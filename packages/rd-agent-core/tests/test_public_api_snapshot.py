from __future__ import annotations

import inspect
from dataclasses import fields

import rd_agent_core
from rd_agent_core import (
    AgentRunner,
    AgentRunnerRequest,
    ContinuationRunner,
    ContinuationRunnerRequest,
    ContinuationState,
    CoreToolPolicy,
    ModelProfile,
    RunKernel,
    RunRequest,
    SubagentBatchRunner,
    SubagentBatchRunnerError,
    SubagentBatchRunnerRequest,
    SubagentBatchRunnerResult,
    SubagentRunner,
    SubagentRunnerRequest,
    ToolInputValidator,
    ToolOutputBlobWriter,
    ToolOutputLimiter,
    ToolSafetyPolicy,
    TurnKernel,
    TurnRequest,
)
from rd_agent_core.llm_clients import (
    AnthropicNativeLLMClient,
    OpenAICompatLLMClient,
    ProviderClientConfig,
)


def _keyword_only_names(callable_obj) -> tuple[str, ...]:
    signature = inspect.signature(callable_obj)
    return tuple(
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    )


def _dataclass_field_names(cls) -> tuple[str, ...]:
    return tuple(field.name for field in fields(cls))


def test_public_core_exports_snapshot() -> None:
    expected = {
        "AgentRunner",
        "AgentRunnerRequest",
        "AgentRunnerResult",
        "ContinuationRunner",
        "ContinuationRunnerRequest",
        "ContinuationRunnerResult",
        "ContinuationState",
        "CoreErrorCategory",
        "CoreErrorType",
        "ModelProfile",
        "RunKernel",
        "RunObserverPort",
        "RunRequest",
        "RunSummary",
        "SubagentBatchRunner",
        "SubagentBatchRunnerError",
        "SubagentBatchRunnerRequest",
        "SubagentBatchRunnerResult",
        "SubagentRunner",
        "SubagentRunnerRequest",
        "SubagentRunnerResult",
        "ToolSafetyPolicy",
        "ToolInputValidator",
        "ToolOutputBlobWriter",
        "ToolOutputLimiter",
        "TurnKernel",
        "TurnRequest",
        "assert_event_log_port_conformance",
        "assert_run_persistence_port_conformance",
        "assert_tool_executor_port_conformance",
        "continuation_state_from_kernel_result",
    }

    assert expected.issubset(set(rd_agent_core.__all__))


def test_public_constructor_signature_snapshot() -> None:
    assert _keyword_only_names(AgentRunner.__init__) == (
        "run_persistence",
        "event_log",
        "llm_client",
        "tool_executor",
        "tool_observability",
        "tool_policy",
        "run_observer",
        "id_generator",
    )
    assert _keyword_only_names(RunKernel.__init__) == (
        "llm_client",
        "event_writer",
        "tool_executor",
        "tool_observability",
        "tool_policy",
        "id_generator",
        "clock",
    )
    assert _keyword_only_names(TurnKernel.__init__) == (
        "llm_client",
        "event_writer",
        "tool_executor",
        "tool_observability",
        "tool_policy",
    )
    assert _keyword_only_names(SubagentRunner.__init__) == (
        "task_port",
        "run_port",
        "event_log",
        "llm_client",
        "tool_executor",
        "tool_observability",
        "tool_policy",
        "workspace_port",
        "run_observer",
        "id_generator",
    )
    assert _keyword_only_names(ContinuationRunner.__init__) == (
        "continuation_queue",
        "run_persistence",
        "event_log",
        "llm_client",
        "tool_executor",
        "tool_observability",
        "tool_policy",
        "run_observer",
        "id_generator",
    )
    assert _keyword_only_names(SubagentBatchRunner.__init__) == (
        "task_port",
        "runner",
    )


