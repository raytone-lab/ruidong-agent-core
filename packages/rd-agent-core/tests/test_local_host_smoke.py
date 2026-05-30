from __future__ import annotations

from collections.abc import AsyncIterable, Iterable
from dataclasses import replace
from typing import Any

from rd_agent_contracts import (
    AgentEvent,
    EventDraft,
    Message,
    MessageId,
    RunBudget,
    RunCompletion,
    RunRecord,
    RunResultMetadata,
    RunScope,
    RunStatus,
    SessionId,
    TextBlock,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolUseBlock,
    ToolUseId,
    TurnId,
    Usage,
)
from rd_agent_core import CoreEventType, CoreEventWriter, RunKernel, RunLimits, RunRequest
from rd_llm_adapter import TurnDone, UsageUpdate
from rd_llm_adapter.events import StandardEvent


class _Ids:
    def __init__(self) -> None:
        self.turns = 0
        self.messages = 0

    def turn_id(self) -> TurnId:
        self.turns += 1
        return TurnId(f"turn-{self.turns}")

    def message_id(self) -> MessageId:
        self.messages += 1
        return MessageId(f"msg-{self.messages}")

    def tool_use_id(self) -> ToolUseId:
        return ToolUseId("tool-fixed")

    def session_id(self) -> SessionId:
        return SessionId("session-fixed")


class _InMemoryEventLog:
    def __init__(self) -> None:
        self.events_by_run: dict[str, list[AgentEvent]] = {}
        self.idempotency: dict[tuple[str, str], AgentEvent] = {}

    def append_event(
        self,
        run_id: str,
        draft: EventDraft,
        *,
        idempotency_key: str | None = None,
    ) -> AgentEvent:
        if idempotency_key is not None:
            cached = self.idempotency.get((run_id, idempotency_key))
            if cached is not None:
                return cached

        events = self.events_by_run.setdefault(run_id, [])
        event = draft.to_event(
            run_id=run_id,
            seq=len(events) + 1,
            timestamp_ms=1_710_000_000_000 + len(events),
        )
        events.append(event)
        if idempotency_key is not None:
            self.idempotency[(run_id, idempotency_key)] = event
        return event

    def stream_events(
        self,
        run_id: str,
        *,
        from_seq: int = 0,
        limit: int | None = None,
    ) -> Iterable[AgentEvent]:
        events = [
            event
            for event in self.events_by_run.get(run_id, [])
            if event.seq > from_seq
        ]
        return events[:limit] if limit is not None else events


class _InMemoryRunPersistence:
    def __init__(self) -> None:
        self.records: dict[str, RunRecord] = {}
        self.next_run = 1

    def create_root_run(
        self,
        *,
        scope: RunScope,
        budget: RunBudget,
        max_continuations: int = 0,
        run_id: str | None = None,
    ) -> RunRecord:
        resolved_run_id = run_id or f"run-{self.next_run}"
        record = RunRecord(
            run_id=resolved_run_id,
            scope=scope,
            status=RunStatus.PENDING,
            run_index=self.next_run,
            continuation_index=0,
            max_continuations=max_continuations,
            budget=budget,
            created_at_ms=1_710_000_000_000,
        )
        self.next_run += 1
        self.records[record.run_id] = record
        return record

    def create_subagent_run(
        self,
        *,
        scope: RunScope,
        budget: RunBudget,
        max_continuations: int = 0,
        run_id: str | None = None,
    ) -> RunRecord:
        return self.create_root_run(
            scope=scope,
            budget=budget,
            max_continuations=max_continuations,
            run_id=run_id,
        )

    def mark_running(
        self,
        run_id: str,
        *,
        started_at_ms: int | None = None,
    ) -> RunRecord | None:
        record = self.records.get(run_id)
        if record is None:
            return None
        updated = replace(
            record,
            status=RunStatus.RUNNING,
            started_at_ms=started_at_ms,
        )
        self.records[run_id] = updated
        return updated

    def mark_completed(
        self,
        run_id: str,
        *,
        completion: RunCompletion,
    ) -> RunRecord | None:
        record = self.records.get(run_id)
        if record is None:
            return None
        updated = replace(
            record,
            status=RunStatus.COMPLETED,
            stop_reason=completion.stop_reason,
            result_metadata=completion.metadata,
            engine_state_json=completion.engine_state_json,
            completed_at_ms=completion.completed_at_ms,
        )
        self.records[run_id] = updated
        return updated

    def load_run(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)


