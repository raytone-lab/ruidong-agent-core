from rd_agent_contracts.provider_lock import ProviderLock


def test_provider_lock_anthropic():
    lock = ProviderLock(
        provider_id="anthropic-direct",
        adapter_family="anthropic",
        tool_protocol="anthropic_tool_use",
        reasoning_protocol="anthropic_thinking",
        locked_at_run_id="run_123",
    )
    assert lock.provider_id == "anthropic-direct"
    assert lock.adapter_family == "anthropic"


def test_provider_lock_openai_compat():
    lock = ProviderLock(
        provider_id="openrouter-claude",
        adapter_family="openai_compat",
        tool_protocol="openai_tool_calls",
        reasoning_protocol=None,
        locked_at_run_id="run_456",
    )
    assert lock.reasoning_protocol is None


def test_provider_lock_compatible_adapter():
    """同一 transcript 内只能换"协议族相同"的 provider。"""
    lock = ProviderLock(
        provider_id="anthropic-direct",
        adapter_family="anthropic",
        tool_protocol="anthropic_tool_use",
        reasoning_protocol="anthropic_thinking",
        locked_at_run_id="run_123",
    )
    assert lock.is_compatible_with(
        adapter_family="anthropic", tool_protocol="anthropic_tool_use"
    )
    assert not lock.is_compatible_with(
        adapter_family="openai_compat", tool_protocol="openai_tool_calls"
    )
