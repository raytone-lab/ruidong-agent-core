"""Turn-level runtime kernel.

The kernel consumes provider-normalized ``rd-llm-adapter`` events, writes
canonical ``AgentEvent`` records, and executes completed tool calls through
injected contracts. It intentionally has no database, SaaS, frontend, or
business-agent dependencies.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from hashlib import sha256
from typing import Any, Protocol

from rd_agent_contracts import (
    AgentEvent,
    BlobRef,
    BlobWriter,
    CancellationToken,
    InvalidToolCall,
    Message,
    StandardContentBlock,
    ToolCallCounts,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutorPort,
    ToolObservabilityPort,
    ToolObservabilityRecord,
    ToolUseBlock,
    Usage,
)
from rd_llm_adapter.events import (
    ReasoningDelta,
    StandardEvent,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallEnd,
    ToolCallIdDelta,
    ToolCallNameDelta,
    ToolCallStart,
    TurnDone,
    UsageUpdate,
)

from .errors import CoreErrorType, core_error
from .events import CoreEventType, CoreEventWriter
from .model_profile import ModelProfile


@dataclass(frozen=True)
class TurnRequest:
    run_id: str
    turn_id: str
    messages: Sequence[Message]
    tool_context: ToolExecutionContext
    model: str | None = None
    model_profile: ModelProfile | None = None
    system_prompt: str | None = None
    tools: Sequence[ToolDefinition] = ()
    turn_index: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken | None = None


@dataclass(frozen=True)
class ToolSafetyPolicy:
    allow_undeclared_tools: bool = False
    allowed_tool_names: frozenset[str] | None = None
    blocked_tool_names: frozenset[str] = field(default_factory=frozenset)
    require_confirmation_for_mutating_tools: bool = False
    confirmed_tool_use_ids: frozenset[str] = field(default_factory=frozenset)

    def evaluate(
        self,
        tool_call: ToolUseBlock,
        declared_tools: Sequence[ToolDefinition],
    ) -> ToolExecutionResult | None:
        details = {"tool_name": tool_call.name, "tool_use_id": tool_call.id}
        if tool_call.name in self.blocked_tool_names:
            return _tool_policy_denial(
                "tool_blocked",
                "Tool call blocked by tool safety policy.",
                details,
            )
        if (
            self.allowed_tool_names is not None
            and tool_call.name not in self.allowed_tool_names
        ):
            return _tool_policy_denial(
                "tool_not_allowed",
                "Tool call is not in the safety policy allowlist.",
                details,
            )

        declared_tool = next(
            (tool for tool in declared_tools if tool.name == tool_call.name),
            None,
        )
        if (
            declared_tool is not None
            and declared_tool.mutates_workspace
            and self.require_confirmation_for_mutating_tools
            and tool_call.id not in self.confirmed_tool_use_ids
        ):
            return _tool_policy_denial(
                "tool_confirmation_required",
                "Mutating tool call requires host confirmation.",
                details,
            )
        return None


@dataclass(frozen=True)
class ToolInputValidator:
    """Minimal JSON-schema validator for declared tool input schemas."""

    enabled: bool = True

    def evaluate(
        self,
        tool_call: ToolUseBlock,
        declared_tool: ToolDefinition | None,
    ) -> ToolExecutionResult | None:
        if not self.enabled or declared_tool is None:
            return None
        error_message = _schema_error(tool_call.input, declared_tool.input_schema)
        if error_message is None:
            return None
        return _tool_result(
            ok=False,
            content="",
            tool_use_id=tool_call.id,
            error=core_error(
                CoreErrorType.TOOL_INPUT_INVALID.value,
                error_message,
                details={"tool_name": tool_call.name, "tool_use_id": tool_call.id},
            ),
            executed=False,
        )


@dataclass(frozen=True)
class ToolOutputLimiter:
    max_content_chars: int

    def __post_init__(self) -> None:
        if self.max_content_chars < 1:
            raise ValueError("max_content_chars must be >= 1")

    def limit(self, result: ToolExecutionResult) -> ToolExecutionResult:
        if len(result.content) <= self.max_content_chars:
            return result
        return replace(
            result,
            content=result.content[: self.max_content_chars],
            metadata={
                **dict(result.metadata),
                "output_truncated": True,
                "original_content_chars": len(result.content),
            },
        )


@dataclass(frozen=True)
class ToolOutputBlobWriter:
    blob_writer: BlobWriter
    max_inline_chars: int = 8192
    mime_type: str = "text/plain"

    def __post_init__(self) -> None:
        if self.max_inline_chars < 0:
            raise ValueError("max_inline_chars must be >= 0")

    async def write_if_needed(self, result: ToolExecutionResult) -> ToolExecutionResult:
        if len(result.content) <= self.max_inline_chars:
            return result
        content_bytes = result.content.encode("utf-8")
        content_ref, content_sha256 = await self.blob_writer.write_large_payload(
            content_bytes,
            self.mime_type,
        )
        if not content_sha256:
            content_sha256 = sha256(content_bytes).hexdigest()
        inline = result.content[: self.max_inline_chars] if self.max_inline_chars else None
        blob_ref = BlobRef(
            content_bytes=len(content_bytes),
            content_sha256=content_sha256,
            mime_type=self.mime_type,
            content_inline=inline,
            content_ref=content_ref,
            content_inline_truncated=inline is not None,
        )
        return replace(
            result,
            content=inline or "",
            metadata={
                **dict(result.metadata),
                "blob_ref": asdict(blob_ref),
            },
        )


@dataclass(frozen=True)
class CoreToolPolicy:
    pause_tool_names: frozenset[str] = field(default_factory=frozenset)
    pause_stop_reason: str = "pause_requested"
    safety_policy: ToolSafetyPolicy = field(default_factory=ToolSafetyPolicy)
    input_validator: ToolInputValidator | None = field(default_factory=ToolInputValidator)
    output_limiter: ToolOutputLimiter | None = None
    output_blob_writer: ToolOutputBlobWriter | None = None
    observability_fail_fast: bool = False

    def is_pause_tool(self, tool_name: str) -> bool:
        return tool_name in self.pause_tool_names


@dataclass(frozen=True)
class TurnKernelResult:
    stop_reason: str
    raw_stop_reason: str
    content: tuple[StandardContentBlock, ...]
    usage: Usage
    tool_results: tuple[ToolExecutionResult, ...]
    invalid_tool_calls: tuple[InvalidToolCall, ...]
    events: tuple[AgentEvent, ...]
    tool_call_counts: ToolCallCounts = field(default_factory=ToolCallCounts)
    pause_requested: bool = False
    provider_state: Any | None = None

    @property
    def tool_calls_requested(self) -> int:
        return self.tool_call_counts.requested

    @property
    def tool_calls_executed(self) -> int:
        return self.tool_call_counts.executed

    @property
    def tool_calls_denied(self) -> int:
        return self.tool_call_counts.denied


@dataclass
class _StandardEventIdempotencyState:
    text_delta_counts: dict[int, int] = field(default_factory=dict)
    reasoning_delta_counts: dict[int, int] = field(default_factory=dict)
    tool_call_id_delta_counts: dict[int, int] = field(default_factory=dict)
    tool_call_name_delta_counts: dict[int, int] = field(default_factory=dict)
    tool_call_args_delta_counts: dict[int, int] = field(default_factory=dict)

    def key_for(
        self,
        *,
        turn_id: str,
        event: StandardEvent,
        usage_update_index: int | None = None,
    ) -> str | None:
        if isinstance(event, TextDelta):
            delta_index = self._next(self.text_delta_counts, event.block_index)
            return f"{turn_id}:text_delta:{event.block_index}:{delta_index}"
        if isinstance(event, ReasoningDelta):
            delta_index = self._next(
                self.reasoning_delta_counts,
                event.block_index,
            )
            return f"{turn_id}:reasoning_delta:{event.block_index}:{delta_index}"
        if isinstance(event, ToolCallStart):
            return f"{turn_id}:tool_call:{event.index}:started"
        if isinstance(event, ToolCallIdDelta):
            delta_index = self._next(self.tool_call_id_delta_counts, event.index)
            return f"{turn_id}:tool_call:{event.index}:id_delta:{delta_index}"
        if isinstance(event, ToolCallNameDelta):
            delta_index = self._next(self.tool_call_name_delta_counts, event.index)
            return f"{turn_id}:tool_call:{event.index}:name_delta:{delta_index}"
        if isinstance(event, ToolCallArgsDelta):
            delta_index = self._next(self.tool_call_args_delta_counts, event.index)
            return f"{turn_id}:tool_call:{event.index}:args_delta:{delta_index}"
        if isinstance(event, ToolCallEnd):
            return f"{turn_id}:tool_call:{event.index}:completed"
        if isinstance(event, UsageUpdate) and usage_update_index is not None:
            return f"{turn_id}:usage:{usage_update_index}"
        return None

    @staticmethod
    def _next(counts: dict[int, int], key: int) -> int:
        count = counts.get(key, 0) + 1
        counts[key] = count
        return count


class LLMClientPort(Protocol):
    def stream_turn(self, request: TurnRequest) -> AsyncIterable[StandardEvent]: ...


class AsyncToolExecutorPort(Protocol):
    async def execute_tool(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


ToolExecutorLike = ToolExecutorPort | AsyncToolExecutorPort


class TurnKernel:
    def __init__(
        self,
        *,
        llm_client: LLMClientPort,
        event_writer: CoreEventWriter,
        tool_executor: ToolExecutorLike | None = None,
        tool_observability: ToolObservabilityPort | None = None,
        tool_policy: CoreToolPolicy | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._event_writer = event_writer
        self._tool_executor = tool_executor
        self._tool_observability = tool_observability
        self._tool_policy = tool_policy or CoreToolPolicy()

    async def run_turn(self, request: TurnRequest) -> TurnKernelResult:
        if request.run_id != self._event_writer.run_id:
            raise ValueError("TurnRequest.run_id must match CoreEventWriter.run_id")

        writer = self._event_writer.with_turn(request.turn_id)
        events: list[AgentEvent] = [
            writer.append(
                CoreEventType.TURN_STARTED,
                {
                    "model": request.model,
                    "model_profile": (
                        request.model_profile.to_event_payload()
                        if request.model_profile is not None
                        else None
                    ),
                    "turn_index": request.turn_index,
                    "metadata": dict(request.metadata),
                },
                idempotency_key=f"{request.turn_id}:turn_started",
            )
        ]
        turn_done: TurnDone | None = None
        last_usage_update: UsageUpdate | None = None
        usage_update_index = 0
        event_idempotency = _StandardEventIdempotencyState()
        cancelled = _is_cancelled(request.cancellation_token)

        if not cancelled:
            async for event in self._llm_client.stream_turn(request):
                if isinstance(event, UsageUpdate):
                    usage_update_index += 1
                    last_usage_update = event
                    emitted = self._emit_standard_event(
                        writer,
                        event,
                        usage_update_index=usage_update_index,
                        event_idempotency=event_idempotency,
                    )
                elif isinstance(event, TurnDone):
                    turn_done = event
                    emitted = self._emit_standard_event(
                        writer,
                        event,
                        event_idempotency=event_idempotency,
                    )
                else:
                    emitted = self._emit_standard_event(
                        writer,
                        event,
                        event_idempotency=event_idempotency,
                    )
                if emitted is not None:
                    events.append(emitted)
                if _is_cancelled(request.cancellation_token):
                    cancelled = True
                    break

        if cancelled:
            usage = _usage_from_update(last_usage_update)
            events.append(
                writer.append(
                    CoreEventType.TURN_COMPLETED,
                    {
                        "stop_reason": CoreErrorType.CANCELLED.value,
                        "raw_stop_reason": CoreErrorType.CANCELLED.value,
                        "tool_calls_requested": 0,
                        "tool_calls_executed": 0,
                        "tool_calls_denied": 0,
                        "invalid_tool_calls": 0,
                        "pause_requested": False,
                        "terminal_text": "",
                        "terminal_reasoning": "",
                        "usage": asdict(usage),
                    },
                    idempotency_key=f"{request.turn_id}:turn_completed",
                )
            )
            return TurnKernelResult(
                stop_reason=CoreErrorType.CANCELLED.value,
                raw_stop_reason=CoreErrorType.CANCELLED.value,
                content=(),
                usage=usage,
                tool_results=(),
                invalid_tool_calls=(),
                events=tuple(events),
                tool_call_counts=ToolCallCounts(),
            )

        if turn_done is None:
            raise RuntimeError("LLMClientPort.stream_turn completed without TurnDone")

        invalid_tool_calls = tuple(
            block for block in turn_done.content if isinstance(block, InvalidToolCall)
        )
        for invalid in invalid_tool_calls:
            events.append(
                writer.append(
                    CoreEventType.TOOL_CALL_INVALID,
                    _dataclass_payload(invalid),
                    idempotency_key=f"{request.turn_id}:invalid_tool:{invalid.id}",
                )
            )

        tool_results: list[ToolExecutionResult] = []
        pause_requested = False
        tool_calls = tuple(block for block in turn_done.content if isinstance(block, ToolUseBlock))
        for tool_call in tool_calls:
            if _is_cancelled(request.cancellation_token):
                cancelled = True
                result, result_events = self._skip_tool_after_cancellation(
                    writer,
                    request,
                    tool_call,
                )
            elif pause_requested:
                result, result_events = self._skip_tool_after_pause(writer, request, tool_call)
            else:
                result, result_events = await self._execute_tool(writer, request, tool_call)
            tool_results.append(result)
            events.extend(result_events)
            if result.ok and self._tool_policy.is_pause_tool(tool_call.name):
                pause_requested = True
                events.append(
                    writer.append(
                        CoreEventType.TURN_PAUSED,
                        {
                            "tool_name": tool_call.name,
                            "tool_use_id": tool_call.id,
                            "stop_reason": self._tool_policy.pause_stop_reason,
                        },
                        idempotency_key=f"{request.turn_id}:paused:{tool_call.id}",
                    )
                )

        tool_call_counts = _tool_call_counts(
            requested=len(tool_calls),
            tool_results=tool_results,
        )
        usage = _usage_from_update(turn_done.usage or last_usage_update)
        final_stop_reason = CoreErrorType.CANCELLED.value if cancelled else (
            self._tool_policy.pause_stop_reason if pause_requested else turn_done.stop_reason
        )
        events.append(
            writer.append(
                CoreEventType.TURN_COMPLETED,
                {
                    "stop_reason": final_stop_reason,
                    "raw_stop_reason": turn_done.raw_stop_reason,
                    "tool_calls_requested": tool_call_counts.requested,
                    "tool_calls_executed": tool_call_counts.executed,
                    "tool_calls_denied": tool_call_counts.denied,
                    "invalid_tool_calls": len(invalid_tool_calls),
                    "pause_requested": pause_requested,
                    "terminal_text": _joined_content_text(turn_done.content, "text"),
                    "terminal_reasoning": _joined_content_text(
                        turn_done.content,
                        "reasoning",
                    ),
                    "usage": asdict(usage),
                },
                idempotency_key=f"{request.turn_id}:turn_completed",
            )
        )

        return TurnKernelResult(
            stop_reason=final_stop_reason,
            raw_stop_reason=turn_done.raw_stop_reason,
            content=tuple(turn_done.content),
            usage=usage,
            tool_results=tuple(tool_results),
            invalid_tool_calls=invalid_tool_calls,
            events=tuple(events),
            tool_call_counts=tool_call_counts,
            pause_requested=pause_requested,
            provider_state=turn_done.provider_state,
        )

    def _skip_tool_after_pause(
        self,
        writer: CoreEventWriter,
        request: TurnRequest,
        tool_call: ToolUseBlock,
    ) -> tuple[ToolExecutionResult, list[AgentEvent]]:
        message = "Execution paused before this tool call because a pause tool already ran."
        result = _tool_result(
            ok=False,
            content=message,
            tool_use_id=tool_call.id,
            error={
                "type": "tool_skipped_after_pause",
                "message": message,
                "category": "tool_policy",
                "details": {
                    "tool_name": tool_call.name,
                    "tool_use_id": tool_call.id,
                    },
            },
            executed=False,
        )
        return result, [
            writer.append(
                CoreEventType.TOOL_STARTED,
                {"tool_name": tool_call.name, "tool_use_id": tool_call.id},
                idempotency_key=f"{request.turn_id}:tool:{tool_call.id}:started",
            ),
            writer.append(
                CoreEventType.TOOL_FAILED,
                {
                    "tool_name": tool_call.name,
                    "tool_use_id": tool_call.id,
                    "result": _dataclass_payload(result),
                },
                idempotency_key=f"{request.turn_id}:tool:{tool_call.id}:completed",
            ),
        ]

    def _skip_tool_after_cancellation(
        self,
        writer: CoreEventWriter,
        request: TurnRequest,
        tool_call: ToolUseBlock,
    ) -> tuple[ToolExecutionResult, list[AgentEvent]]:
        message = "Execution cancelled before this tool call ran."
        result = _tool_result(
            ok=False,
            content=message,
            tool_use_id=tool_call.id,
            error=core_error(
                CoreErrorType.CANCELLED.value,
                message,
                details={
                    "tool_name": tool_call.name,
                    "tool_use_id": tool_call.id,
                },
            ),
            executed=False,
        )
        return result, [
            writer.append(
                CoreEventType.TOOL_STARTED,
                {"tool_name": tool_call.name, "tool_use_id": tool_call.id},
                idempotency_key=f"{request.turn_id}:tool:{tool_call.id}:started",
            ),
            writer.append(
                CoreEventType.TOOL_FAILED,
                {
                    "tool_name": tool_call.name,
                    "tool_use_id": tool_call.id,
                    "result": _dataclass_payload(result),
                },
                idempotency_key=f"{request.turn_id}:tool:{tool_call.id}:completed",
            ),
        ]

    def _emit_standard_event(
        self,
        writer: CoreEventWriter,
        event: StandardEvent,
        *,
        usage_update_index: int | None = None,
        event_idempotency: _StandardEventIdempotencyState,
    ) -> AgentEvent | None:
        if isinstance(event, TextDelta):
            return writer.append(
                CoreEventType.TEXT_DELTA,
                {"text": event.text, "block_index": event.block_index},
                idempotency_key=event_idempotency.key_for(
                    turn_id=writer.turn_id,
                    event=event,
                ),
            )
        if isinstance(event, ReasoningDelta):
            return writer.append(
                CoreEventType.REASONING_DELTA,
                {
                    "text": event.text,
                    "block_index": event.block_index,
                    "provider_data": event.provider_data,
                },
                idempotency_key=event_idempotency.key_for(
                    turn_id=writer.turn_id,
                    event=event,
                ),
            )
        if isinstance(event, ToolCallStart):
            return writer.append(
                CoreEventType.TOOL_CALL_STARTED,
                _dataclass_payload(event),
                idempotency_key=event_idempotency.key_for(
                    turn_id=writer.turn_id,
                    event=event,
                ),
            )
        if isinstance(event, ToolCallIdDelta | ToolCallNameDelta | ToolCallArgsDelta):
            return writer.append(
                CoreEventType.TOOL_CALL_DELTA,
                _dataclass_payload(event),
                idempotency_key=event_idempotency.key_for(
                    turn_id=writer.turn_id,
                    event=event,
                ),
            )
        if isinstance(event, ToolCallEnd):
            return writer.append(
                CoreEventType.TOOL_CALL_COMPLETED,
                _dataclass_payload(event),
                idempotency_key=event_idempotency.key_for(
                    turn_id=writer.turn_id,
                    event=event,
                ),
            )
        if isinstance(event, UsageUpdate):
            payload = event.to_dict()
            if usage_update_index is not None:
                payload["usage_sequence"] = usage_update_index
            return writer.append(
                CoreEventType.USAGE_UPDATE,
                payload,
                idempotency_key=event_idempotency.key_for(
                    turn_id=writer.turn_id,
                    event=event,
                    usage_update_index=usage_update_index,
                ),
            )
        return None

    async def _execute_tool(
        self,
        writer: CoreEventWriter,
        request: TurnRequest,
        tool_call: ToolUseBlock,
    ) -> tuple[ToolExecutionResult, list[AgentEvent]]:
        events = [
            writer.append(
                CoreEventType.TOOL_STARTED,
                {"tool_name": tool_call.name, "tool_use_id": tool_call.id},
                idempotency_key=f"{request.turn_id}:tool:{tool_call.id}:started",
            )
        ]

        declared_tool = next(
            (tool for tool in request.tools if tool.name == tool_call.name),
            None,
        )
        if (
            declared_tool is None
            and not self._tool_policy.safety_policy.allow_undeclared_tools
        ):
            result = _tool_result(
                ok=False,
                content="",
                tool_use_id=tool_call.id,
                error=core_error(
                    CoreErrorType.TOOL_NOT_DECLARED.value,
                    f"Tool is not declared for this turn: {tool_call.name}",
                    details={"tool_name": tool_call.name, "tool_use_id": tool_call.id},
                ),
                executed=False,
            )
        elif (
            safety_result := self._tool_policy.safety_policy.evaluate(
                tool_call,
                request.tools,
            )
        ) is not None:
            result = safety_result
        elif (
            self._tool_policy.input_validator is not None
            and (
                validation_result := self._tool_policy.input_validator.evaluate(
                    tool_call,
                    declared_tool,
                )
            )
            is not None
        ):
            result = validation_result
        elif self._tool_executor is None:
            result = _tool_result(
                ok=False,
                content="",
                tool_use_id=tool_call.id,
                error=core_error(
                    CoreErrorType.TOOL_EXECUTOR_MISSING.value,
                    "No ToolExecutorPort was provided for tool execution.",
                    details={"tool_name": tool_call.name, "tool_use_id": tool_call.id},
                ),
                executed=False,
            )
        else:
            try:
                tool_context = replace(
                    request.tool_context,
                    metadata={
                        **dict(request.tool_context.metadata),
                        "core_turn_id": request.turn_id,
                    },
                )
                raw_result = self._tool_executor.execute_tool(
                    ToolExecutionRequest(
                        tool_name=tool_call.name,
                        tool_input=dict(tool_call.input),
                        context=tool_context,
                        tool_use_id=tool_call.id,
                        turn=request.turn_index,
                    )
                )
                result = _normalize_tool_result(
                    await raw_result if inspect.isawaitable(raw_result) else raw_result,
                    tool_use_id=tool_call.id,
                    executed=True,
                )
                if self._tool_policy.output_blob_writer is not None:
                    result = await self._tool_policy.output_blob_writer.write_if_needed(
                        result
                    )
                if self._tool_policy.output_limiter is not None:
                    result = self._tool_policy.output_limiter.limit(result)
            except Exception as exc:  # noqa: BLE001 - tool boundary must fail closed.
                result = _tool_result(
                    ok=False,
                    content="",
                    tool_use_id=tool_call.id,
                    error=core_error(
                        exc.__class__.__name__,
                        str(exc),
                        category="tool_error",
                    ),
                    executed=True,
                )

        completed_type = CoreEventType.TOOL_COMPLETED if result.ok else CoreEventType.TOOL_FAILED
        events.append(
            writer.append(
                completed_type,
                {
                    "tool_name": tool_call.name,
                    "tool_use_id": tool_call.id,
                    "result": _dataclass_payload(result),
                },
                idempotency_key=f"{request.turn_id}:tool:{tool_call.id}:completed",
            )
        )
        self._record_tool_observability(request, tool_call, result)
        return result, events

    def _record_tool_observability(
        self,
        request: TurnRequest,
        tool_call: ToolUseBlock,
        result: ToolExecutionResult,
    ) -> None:
        if self._tool_observability is None:
            return
        try:
            self._tool_observability.record_tool_calls(
                [
                    ToolObservabilityRecord(
                        project_id=request.tool_context.project_id,
                        session_id=request.tool_context.session_id,
                        tool_name=tool_call.name,
                        tool_input=tool_call.input,
                        tool_output=result.content,
                        ok=result.ok,
                        correlation_id=request.tool_context.correlation_id,
                        error=result.error,
                        duration_ms=result.duration_ms,
                        tool_use_id=tool_call.id,
                        turn=request.turn_index,
                    )
                ]
            )
        except Exception:
            if self._tool_policy.observability_fail_fast:
                raise


def _usage_from_update(update: UsageUpdate | None) -> Usage:
    if update is None:
        return Usage()
    return Usage(
        input_tokens=update.input_tokens,
        output_tokens=update.output_tokens,
        cache_creation_input_tokens=update.cache_creation_input_tokens,
        cache_read_input_tokens=update.cache_read_input_tokens,
    )


def _dataclass_payload(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


def _tool_policy_denial(
    error_type: str,
    message: str,
    details: dict[str, Any],
) -> ToolExecutionResult:
    return _tool_result(
        ok=False,
        content="",
        tool_use_id=str(details.get("tool_use_id") or ""),
        error=core_error(error_type, message, details=details),
        executed=False,
    )


def _tool_result(
    *,
    ok: bool,
    content: str,
    tool_use_id: str,
    error: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    metadata: Mapping[str, Any] | None = None,
    executed: bool,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        ok=ok,
        content=content,
        tool_use_id=tool_use_id,
        error=error,
        duration_ms=duration_ms,
        metadata={**dict(metadata or {}), "executed": executed},
    )


def _normalize_tool_result(
    result: ToolExecutionResult,
    *,
    tool_use_id: str,
    executed: bool,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        ok=result.ok,
        content=result.content,
        tool_use_id=result.tool_use_id or tool_use_id,
        error=result.error,
        duration_ms=result.duration_ms,
        metadata={**dict(result.metadata), "executed": executed},
    )


def _tool_call_counts(
    *,
    requested: int,
    tool_results: Sequence[ToolExecutionResult],
) -> ToolCallCounts:
    executed = sum(1 for result in tool_results if result.metadata.get("executed") is True)
    return ToolCallCounts(
        requested=requested,
        executed=executed,
        denied=max(0, requested - executed),
    )


def _schema_error(value: Any, schema: Mapping[str, Any], path: str = "$") -> str | None:
    if not schema:
        return None
    enum_values = schema.get("enum")
    if isinstance(enum_values, Sequence) and not isinstance(enum_values, (str, bytes)):
        if value not in enum_values:
            return f"{path} must be one of {list(enum_values)!r}"

    expected_type = schema.get("type")
    if expected_type is not None and not _matches_json_schema_type(value, expected_type):
        return f"{path} must be {expected_type}"

    if expected_type == "object" or "properties" in schema or "required" in schema:
        if not isinstance(value, Mapping):
            return f"{path} must be object"
        required = schema.get("required") or ()
        if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
            for key in required:
                if str(key) not in value:
                    return f"{path}.{key} is required"
        properties = schema.get("properties") or {}
        if isinstance(properties, Mapping):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    child_error = _schema_error(value[key], child_schema, f"{path}.{key}")
                    if child_error is not None:
                        return child_error
        if schema.get("additionalProperties") is False and isinstance(properties, Mapping):
            allowed = set(str(key) for key in properties)
            extra = sorted(str(key) for key in value if str(key) not in allowed)
            if extra:
                return f"{path} has undeclared properties: {extra}"

    if expected_type == "array":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return f"{path} must be array"
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                child_error = _schema_error(item, item_schema, f"{path}[{index}]")
                if child_error is not None:
                    return child_error
    return None


def _matches_json_schema_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        return any(_matches_json_schema_type(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _joined_content_text(content: Sequence[StandardContentBlock], block_type: str) -> str:
    return "".join(
        str(getattr(block, "text", "") or "")
        for block in content
        if getattr(block, "type", "") == block_type
    )


def _is_cancelled(token: CancellationToken | None) -> bool:
    return token is not None and token.is_cancelled()
