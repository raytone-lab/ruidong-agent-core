"""Reusable test harness for host integrations.

The harness intentionally lives in ``rd_agent_core.testing`` instead of the
main runtime namespace. It gives product hosts a small, deterministic way to
verify their agent wiring without importing private test fixtures.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from rd_agent_contracts import (
    ActionId,
    AgentEvent,
    AgentKind,
    ContinuationJobRecord,
    ContinuationJobSpec,
    ContinuationJobStatus,
    ContinuationQueuePort,
    EventDraft,
    EventLogPort,
    InvalidToolCall,
    Message,
    MessageId,
    RunBudget,
    RunCompletion,
    RunFailure,
    RunId,
    RunPersistencePort,
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
)
from rd_llm_adapter import TextDelta, TurnDone
from rd_llm_adapter.events import StandardEvent

from .conformance import (
    assert_event_log_port_conformance,
    assert_run_persistence_port_conformance,
    assert_tool_executor_port_conformance,
)
from .continuation_runner import (
    ContinuationRunner,
    ContinuationRunnerRequest,
    ContinuationRunnerResult,
)
from .events import CoreEventWriter
from .policies import RunLimits
from .run import RunKernel, RunKernelResult, RunRequest
from .runner import AgentRunner, AgentRunnerRequest, AgentRunnerResult
from .turn import CoreToolPolicy, LLMClientPort, ToolExecutorLike, TurnRequest


class DeterministicIdGenerator:
    """Stable ID generator for harness runs and snapshot-friendly tests."""

    def __init__(self) -> None:
        self._run = 0
        self._turn = 0
        self._message = 0
        self._action = 0
        self._tool = 0
        self._session = 0

    def run_id(self) -> RunId:
        self._run += 1
        return RunId(f"run-{self._run}")

    def turn_id(self) -> TurnId:
        self._turn += 1
        return TurnId(f"turn-{self._turn}")

    def message_id(self) -> MessageId:
        self._message += 1
        return MessageId(f"msg-{self._message}")

    def action_id(self) -> ActionId:
        self._action += 1
        return ActionId(f"act-{self._action}")

    def tool_use_id(self) -> ToolUseId:
        self._tool += 1
        return ToolUseId(f"tool-{self._tool}")

    def session_id(self) -> SessionId:
        self._session += 1
        return SessionId(f"session-{self._session}")


class InMemoryEventLog:
    """Append-only event log with per-run sequences and idempotency."""

    def __init__(self, *, timestamp_ms: int = 1_710_000_000_000) -> None:
        self.timestamp_ms = timestamp_ms
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
            existing = self.idempotency.get((run_id, idempotency_key))
            if existing is not None:
                return existing

        events = self.events_by_run.setdefault(run_id, [])
        event = draft.to_event(
            run_id=run_id,
            seq=len(events) + 1,
            timestamp_ms=self.timestamp_ms + len(events),
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
            for event in self.events_by_run.get(run_id, ())
            if event.seq > from_seq
        ]
        return events[:limit] if limit is not None else events


class InMemoryRunPersistence:
    """In-memory ``RunPersistencePort`` implementation for contract tests."""

    def __init__(self, *, timestamp_ms: int = 1_710_000_000_000) -> None:
        self.timestamp_ms = timestamp_ms
        self.records: dict[str, RunRecord] = {}
        self._next_index = 1

    def create_root_run(
        self,
        *,
        scope: RunScope,
        budget: RunBudget,
        max_continuations: int = 0,
        run_id: str | None = None,
    ) -> RunRecord:
        return self._create_run(
            scope=scope,
            budget=budget,
            max_continuations=max_continuations,
            continuation_index=0,
            engine_state_json=None,
            run_id=run_id,
        )

    def create_subagent_run(
        self,
        *,
        scope: RunScope,
        budget: RunBudget,
        max_continuations: int = 0,
        run_id: str | None = None,
    ) -> RunRecord:
        return self._create_run(
            scope=scope,
            budget=budget,
            max_continuations=max_continuations,
            continuation_index=0,
            engine_state_json=None,
            run_id=run_id,
        )

    def create_continuation_run(
        self,
        *,
        previous_run_id: str,
        engine_state_json: str,
        run_id: str | None = None,
    ) -> RunRecord | None:
        previous = self.records.get(previous_run_id)
        if previous is None:
            return None
        next_continuation = previous.continuation_index + 1
        if next_continuation > previous.max_continuations:
            return None

        return self._create_run(
            scope=replace(previous.scope, parent_run_id=previous.run_id),
            budget=previous.budget,
            max_continuations=previous.max_continuations,
            continuation_index=next_continuation,
            engine_state_json=engine_state_json,
            run_id=run_id,
        )

    def mark_running(
        self,
        run_id: str,
        *,
        started_at_ms: int | None = None,
    ) -> RunRecord | None:
        return self._update(
            run_id,
            status=RunStatus.RUNNING,
            started_at_ms=started_at_ms,
        )

    def mark_completed(
        self,
        run_id: str,
        *,
        completion: RunCompletion,
    ) -> RunRecord | None:
        return self._update(
            run_id,
            status=completion.status,
            stop_reason=completion.stop_reason,
            result_metadata=completion.metadata,
            engine_state_json=completion.engine_state_json,
            completed_at_ms=completion.completed_at_ms,
        )

    def mark_failed(
        self,
        run_id: str,
        *,
        failure: RunFailure,
    ) -> RunRecord | None:
        return self._update(
            run_id,
            status=RunStatus.FAILED,
            error_message=failure.error_message,
            completed_at_ms=failure.completed_at_ms,
        )

    def mark_resumed(self, run_id: str) -> RunRecord | None:
        return self._update(run_id, status=RunStatus.RESUMED)

    def claim_latest_waiting_orchestrator_run(
        self,
        *,
        project_id: str,
    ) -> RunRecord | None:
        candidates = [
            record
            for record in self.records.values()
            if record.scope.project_id == project_id
            and record.scope.agent_kind == AgentKind.ORCHESTRATOR
            and record.status == RunStatus.WAITING_USER
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda record: record.created_at_ms or 0)
        return self._update(latest.run_id, status=RunStatus.RESUMING)

    def load_run(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    def load_run_with_parent(
        self,
        run_id: str,
    ) -> tuple[RunRecord, RunRecord | None] | None:
        record = self.records.get(run_id)
        if record is None:
            return None
        parent = (
            self.records.get(record.scope.parent_run_id)
            if record.scope.parent_run_id
            else None
        )
        return record, parent

    def _create_run(
        self,
        *,
        scope: RunScope,
        budget: RunBudget | None,
        max_continuations: int,
        continuation_index: int,
        engine_state_json: str | None,
        run_id: str | None,
    ) -> RunRecord:
        resolved_run_id = run_id
        while resolved_run_id is None:
            candidate = f"run-{self._next_index}"
            if candidate not in self.records:
                resolved_run_id = candidate
            else:
                self._next_index += 1
        if resolved_run_id in self.records:
            raise ValueError(f"run_id already exists: {resolved_run_id}")
        record = RunRecord(
            run_id=resolved_run_id,
            scope=scope,
            status=RunStatus.PENDING,
            run_index=self._next_index,
            continuation_index=continuation_index,
            max_continuations=max_continuations,
            budget=budget,
            engine_state_json=engine_state_json,
            created_at_ms=self.timestamp_ms + self._next_index,
        )
        self._next_index += 1
        self.records[record.run_id] = record
        return record

    def _update(self, run_id: str, **changes: Any) -> RunRecord | None:
        record = self.records.get(run_id)
        if record is None:
            return None
        updated = replace(record, **changes)
        self.records[run_id] = updated
        return updated


class InMemoryContinuationQueue:
    """In-memory ``ContinuationQueuePort`` for worker and host harness tests."""

    def __init__(self, *, timestamp_ms: int = 1_710_000_000_000) -> None:
        self.timestamp_ms = timestamp_ms
        self.records: dict[str, ContinuationJobRecord] = {}
        self._next_id = 1

    def enqueue_for_run(
        self,
        spec: ContinuationJobSpec,
        *,
        job_id: str | None = None,
    ) -> ContinuationJobRecord:
        for job in self.records.values():
            if job.next_run_id == spec.next_run_id:
                return job

        timestamp_ms = spec.available_at_ms or self._now()
        record = ContinuationJobRecord(
            job_id=job_id or self._new_id(),
            user_request_id=spec.user_request_id,
            project_id=spec.project_id,
            previous_run_id=spec.previous_run_id,
            next_run_id=spec.next_run_id,
            status=ContinuationJobStatus.QUEUED,
            attempts=0,
            max_attempts=spec.max_attempts,
            correlation_id=spec.correlation_id,
            available_at_ms=timestamp_ms,
            created_at_ms=timestamp_ms,
            updated_at_ms=timestamp_ms,
        )
        self.records[record.job_id] = record
        return record

    def claim_next(
        self,
        *,
        worker_id: str,
        available_at_ms: int | None = None,
    ) -> ContinuationJobRecord | None:
        timestamp_ms = available_at_ms or self._now()
        queued = [
            job
            for job in self.records.values()
            if job.status == ContinuationJobStatus.QUEUED
            and (job.available_at_ms or 0) <= timestamp_ms
        ]
        if not queued:
            return None
        job = sorted(queued, key=lambda item: item.created_at_ms or 0)[0]
        return self._update(
            job.job_id,
            status=ContinuationJobStatus.RUNNING,
            worker_id=worker_id,
            locked_at_ms=timestamp_ms,
            heartbeat_at_ms=timestamp_ms,
            updated_at_ms=timestamp_ms,
        )

    def mark_attempt_started(
        self,
        job_id: str,
        *,
        heartbeat_at_ms: int | None = None,
    ) -> ContinuationJobRecord | None:
        job = self.records.get(job_id)
        if job is None or job.status != ContinuationJobStatus.RUNNING:
            return None
        timestamp_ms = heartbeat_at_ms or self._now()
        return self._update(
            job_id,
            attempts=job.attempts + 1,
            heartbeat_at_ms=timestamp_ms,
            updated_at_ms=timestamp_ms,
        )

    def heartbeat(
        self,
        job_id: str,
        *,
        heartbeat_at_ms: int | None = None,
    ) -> ContinuationJobRecord | None:
        if job_id not in self.records:
            return None
        timestamp_ms = heartbeat_at_ms or self._now()
        return self._update(
            job_id,
            heartbeat_at_ms=timestamp_ms,
            updated_at_ms=timestamp_ms,
        )

    def complete_success(
        self,
        job_id: str,
        *,
        completed_at_ms: int | None = None,
    ) -> ContinuationJobRecord | None:
        if job_id not in self.records:
            return None
        timestamp_ms = completed_at_ms or self._now()
        return self._update(
            job_id,
            status=ContinuationJobStatus.SUCCEEDED,
            completed_at_ms=timestamp_ms,
            updated_at_ms=timestamp_ms,
        )

    def complete_failure(
        self,
        job_id: str,
        *,
        error: str,
        retry_available_at_ms: int | None = None,
        completed_at_ms: int | None = None,
    ) -> ContinuationJobRecord | None:
        job = self.records.get(job_id)
        if job is None:
            return None
        timestamp_ms = completed_at_ms or self._now()
        if job.attempts >= job.max_attempts:
            return self._update(
                job_id,
                status=ContinuationJobStatus.DEAD_LETTER,
                last_error=error,
                completed_at_ms=timestamp_ms,
                updated_at_ms=timestamp_ms,
            )
        return self.release_for_retry(
            job_id,
            error=error,
            available_at_ms=retry_available_at_ms or timestamp_ms,
        )

    def release_for_retry(
        self,
        job_id: str,
        *,
        error: str,
        available_at_ms: int | None = None,
    ) -> ContinuationJobRecord | None:
        if job_id not in self.records:
            return None
        timestamp_ms = self._now()
        return self._update(
            job_id,
            status=ContinuationJobStatus.QUEUED,
            worker_id=None,
            locked_at_ms=None,
            heartbeat_at_ms=None,
            last_error=error,
            available_at_ms=available_at_ms or timestamp_ms,
            updated_at_ms=timestamp_ms,
        )

    def reclaim_stale(self, *, stale_before_ms: int) -> int:
        reclaimed = 0
        for job in tuple(self.records.values()):
            if job.status != ContinuationJobStatus.RUNNING:
                continue
            if job.heartbeat_at_ms is not None and job.heartbeat_at_ms >= stale_before_ms:
                continue
            self.release_for_retry(
                job.job_id,
                error=job.last_error or "stale",
                available_at_ms=self._now(),
            )
            reclaimed += 1
        return reclaimed

    def load_job(self, job_id: str) -> ContinuationJobRecord | None:
        return self.records.get(job_id)

    def _new_id(self) -> str:
        job_id = f"job-{self._next_id}"
        self._next_id += 1
        return job_id

    def _now(self) -> int:
        self.timestamp_ms += 1
        return self.timestamp_ms

    def _update(self, job_id: str, **changes: Any) -> ContinuationJobRecord:
        old = self.records[job_id]
        updated = replace(old, **changes)
        self.records[job_id] = updated
        return updated


ScriptedTurn = (
    Sequence[StandardEvent]
    | Callable[[TurnRequest], Iterable[StandardEvent] | AsyncIterable[StandardEvent]]
)


class ScriptedLLMClient:
    """LLM client that emits deterministic per-turn event scripts."""

    def __init__(self, turns: Sequence[ScriptedTurn]) -> None:
        self.turns = tuple(turns)
        self.requests: list[TurnRequest] = []

    async def stream_turn(self, request: TurnRequest) -> AsyncIterable[StandardEvent]:
        turn_index = len(self.requests)
        self.requests.append(request)
        if turn_index >= len(self.turns):
            raise RuntimeError(f"no scripted LLM turn at index {turn_index}")

        events = self.turns[turn_index]
        stream = events(request) if callable(events) else events
        if hasattr(stream, "__aiter__"):
            async for event in stream:  # type: ignore[union-attr]
                yield event
            return
        for event in stream:
            yield event


ToolHandlerResult = ToolExecutionResult | str | Mapping[str, Any]
ToolHandler = Callable[
    [ToolExecutionRequest],
    ToolHandlerResult | Awaitable[ToolHandlerResult],
]


class FunctionToolExecutor:
    """Tool executor backed by simple Python callables."""

    def __init__(self, handlers: Mapping[str, ToolHandler]) -> None:
        self.handlers = dict(handlers)
        self.requests: list[ToolExecutionRequest] = []

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.requests.append(request)
        handler = self.handlers.get(request.tool_name)
        if handler is None:
            return ToolExecutionResult(
                ok=False,
                content="",
                tool_use_id=request.tool_use_id or "",
                error={
                    "type": "tool_handler_missing",
                    "message": f"No handler registered for tool: {request.tool_name}",
                },
                metadata={"executed": False},
            )

        raw = handler(request)
        value = await raw if inspect.isawaitable(raw) else raw
        if isinstance(value, ToolExecutionResult):
            return ToolExecutionResult(
                ok=value.ok,
                content=value.content,
                tool_use_id=value.tool_use_id or request.tool_use_id or "",
                error=value.error,
                duration_ms=value.duration_ms,
                metadata={**dict(value.metadata), "executed": True},
            )
        if isinstance(value, str):
            return ToolExecutionResult(
                ok=True,
                content=value,
                tool_use_id=request.tool_use_id or "",
                metadata={"executed": True},
            )
        return ToolExecutionResult(
            ok=True,
            content=json.dumps(value, ensure_ascii=False, sort_keys=True),
            tool_use_id=request.tool_use_id or "",
            metadata={"executed": True},
        )


class ManualCancellationToken:
    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def request_cancel(self) -> None:
        self._cancelled = True


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: tuple[ScriptedTurn, ...]
    messages: tuple[Message, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()
    tool_handlers: Mapping[str, ToolHandler] = field(default_factory=dict)
    tool_policy: CoreToolPolicy = field(default_factory=CoreToolPolicy)
    limits: RunLimits = field(default_factory=lambda: RunLimits(max_turns=4, max_tool_calls=8))
    budget: RunBudget = field(
        default_factory=lambda: RunBudget(
            max_turns=4,
            max_tool_calls=8,
            max_wall_clock_s=30,
            total_timeout_s=60,
        )
    )
    cancellation_token: ManualCancellationToken | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def text_only(*, final_text: str = "done") -> Scenario:
        text = TextBlock(final_text)
        return Scenario(
            name="text-only",
            turns=(
                (
                    TextDelta(final_text),
                    TurnDone(
                        stop_reason="end_turn",
                        content=[text],
                        text_blocks=[text],
                        reasoning_blocks=[],
                        tool_calls=[],
                        invalid_tool_calls=[],
                        raw_stop_reason="stop",
                    ),
                ),
            ),
        )

    @staticmethod
    def single_tool(
        *,
        tool_name: str = "lookup",
        tool_input: Mapping[str, Any] | None = None,
        tool_output: str = "lookup:42",
        final_text: str = "done: lookup:42",
    ) -> Scenario:
        resolved_input = dict(tool_input or {"id": "42"})
        tool = ToolUseBlock(id="tool-1", name=tool_name, input=resolved_input)
        text = TextBlock(final_text)

        def _handler(_request: ToolExecutionRequest) -> str:
            return tool_output

        return Scenario(
            name="single-tool",
            turns=(
                (
                    TurnDone(
                        stop_reason="tool_use",
                        content=[tool],
                        text_blocks=[],
                        reasoning_blocks=[],
                        tool_calls=[tool],
                        invalid_tool_calls=[],
                        raw_stop_reason="tool_calls",
                    ),
                ),
                (
                    TurnDone(
                        stop_reason="end_turn",
                        content=[text],
                        text_blocks=[text],
                        reasoning_blocks=[],
                        tool_calls=[],
                        invalid_tool_calls=[],
                        raw_stop_reason="stop",
                    ),
                ),
            ),
            tools=(
                ToolDefinition(
                    name=tool_name,
                    description=f"Scenario tool {tool_name}",
                    input_schema={"type": "object"},
                ),
            ),
            tool_handlers={tool_name: _handler},
        )

    @staticmethod
    def multi_turn_tool_loop(*, tool_name: str = "lookup", count: int = 2) -> Scenario:
        turns: list[ScriptedTurn] = []
        for index in range(1, count + 1):
            tool = ToolUseBlock(
                id=f"tool-{index}",
                name=tool_name,
                input={"id": str(index)},
            )
            turns.append(
                (
                    TurnDone(
                        stop_reason="tool_use",
                        content=[tool],
                        text_blocks=[],
                        reasoning_blocks=[],
                        tool_calls=[tool],
                        invalid_tool_calls=[],
                        raw_stop_reason="tool_calls",
                    ),
                )
            )
        final_text = TextBlock("done")
        turns.append(
            (
                TurnDone(
                    stop_reason="end_turn",
                    content=[final_text],
                    text_blocks=[final_text],
                    reasoning_blocks=[],
                    tool_calls=[],
                    invalid_tool_calls=[],
                    raw_stop_reason="stop",
                ),
            )
        )
        return Scenario(
            name="multi-turn",
            turns=tuple(turns),
            tools=(
                ToolDefinition(
                    name=tool_name,
                    description=f"Scenario tool {tool_name}",
                    input_schema={"type": "object"},
                ),
            ),
            tool_handlers={tool_name: lambda request: f"{tool_name}:{request.tool_input['id']}"},
            limits=RunLimits(max_turns=count + 1, max_tool_calls=count + 1),
            budget=RunBudget(
                max_turns=count + 1,
                max_tool_calls=count + 1,
                max_wall_clock_s=30,
                total_timeout_s=60,
            ),
        )

    @staticmethod
    def invalid_tool() -> Scenario:
        invalid = InvalidToolCall(
            id="tool-invalid",
            name="lookup",
            raw_args="{",
            parse_error="invalid json",
            index=0,
        )
        return Scenario(
            name="invalid-tool",
            turns=(
                (
                    TurnDone(
                        stop_reason="end_turn",
                        content=[invalid],
                        text_blocks=[],
                        reasoning_blocks=[],
                        tool_calls=[],
                        invalid_tool_calls=[invalid],
                        raw_stop_reason="stop",
                    ),
                ),
            ),
            tools=(
                ToolDefinition(
                    name="lookup",
                    description="Lookup",
                    input_schema={"type": "object"},
                ),
            ),
            tool_handlers={"lookup": lambda _request: "should-not-run"},
        )

    @staticmethod
    def pause(*, tool_name: str = "ask_user") -> Scenario:
        tool = ToolUseBlock(id="tool-pause", name=tool_name, input={"question": "Continue?"})
        return Scenario(
            name="pause-tool",
            turns=(
                (
                    TurnDone(
                        stop_reason="tool_use",
                        content=[tool],
                        text_blocks=[],
                        reasoning_blocks=[],
                        tool_calls=[tool],
                        invalid_tool_calls=[],
                        raw_stop_reason="tool_calls",
                    ),
                ),
            ),
            tools=(
                ToolDefinition(
                    name=tool_name,
                    description="Pause for user input",
                    input_schema={"type": "object"},
                ),
            ),
            tool_handlers={tool_name: lambda _request: "waiting"},
            tool_policy=CoreToolPolicy(
                pause_tool_names=frozenset({tool_name}),
                pause_stop_reason="ask_user",
            ),
        )

    @staticmethod
    def cancellation_before_start() -> Scenario:
        return Scenario(
            name="cancellation",
            turns=Scenario.text_only().turns,
            cancellation_token=ManualCancellationToken(cancelled=True),
        )

    @staticmethod
    def provider_partial_error(*, partial_text: str = "partial") -> Scenario:
        text = TextBlock(partial_text)
        return Scenario(
            name="provider-partial-error",
            turns=(
                (
                    TextDelta(partial_text),
                    TurnDone(
                        stop_reason="error",
                        content=[text],
                        text_blocks=[text],
                        reasoning_blocks=[],
                        tool_calls=[],
                        invalid_tool_calls=[],
                        raw_stop_reason="error",
                    ),
                ),
            ),
        )


@dataclass(frozen=True)
class ScenarioRunResult:
    run: RunRecord
    completed: RunRecord
    kernel_result: RunKernelResult
    events: tuple[AgentEvent, ...]
    runner_result: AgentRunnerResult | None = None

    def assert_run_status(self, expected: str) -> ScenarioRunResult:
        if self.completed.status != expected:
            raise AssertionError(
                f"expected run status {expected!r}, got {self.completed.status!r}"
            )
        return self

    def assert_stop_reason(self, expected: str) -> ScenarioRunResult:
        if self.kernel_result.stop_reason != expected:
            raise AssertionError(
                f"expected stop reason {expected!r}, got {self.kernel_result.stop_reason!r}"
            )
        return self

    def assert_event_sequence(self, expected: Sequence[str]) -> ScenarioRunResult:
        actual = [str(event.event_type) for event in self.events]
        if actual != [str(item) for item in expected]:
            raise AssertionError(f"expected events {list(expected)!r}, got {actual!r}")
        return self


class KernelHarness:
    def __init__(
        self,
        *,
        event_log: InMemoryEventLog | None = None,
        persistence: InMemoryRunPersistence | None = None,
        id_generator: DeterministicIdGenerator | None = None,
        timestamp_ms: int = 1_710_000_000_000,
    ) -> None:
        self.event_log = event_log or InMemoryEventLog(timestamp_ms=timestamp_ms)
        self.persistence = persistence or InMemoryRunPersistence(timestamp_ms=timestamp_ms)
        self.id_generator = id_generator or DeterministicIdGenerator()
        self.timestamp_ms = timestamp_ms

    async def run(self, scenario: Scenario, *, run_id: str | None = None) -> ScenarioRunResult:
        resolved_run_id = run_id or str(self.id_generator.run_id())
        run = self.persistence.create_root_run(
            scope=_default_scope(),
            budget=scenario.budget,
            run_id=resolved_run_id,
        )
        self.persistence.mark_running(run.run_id, started_at_ms=self.timestamp_ms + 1)
        kernel = RunKernel(
            llm_client=ScriptedLLMClient(scenario.turns),
            event_writer=CoreEventWriter(self.event_log, run_id=run.run_id),
            tool_executor=FunctionToolExecutor(scenario.tool_handlers)
            if scenario.tool_handlers
            else None,
            tool_policy=scenario.tool_policy,
            id_generator=self.id_generator,
        )
        kernel_result = await kernel.run(
            RunRequest(
                run_id=run.run_id,
                messages=scenario.messages,
                tool_context=_default_tool_context(run.run_id),
                tools=scenario.tools,
                limits=scenario.limits,
                metadata=dict(scenario.metadata),
                cancellation_token=scenario.cancellation_token,
            )
        )
        completed = self.persistence.mark_completed(
            run.run_id,
            completion=RunCompletion(
                stop_reason=kernel_result.stop_reason,
                status=_status_for_scenario_stop(kernel_result.stop_reason),
                metadata=RunResultMetadata(
                    usage=kernel_result.usage,
                    turns_count=kernel_result.turns_count,
                    tool_call_counts=kernel_result.tool_call_counts,
                    extra={"event_count": len(kernel_result.events)},
                ),
                completed_at_ms=self.timestamp_ms + 2,
            ),
        )
        if completed is None:
            raise RuntimeError(f"scenario run disappeared: {run.run_id}")
        return ScenarioRunResult(
            run=run,
            completed=completed,
            kernel_result=kernel_result,
            events=tuple(self.event_log.stream_events(run.run_id)),
        )


class RunnerHarness:
    def __init__(
        self,
        *,
        persistence: RunPersistencePort | None = None,
        event_log: EventLogPort | None = None,
        id_generator: DeterministicIdGenerator | None = None,
    ) -> None:
        self.persistence = persistence or InMemoryRunPersistence()
        self.event_log = event_log or InMemoryEventLog()
        self.id_generator = id_generator or DeterministicIdGenerator()

    @classmethod
    def from_ports(
        cls,
        *,
        persistence: RunPersistencePort,
        event_log: EventLogPort,
        id_generator: DeterministicIdGenerator | None = None,
    ) -> RunnerHarness:
        return cls(
            persistence=persistence,
            event_log=event_log,
            id_generator=id_generator,
        )

    async def run(self, scenario: Scenario, *, run_id: str | None = None) -> ScenarioRunResult:
        resolved_run_id = run_id or str(self.id_generator.run_id())
        runner = AgentRunner(
            run_persistence=self.persistence,
            event_log=self.event_log,
            llm_client=ScriptedLLMClient(scenario.turns),
            tool_executor=FunctionToolExecutor(scenario.tool_handlers)
            if scenario.tool_handlers
            else None,
            tool_policy=scenario.tool_policy,
            id_generator=self.id_generator,
        )
        runner_result = await runner.run(
            AgentRunnerRequest(
                run_id=resolved_run_id,
                scope=_default_scope(),
                budget=scenario.budget,
                messages=scenario.messages,
                tools=scenario.tools,
                tool_context=_default_tool_context(resolved_run_id),
                limits=scenario.limits,
                metadata=scenario.metadata,
                cancellation_token=scenario.cancellation_token,
            )
        )
        return ScenarioRunResult(
            run=runner_result.run,
            completed=runner_result.completed,
            kernel_result=runner_result.kernel_result,
            events=runner_result.events,
            runner_result=runner_result,
        )


class HostHarness:
    def __init__(
        self,
        *,
        persistence: RunPersistencePort,
        event_log: EventLogPort,
        continuation_queue: ContinuationQueuePort | None = None,
        id_generator: DeterministicIdGenerator | None = None,
    ) -> None:
        self.persistence = persistence
        self.event_log = event_log
        self.continuation_queue = continuation_queue
        self.id_generator = id_generator or DeterministicIdGenerator()

    async def assert_port_conformance(self) -> None:
        assert_event_log_port_conformance(self.event_log)
        assert_run_persistence_port_conformance(self.persistence)
        executor = FunctionToolExecutor({"conformance_echo": lambda _request: "ok"})
        await assert_tool_executor_port_conformance(executor)

    async def certify(
        self,
        scenarios: Sequence[Scenario] | None = None,
    ) -> tuple[ScenarioRunResult, ...]:
        selected = tuple(scenarios or certification_scenarios())
        harness = RunnerHarness.from_ports(
            persistence=self.persistence,
            event_log=self.event_log,
            id_generator=self.id_generator,
        )
        results = []
        for index, scenario in enumerate(selected, start=1):
            results.append(await harness.run(scenario, run_id=f"cert-{index}-{scenario.name}"))
        return tuple(results)

    async def certify_continuation(
        self,
        *,
        continuation_queue: ContinuationQueuePort | None = None,
    ) -> ContinuationRunnerResult:
        queue = continuation_queue or self.continuation_queue or InMemoryContinuationQueue()
        tool = ToolDefinition(
            name="lookup",
            description="Continuation certification lookup",
            input_schema={"type": "object"},
        )
        runner = AgentRunner(
            run_persistence=self.persistence,
            event_log=self.event_log,
            llm_client=ScriptedLLMClient([_continuation_tool_turn]),
            tool_executor=FunctionToolExecutor({"lookup": _continuation_lookup}),
            id_generator=self.id_generator,
        )
        root = await runner.run(
            AgentRunnerRequest(
                run_id="cert-continuation-root",
                scope=_default_scope(),
                budget=RunBudget(
                    max_turns=1,
                    max_tool_calls=2,
                    max_wall_clock_s=30,
                    total_timeout_s=60,
                ),
                max_continuations=1,
                tools=(tool,),
            )
        )
        queue.enqueue_for_run(
            ContinuationJobSpec(
                user_request_id=root.completed.scope.user_request_id,
                project_id=root.completed.scope.project_id,
                previous_run_id=root.completed.run_id,
                next_run_id="cert-continuation-1",
                max_attempts=1,
                correlation_id=root.completed.scope.correlation_id,
            ),
            job_id="cert-continuation-job",
        )
        continuation_runner = ContinuationRunner(
            continuation_queue=queue,
            run_persistence=self.persistence,
            event_log=self.event_log,
            llm_client=ScriptedLLMClient([_continuation_final_turn]),
            id_generator=self.id_generator,
        )
        result = await continuation_runner.run_next(
            ContinuationRunnerRequest(
                worker_id="cert-continuation-worker",
                tools=(tool,),
            )
        )
        if result is None:
            raise AssertionError("continuation certification job was not claimed")
        return result


def certification_scenarios() -> tuple[Scenario, ...]:
    return (
        Scenario.text_only(),
        Scenario.single_tool(),
        Scenario.multi_turn_tool_loop(),
        Scenario.invalid_tool(),
        Scenario.pause(),
        Scenario.cancellation_before_start(),
        Scenario.provider_partial_error(),
    )


def _continuation_tool_turn(_request: TurnRequest) -> list[StandardEvent]:
    tool = ToolUseBlock(id="tool-continuation", name="lookup", input={"id": "42"})
    return [
        TurnDone(
            stop_reason="tool_use",
            content=[tool],
            text_blocks=[],
            reasoning_blocks=[],
            tool_calls=[tool],
            invalid_tool_calls=[],
            raw_stop_reason="tool_calls",
        )
    ]


def _continuation_lookup(request: ToolExecutionRequest) -> str:
    return f"lookup:{request.tool_input['id']}"


def _continuation_final_turn(request: TurnRequest) -> list[StandardEvent]:
    latest_result = next(
        result
        for message in reversed(request.messages)
        for result in message.tool_results
        if message.role == "tool"
    )
    text = TextBlock(f"continued: {latest_result.content}")
    return [
        TurnDone(
            stop_reason="end_turn",
            content=[text],
            text_blocks=[text],
            reasoning_blocks=[],
            tool_calls=[],
            invalid_tool_calls=[],
            raw_stop_reason="stop",
        )
    ]


def _default_scope() -> RunScope:
    return RunScope(
        user_request_id="request-harness",
        project_id="project-harness",
        session_id="session-harness",
    )


def _default_tool_context(run_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        project_id="project-harness",
        session_id="session-harness",
        user_request_id="request-harness",
        agent_run_id=run_id,
    )


def _status_for_scenario_stop(stop_reason: str) -> str:
    if stop_reason == "ask_user":
        return RunStatus.WAITING_USER.value
    if stop_reason == "cancelled":
        return RunStatus.CANCELLED.value
    if stop_reason in {"max_turns", "max_wall_clock", "repeated_tool_call", "error"}:
        return RunStatus.NEEDS_ATTENTION.value
    return RunStatus.COMPLETED.value


@dataclass(frozen=True)
class HarnessRunResult:
    run: RunRecord
    completed: RunRecord
    kernel_result: RunKernelResult
    events: tuple[AgentEvent, ...]


class AgentCoreHarness:
    """End-to-end local host harness for ``RunKernel`` contract tests."""

    def __init__(
        self,
        *,
        llm_client: LLMClientPort,
        tool_executor: ToolExecutorLike | None = None,
        event_log: InMemoryEventLog | None = None,
        persistence: InMemoryRunPersistence | None = None,
        id_generator: DeterministicIdGenerator | None = None,
        timestamp_ms: int = 1_710_000_000_000,
    ) -> None:
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.event_log = event_log or InMemoryEventLog(timestamp_ms=timestamp_ms)
        self.persistence = persistence or InMemoryRunPersistence(
            timestamp_ms=timestamp_ms
        )
        self.id_generator = id_generator or DeterministicIdGenerator()
        self.timestamp_ms = timestamp_ms

    async def run(
        self,
        *,
        run_id: str | None = None,
        messages: Sequence[Message] = (),
        tools: Sequence[ToolDefinition] = (),
        tool_context: ToolExecutionContext | None = None,
        scope: RunScope | None = None,
        budget: RunBudget | None = None,
        limits: RunLimits | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        max_continuations: int = 0,
    ) -> HarnessRunResult:
        resolved_scope = scope or RunScope(
            user_request_id="request-harness",
            project_id="project-harness",
            session_id="session-harness",
        )
        resolved_budget = budget or RunBudget(
            max_turns=3,
            max_tool_calls=3,
            max_wall_clock_s=30,
            total_timeout_s=60,
        )
        resolved_limits = limits or RunLimits(
            max_turns=resolved_budget.max_turns,
            max_tool_calls=resolved_budget.max_tool_calls,
            timeout_ms=resolved_budget.max_wall_clock_s * 1000,
        )
        resolved_context = tool_context or ToolExecutionContext(
            project_id=resolved_scope.project_id,
            metadata={"session_id": resolved_scope.session_id},
        )

        resolved_run_id = run_id or str(self.id_generator.run_id())
        run = self.persistence.create_root_run(
            scope=resolved_scope,
            budget=resolved_budget,
            max_continuations=max_continuations,
            run_id=resolved_run_id,
        )
        self.persistence.mark_running(run.run_id, started_at_ms=self.timestamp_ms + 1)

        kernel = RunKernel(
            llm_client=self.llm_client,
            event_writer=CoreEventWriter(self.event_log, run_id=run.run_id),
            tool_executor=self.tool_executor,
            id_generator=self.id_generator,
        )
        kernel_result = await kernel.run(
            RunRequest(
                run_id=run.run_id,
                messages=tuple(messages),
                tool_context=resolved_context,
                tools=tuple(tools),
                model=model,
                system_prompt=system_prompt,
                limits=resolved_limits,
                metadata=dict(metadata or {}),
            )
        )
        completed = self.persistence.mark_completed(
            run.run_id,
            completion=RunCompletion(
                stop_reason=kernel_result.stop_reason,
                    metadata=RunResultMetadata(
                        usage=kernel_result.usage,
                        turns_count=kernel_result.turns_count,
                        tool_call_counts=kernel_result.tool_call_counts,
                        extra={"event_count": len(kernel_result.events)},
                    ),
                completed_at_ms=self.timestamp_ms + 2,
            ),
        )
        if completed is None:
            raise RuntimeError(f"harness run disappeared: {run.run_id}")

        return HarnessRunResult(
            run=run,
            completed=completed,
            kernel_result=kernel_result,
            events=tuple(self.event_log.stream_events(run.run_id)),
        )
