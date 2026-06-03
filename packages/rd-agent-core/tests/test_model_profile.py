from __future__ import annotations

from rd_agent_core import ModelProfile, normalize_model_profile
from rd_llm_adapter import ModelCapabilities, ThinkingExtractionConfig


def test_model_profile_derives_protocols_and_provider_lock() -> None:
    profile = ModelProfile(
        profile_id="claude-sonnet",
        provider_id="anthropic",
        model="claude-sonnet-4",
        adapter_kind="anthropic_native",
        capabilities=ModelCapabilities(
            tool_call_style="anthropic_blocks",
            thinking=ThinkingExtractionConfig(
                mode="anthropic_block",
                has_signature=True,
                must_roundtrip=True,
            ),
            supports_stream_usage=False,
        ),
        thinking_budget_tokens=1024,
    )

    lock = profile.to_provider_lock(run_id="run-1")

    assert profile.resolved_adapter_family == "anthropic"
    assert profile.resolved_tool_protocol == "anthropic_tool_use"
    assert profile.resolved_reasoning_protocol == "anthropic_thinking_blocks"
    assert profile.supports_stream_usage is False
    assert profile.is_compatible_with(lock)
    assert lock.locked_at_run_id == "run-1"


def test_normalize_model_profile_accepts_flat_legacy_profile_dict() -> None:
    profile = normalize_model_profile(
        {
            "name": "deepseek",
            "provider": "deepseek",
            "model_name": "deepseek-chat",
            "supports_function_calling": False,
            "supports_stream_usage": False,
            "tool_call_style": "openai_native",
            "max_context": 64000,
            "max_output": 2048,
            "reasoning_effort": "medium",
        }
    )

    assert profile.profile_id == "deepseek"
    assert profile.provider_id == "deepseek"
    assert profile.model == "deepseek-chat"
    assert profile.max_tokens == 2048
    assert profile.context_window == 64000
    assert profile.supports_function_calling is False
    assert profile.supports_stream_usage is False
    assert profile.reasoning_effort == "medium"


def test_anthropic_native_profile_defaults_to_anthropic_tool_protocol() -> None:
    profile = normalize_model_profile(
        None,
        model="claude",
        default_adapter_kind="anthropic_native",
    )

    assert profile.adapter_kind == "anthropic_native"
    assert profile.resolved_adapter_family == "anthropic"
    assert profile.resolved_tool_protocol == "anthropic_tool_use"
