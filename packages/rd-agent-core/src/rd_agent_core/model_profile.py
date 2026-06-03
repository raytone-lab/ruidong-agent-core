"""Runtime model profile normalization and provider-lock helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from rd_agent_contracts import ProviderLock
from rd_llm_adapter import ModelCapabilities, ProtocolLimits, ThinkingExtractionConfig

ReasoningEffort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ModelProfile:
    """Host-neutral model/runtime protocol profile.

    The profile intentionally contains no API key or tenant secret. It describes
    how core and provider adapters should treat a model: adapter family, tool
    protocol, reasoning protocol, and capability limits.
    """

    profile_id: str
    model: str
    provider_id: str = ""
    adapter_kind: str = "openai_compat"
    adapter_family: str | None = None
    tool_protocol: str | None = None
    reasoning_protocol: str | None = None
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    protocol_limits: ProtocolLimits = field(default_factory=ProtocolLimits)
    max_tokens: int | None = None
    context_window: int | None = None
    supports_function_calling: bool | None = None
    supports_stream_usage: bool | None = None
    reasoning_effort: ReasoningEffort | None = None
    thinking_budget_tokens: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.model or "").strip():
            raise ValueError("model must be non-empty")
        if not str(self.adapter_kind or "").strip():
            raise ValueError("adapter_kind must be non-empty")
        if not str(self.profile_id or "").strip():
            object.__setattr__(self, "profile_id", self.model)
        if self.max_tokens is None:
            object.__setattr__(self, "max_tokens", self.capabilities.max_output)
        if self.context_window is None:
            object.__setattr__(self, "context_window", self.capabilities.max_context)
        if self.supports_function_calling is None:
            object.__setattr__(
                self,
                "supports_function_calling",
                self.capabilities.supports_tool_use,
            )
        if self.supports_stream_usage is None:
            object.__setattr__(
                self,
                "supports_stream_usage",
                self.capabilities.supports_stream_usage,
            )

    @property
    def resolved_adapter_family(self) -> str:
        if self.adapter_family:
            return self.adapter_family
        if self.adapter_kind == "anthropic_native":
            return "anthropic"
        if self.adapter_kind == "openai_compat":
            return "openai_compat"
        return self.adapter_kind

    @property
    def resolved_tool_protocol(self) -> str:
        if self.tool_protocol:
            return self.tool_protocol
        if self.adapter_kind == "anthropic_native":
            return "anthropic_tool_use"
        return {
            "anthropic_blocks": "anthropic_tool_use",
            "gemini_functions": "gemini_function_calling",
            "openai_native": "openai_tool_calls",
        }.get(self.capabilities.tool_call_style, self.capabilities.tool_call_style)

    @property
    def resolved_reasoning_protocol(self) -> str | None:
        if self.reasoning_protocol is not None:
            return self.reasoning_protocol
        mode = self.capabilities.thinking.mode
        return {
            "anthropic_block": "anthropic_thinking_blocks",
            "openai_field": "openai_reasoning_field",
            "openai_responses": "openai_responses_reasoning",
            "xml_tag": "xml_tag_reasoning",
        }.get(mode)

    def to_provider_lock(self, *, run_id: str) -> ProviderLock:
        return ProviderLock(
            provider_id=self.provider_id or self.profile_id,
            adapter_family=self.resolved_adapter_family,
            tool_protocol=self.resolved_tool_protocol,
            reasoning_protocol=self.resolved_reasoning_protocol,
            locked_at_run_id=run_id,
        )

    def is_compatible_with(self, lock: ProviderLock) -> bool:
        return lock.is_compatible_with(
            self.resolved_adapter_family,
            self.resolved_tool_protocol,
            self.resolved_reasoning_protocol,
        )

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "model": self.model,
            "adapter_kind": self.adapter_kind,
            "adapter_family": self.resolved_adapter_family,
            "tool_protocol": self.resolved_tool_protocol,
            "reasoning_protocol": self.resolved_reasoning_protocol,
            "max_tokens": self.max_tokens,
            "context_window": self.context_window,
            "supports_function_calling": self.supports_function_calling,
            "supports_stream_usage": self.supports_stream_usage,
        }


def normalize_model_profile(
    raw_profile: Any | None,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    default_adapter_kind: str = "openai_compat",
) -> ModelProfile:
    if isinstance(raw_profile, ModelProfile):
        return raw_profile

    values = _profile_values(raw_profile)
    resolved_model = _first_string(
        values,
        "model",
        "model_name",
        "requested_model",
        "provider_model_name",
    ) or str(model or "").strip()
    if not resolved_model:
        raise ValueError("model must be provided when profile does not define one")

    capabilities = _coerce_capabilities(values)
    return ModelProfile(
        profile_id=(
            _first_string(values, "profile_id", "id", "name", "model_profile")
            or resolved_model
        ),
        provider_id=_first_string(values, "provider_id", "provider", "vendor") or "",
        model=resolved_model,
        adapter_kind=_first_string(values, "adapter_kind") or default_adapter_kind,
        adapter_family=_first_string(values, "adapter_family", "provider_family"),
        tool_protocol=_first_string(values, "tool_protocol"),
        reasoning_protocol=_first_string(values, "reasoning_protocol"),
        capabilities=capabilities,
        protocol_limits=_coerce_protocol_limits(values.get("protocol_limits")),
        max_tokens=_first_int(values, "max_tokens", "max_output") or max_tokens,
        context_window=_first_int(values, "context_window", "max_context"),
        supports_function_calling=_first_bool(
            values,
            "supports_function_calling",
            "supports_tool_use",
        ),
        supports_stream_usage=_first_bool(values, "supports_stream_usage"),
        reasoning_effort=_coerce_reasoning_effort(values.get("reasoning_effort")),
        thinking_budget_tokens=_first_int(values, "thinking_budget_tokens"),
        metadata=values.get("metadata") if isinstance(values.get("metadata"), Mapping) else {},
    )


def _profile_values(raw_profile: Any | None) -> dict[str, Any]:
    if raw_profile is None:
        return {}
    if isinstance(raw_profile, Mapping):
        return dict(raw_profile)
    keys = (
        "adapter_family",
        "adapter_kind",
        "capabilities",
        "context_window",
        "id",
        "max_context",
        "max_output",
        "max_tokens",
        "metadata",
        "model",
        "model_name",
        "model_profile",
        "name",
        "profile_id",
        "protocol_limits",
        "provider",
        "provider_family",
        "provider_id",
        "provider_model_name",
        "reasoning_effort",
        "reasoning_protocol",
        "requested_model",
        "supports_function_calling",
        "supports_stream_usage",
        "supports_tool_use",
        "thinking_budget_tokens",
        "tool_call_style",
        "tool_protocol",
        "vendor",
    )
    return {key: getattr(raw_profile, key) for key in keys if hasattr(raw_profile, key)}


def _coerce_capabilities(values: Mapping[str, Any]) -> ModelCapabilities:
    raw = values.get("capabilities")
    if isinstance(raw, ModelCapabilities):
        return raw
    data = dict(raw) if isinstance(raw, Mapping) else {}
    thinking = data.get("thinking")
    if isinstance(thinking, Mapping):
        data["thinking"] = ThinkingExtractionConfig(
            **_known_fields(thinking, ThinkingExtractionConfig)
        )
    for source, target in (
        ("supports_tool_use", "supports_tool_use"),
        ("tool_call_style", "tool_call_style"),
        ("supports_stream_usage", "supports_stream_usage"),
        ("max_context", "max_context"),
        ("context_window", "max_context"),
        ("max_output", "max_output"),
        ("max_tokens", "max_output"),
    ):
        if source in values and values[source] is not None:
            data[target] = values[source]
    return ModelCapabilities(**_known_fields(data, ModelCapabilities))


def _coerce_protocol_limits(raw: Any) -> ProtocolLimits:
    if isinstance(raw, ProtocolLimits):
        return raw
    if isinstance(raw, Mapping):
        return ProtocolLimits(**_known_fields(raw, ProtocolLimits))
    return ProtocolLimits()


def _known_fields(raw: Mapping[str, Any], cls: type) -> dict[str, Any]:
    field_names = set(getattr(cls, "__dataclass_fields__", ()))
    return {str(key): value for key, value in raw.items() if str(key) in field_names}


def _first_string(values: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _first_int(values: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = values.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_bool(values: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool):
            return value
    return None


def _coerce_reasoning_effort(value: Any) -> ReasoningEffort | None:
    if value in {"low", "medium", "high"}:
        return value
    return None


def model_profile_to_dict(profile: ModelProfile) -> dict[str, Any]:
    payload = asdict(profile)
    payload["capabilities"] = asdict(profile.capabilities)
    payload["protocol_limits"] = asdict(profile.protocol_limits)
    return payload