def test_public_dataclass_field_snapshot() -> None:
    assert _dataclass_field_names(AgentRunnerRequest) == (
        "scope",
        "budget",
        "messages",
        "tools",
        "tool_context",
        "run_id",
        "max_continuations",
        "model",
        "model_profile",
        "system_prompt",
        "limits",
        "metadata",
        "cancellation_token",
    )
    assert _dataclass_field_names(RunRequest) == (
        "run_id",
        "messages",
        "tool_context",
        "tools",
        "model",
        "model_profile",
        "system_prompt",
        "limits",
        "metadata",
        "turn_offset",
        "cancellation_token",
    )
    assert _dataclass_field_names(ContinuationRunnerRequest) == (
        "worker_id",
        "budget",
        "limits",
        "tools",
        "tool_context",
        "model",
        "model_profile",
        "system_prompt",
        "metadata",
        "cancellation_token",
        "heartbeat_at_ms",
        "retry_available_at_ms",
    )
    assert _dataclass_field_names(ContinuationState) == (
        "messages",
        "turn_offset",
    )
    assert _dataclass_field_names(SubagentBatchRunnerRequest) == (
        "user_request_id",
        "worker_id",
        "max_count",
        "candidate_limit",
        "started_at_ms",
        "runner_request",
    )
    assert _dataclass_field_names(SubagentBatchRunnerError) == (
        "task_id",
        "error_type",
        "message",
    )
    assert _dataclass_field_names(SubagentBatchRunnerResult) == (
        "claimed_tasks",
        "results",
        "completed_tasks",
        "aggregate_outcome",
        "aggregate_text",
        "errors",
    )
    assert _dataclass_field_names(TurnRequest) == (
        "run_id",
        "turn_id",
        "messages",
        "tool_context",
        "model",
        "model_profile",
        "system_prompt",
        "tools",
        "turn_index",
        "metadata",
        "cancellation_token",
    )
    assert _dataclass_field_names(ToolSafetyPolicy) == (
        "allow_undeclared_tools",
        "allowed_tool_names",
        "blocked_tool_names",
        "require_confirmation_for_mutating_tools",
        "confirmed_tool_use_ids",
    )
    assert _dataclass_field_names(ToolInputValidator) == ("enabled",)
    assert _dataclass_field_names(ToolOutputBlobWriter) == (
        "blob_writer",
        "max_inline_chars",
        "mime_type",
    )
    assert _dataclass_field_names(ToolOutputLimiter) == ("max_content_chars",)
    assert _dataclass_field_names(CoreToolPolicy) == (
        "pause_tool_names",
        "pause_stop_reason",
        "safety_policy",
        "input_validator",
        "output_limiter",
        "output_blob_writer",
        "observability_fail_fast",
    )
    assert _dataclass_field_names(ProviderClientConfig) == (
        "model",
        "api_key",
        "base_url",
        "timeout",
        "max_tokens",
        "extra_headers",
        "profile",
    )
    assert _dataclass_field_names(ModelProfile) == (
        "profile_id",
        "model",
        "provider_id",
        "adapter_kind",
        "adapter_family",
        "tool_protocol",
        "reasoning_protocol",
        "capabilities",
        "protocol_limits",
        "max_tokens",
        "context_window",
        "supports_function_calling",
        "supports_stream_usage",
        "reasoning_effort",
        "thinking_budget_tokens",
        "metadata",
    )
    assert _dataclass_field_names(SubagentRunnerRequest) == (
        "user_request_id",
        "worker_id",
        "session_id",
        "messages",
        "tools",
        "tool_context",
        "model",
        "model_profile",
        "system_prompt",
        "limits",
        "metadata",
        "cancellation_token",
        "workspace_isolation_enabled",
        "inline_parallel_enabled",
        "retryable_needs_attention",
        "failure_retry_delay_seconds",
        "parent_completed_grace_seconds",
        "skip_user_requests_with_running",
    )


def test_provider_client_init_signature_snapshot() -> None:
    assert tuple(inspect.signature(OpenAICompatLLMClient.__init__).parameters) == (
        "self",
        "config",
        "adapter",
        "transport",
        "supports_function_calling",
        "supports_stream_usage",
        "reasoning_effort",
    )
    assert tuple(inspect.signature(AnthropicNativeLLMClient.__init__).parameters) == (
        "self",
        "config",
        "adapter",
        "transport",
        "thinking_budget_tokens",
    )