class _LocalHostLLM:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def stream_turn(self, request: Any) -> AsyncIterable[StandardEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            tool = ToolUseBlock(
                id="tool-1",
                name="lookup",
                input={"id": "42"},
            )
            yield UsageUpdate(input_tokens=3, output_tokens=2, total_tokens=5)
            yield TurnDone(
                stop_reason="tool_use",
                content=[tool],
                text_blocks=[],
                reasoning_blocks=[],
                tool_calls=[tool],
                invalid_tool_calls=[],
                raw_stop_reason="tool_calls",
            )
            return

        assert _latest_tool_result(request.messages).content == "lookup:42"
        text = TextBlock("done")
        yield UsageUpdate(input_tokens=1, output_tokens=4, total_tokens=5)
        yield TurnDone(
            stop_reason="end_turn",
            content=[text],
            text_blocks=[text],
            reasoning_blocks=[],
            tool_calls=[],
            invalid_tool_calls=[],
            raw_stop_reason="stop",
        )


class _LocalToolExecutor:
    def __init__(self) -> None:
        self.requests: list[ToolExecutionRequest] = []

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.requests.append(request)
        return ToolExecutionResult(
            ok=True,
            content=f"{request.tool_name}:{request.tool_input['id']}",
        )


def _latest_tool_result(messages: tuple[Message, ...]) -> Any:
    return next(
        result
        for message in reversed(messages)
        for result in message.tool_results
        if message.role == "tool"
    )


async def test_local_host_contract_smoke_persists_kernel_result_and_events() -> None:
    event_log = _InMemoryEventLog()
    persistence = _InMemoryRunPersistence()
    run = persistence.create_root_run(
        run_id="run-local",
        scope=RunScope(
            user_request_id="request-1",
            project_id="project-1",
            session_id="session-1",
        ),
        budget=RunBudget(
            max_turns=3,
            max_tool_calls=2,
            max_wall_clock_s=30,
            total_timeout_s=60,
        ),
    )
    assert persistence.mark_running(run.run_id, started_at_ms=1_710_000_000_001)

    llm = _LocalHostLLM()
    tools = (
        ToolDefinition(
            name="lookup",
            description="Lookup by id",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        ),
    )
    kernel = RunKernel(
        llm_client=llm,
        event_writer=CoreEventWriter(event_log, run_id=run.run_id),
        tool_executor=_LocalToolExecutor(),
        id_generator=_Ids(),
    )

    result = await kernel.run(
        RunRequest(
            run_id=run.run_id,
            messages=(),
            tool_context=ToolExecutionContext(project_id="project-1"),
            tools=tools,
            limits=RunLimits(max_turns=3, max_tool_calls=2, timeout_ms=30_000),
        )
    )
    completed = persistence.mark_completed(
        run.run_id,
        completion=RunCompletion(
            stop_reason=result.stop_reason,
            metadata=RunResultMetadata(
                usage=result.usage,
                turns_count=result.turns_count,
                tool_calls_count=result.tool_calls_count,
                extra={"event_count": len(result.events)},
            ),
            completed_at_ms=1_710_000_000_010,
        ),
    )

    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.stop_reason == "end_turn"
    assert completed.result_metadata.usage == Usage(input_tokens=4, output_tokens=6)
    assert completed.result_metadata.turns_count == 2
    assert completed.result_metadata.tool_calls_count == 1
    assert len(llm.requests) == 2

    emitted = list(event_log.stream_events(run.run_id))
    assert [event.seq for event in emitted] == list(range(1, len(emitted) + 1))
    assert [event.event_type for event in emitted].count(CoreEventType.TURN_COMPLETED) == 2
    assert any(event.event_type == CoreEventType.TOOL_COMPLETED for event in emitted)
