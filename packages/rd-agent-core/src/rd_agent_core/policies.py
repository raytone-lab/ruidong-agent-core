"""Pure runtime policies shared by concrete agent hosts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from rd_agent_contracts import StopReason


@dataclass(frozen=True)
class RunLimits:
    max_turns: int | None = None
    max_tool_calls: int | None = None
    timeout_ms: int | None = None
    repeated_tool_call_threshold: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("max_turns", self.max_turns),
            ("max_tool_calls", self.max_tool_calls),
            ("timeout_ms", self.timeout_ms),
            ("repeated_tool_call_threshold", self.repeated_tool_call_threshold),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{name} must be >= 1 when set")


@dataclass(frozen=True)
class ToolRepeatPolicy:
    """Per-tool repeat policy resolved from ``ToolDefinition.metadata``."""

    disabled: bool = False
    threshold: int | None = None

    def __post_init__(self) -> None:
        if self.threshold is not None and self.threshold < 1:
            raise ValueError("threshold must be >= 1 when set")


@dataclass(frozen=True)
class RunLimitState:
    turns_used: int = 0
    tool_calls_used: int = 0
    elapsed_ms: int = 0

    def __post_init__(self) -> None:
        if self.turns_used < 0:
            raise ValueError("turns_used must be >= 0")
        if self.tool_calls_used < 0:
            raise ValueError("tool_calls_used must be >= 0")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must be >= 0")


@dataclass(frozen=True)
class RunLimitDecision:
    allowed: bool
    reason: str | None = None
    limit_name: str | None = None


def evaluate_run_limits(limits: RunLimits, state: RunLimitState) -> RunLimitDecision:
    if limits.max_turns is not None and state.turns_used >= limits.max_turns:
        return RunLimitDecision(False, "max_turns reached", "max_turns")
    if limits.max_tool_calls is not None and state.tool_calls_used >= limits.max_tool_calls:
        return RunLimitDecision(False, "max_tool_calls reached", "max_tool_calls")
    if limits.timeout_ms is not None and state.elapsed_ms >= limits.timeout_ms:
        return RunLimitDecision(
            False,
            "max_wall_clock reached",
            StopReason.MAX_WALL_CLOCK.value,
        )
    return RunLimitDecision(True)


@dataclass(frozen=True)
class ToolCallSignature:
    tool_name: str
    input_digest: str

    def to_key(self) -> str:
        return f"{self.tool_name}:{self.input_digest}"


def tool_call_signature(tool_name: str, tool_input: Mapping[str, Any]) -> ToolCallSignature:
    encoded = json.dumps(tool_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ToolCallSignature(tool_name=tool_name, input_digest=sha256(encoded.encode()).hexdigest())


def tool_repeat_policy_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> ToolRepeatPolicy | None:
    """Resolve repeat policy from tool metadata.

    Supported metadata forms:

    - ``{"repeat_policy": "allow"}`` disables repeated-call blocking.
    - ``{"repeat_policy": {"enabled": False}}`` disables blocking.
    - ``{"repeat_policy": {"threshold": 5}}`` overrides the run default.
    - ``{"tool_repeat_policy": ...}`` is accepted as an explicit alias.
    """

    if not metadata:
        return None
    raw = metadata.get("repeat_policy")
    if raw is None:
        raw = metadata.get("tool_repeat_policy")
    if raw is None:
        return None

    if isinstance(raw, str):
        mode = raw.strip().lower()
        if mode in {"allow", "allow_repeated", "disabled", "ignore", "off"}:
            return ToolRepeatPolicy(disabled=True)
        if mode in {"default", "strict", "enabled", "on"}:
            return None
        return None

    if isinstance(raw, bool):
        return ToolRepeatPolicy(disabled=not raw)

    if isinstance(raw, int):
        return ToolRepeatPolicy(threshold=raw) if raw >= 1 else None

    if not isinstance(raw, Mapping):
        return None

    enabled = raw.get("enabled")
    mode_value = raw.get("mode") or raw.get("behavior")
    mode = str(mode_value).strip().lower() if mode_value is not None else ""
    if enabled is False or mode in {"allow", "allow_repeated", "disabled", "ignore", "off"}:
        return ToolRepeatPolicy(disabled=True)

    threshold = _positive_int(raw.get("threshold"))
    if threshold is not None:
        return ToolRepeatPolicy(threshold=threshold)

    if enabled is True or mode in {"default", "strict", "enabled", "on"}:
        return None
    return None


def repeat_threshold_for_tool(
    *,
    tool_name: str,
    policies: Mapping[str, ToolRepeatPolicy],
    default_threshold: int | None,
) -> int | None:
    policy = policies.get(tool_name)
    if policy is None:
        return default_threshold
    if policy.disabled:
        return None
    if policy.threshold is not None:
        return policy.threshold
    return default_threshold


def has_repeated_tool_call(
    history: Iterable[ToolCallSignature],
    *,
    candidate: ToolCallSignature,
    threshold: int,
) -> bool:
    if threshold < 1:
        raise ValueError("threshold must be >= 1")
    repeated = sum(1 for item in history if item == candidate)
    return repeated >= threshold


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            parsed = int(stripped)
            return parsed if parsed >= 1 else None
    return None
