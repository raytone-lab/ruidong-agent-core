from __future__ import annotations

import pytest
from rd_agent_contracts import (
    ContinuationJobSpec,
    ContinuationJobStatus,
    Message,
    RunBudget,
    RunCompletion,
    RunScope,
    RunStatus,
    TextBlock,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolExecutionRequest,
    ToolResult,
    ToolUseBlock,
)
from rd_agent_core import (
    AgentRunner,
    AgentRunnerRequest,
    ContinuationRunner,
    ContinuationRunnerRequest,
    ContinuationState,
)
from rd_agent_core.testing import (
    DeterministicIdGenerator,
    FunctionToolExecutor,
    InMemoryContinuationQueue,
    InMemoryEventLog,
    InMemoryRunPersistence,
    ScriptedLLMClient,
)
from rd_llm_adapter import TurnDone


class _RunObserver:
    def __init__(self) -> None:
        self.summaries = []

    def record_run_summary(self, summary) -> None:
        self.summaries.append(summary)


class _MarkRunningFailsPersistence(InMemoryRunPersistence):
    def mark_running(self, run_id: str, *, started_at_ms: int | None = None):
        if run_id == "run-cont-running-fails":
            return None
        return super().mark_running(run_id, started_at_ms=started_at_ms)


def _tool() -> ToolDefinition:
    return ToolDefinition(
        name="lookup",
        description="Lookup by id",
        input_schema={"type": "object"},
    )


def _tool_turn(_request) -> list:
    tool = ToolUseBlock(id="tool-1", name="lookup", input={"id": "42"})
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


def _final_turn(request) -> list:
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


def _lookup(request: ToolExecutionRequest) -> str:
    return f"lookup:{request.tool_input['id']}"


async def _create_continuable_root(
    *,
    persistence: InMemoryRunPersistence,
    event_log: InMemoryEventLog,
):
    runner = AgentRunner(
        run_persistence=persistence,
        event_log=event_log,
        llm_client=ScriptedLLMClient([_tool_turn]),
        tool_executor=FunctionToolExecutor({"lookup": _lookup}),
        id_generator=DeterministicIdGenerator(),
    )
    return await runner.run(
        AgentRunnerRequest(
            run_id="run-root",
            scope=RunScope(
                user_request_id="request-1",
                project_id="project-1",
                session_id="session-1",
                correlation_id="corr-1",
            ),
            budget=RunBudget(
                max_turns=1,
                max_tool_calls=2,
                max_wall_clock_s=30,
                total_timeout_s=60,
            ),
            max_continuations=1,
            tools=(_tool(),),
        )
    )


def test_continuation_state_round_trips_messages() -> None:
    state = ContinuationState(
        messages=(
            Message(
                message_id="msg-1",
                role="assistant",
                content=[{"type": "tool_use", "id": "tool-1"}],
                turn_id="turn-1",
                tool_calls=[
                    ToolCall(
                        tool_use_id="tool-1",
                        tool_name="lookup",
                        input={"id": "42"},
                        status=ToolCallStatus.COMPLETE,
                    )
                ],
            ),
            Message(
                message_id="msg-2",
                role="tool",
                content="lookup:42",
                turn_id="turn-1",
                tool_results=[
                    ToolResult(
                        tool_use_id="tool-1",
                        ok=True,
                        content="lookup:42",
                    )
                ],
            ),
        ),
        turn_offset=1,
    )

    assert ContinuationState.from_json(state.to_json()) == state


async def test_continuation_runner_resumes_state_and_completes_job() -> None:
    persistence = InMemoryRunPersistence()
    event_log = InMemoryEventLog()
    root = await _create_continuable_root(
        persistence=persistence,
        event_log=event_log,
    )
    queue = InMemoryContinuationQueue()
    queue.enqueue_for_run(
        ContinuationJobSpec(
            user_request_id="request-1",
            project_id="project-1",
            previous_run_id=root.completed.run_id,
            next_run_id="run-cont-1",
            max_attempts=1,
            correlation_id="corr-1",
        ),
        job_id="job-1",
    )
    observer = _RunObserver()
    llm = ScriptedLLMClient([_final_turn])
    runner = ContinuationRunner(
        continuation_queue=queue,
        run_persistence=persistence,
        event_log=event_log,
        llm_client=llm,
        run_observer=observer,
        id_generator=DeterministicIdGenerator(),
    )

    result = await runner.run_next(
        ContinuationRunnerRequest(
            worker_id="worker-1",
            tools=(_tool(),),
            heartbeat_at_ms=123,
        )
    )

    assert result is not None
    assert root.completed.status == RunStatus.CONTINUABLE
    assert result.completed_run.status == RunStatus.COMPLETED
    assert result.completed_run.scope.parent_run_id == root.completed.run_id
    assert result.completed_run.continuation_index == 1
    assert result.completed_job.status == ContinuationJobStatus.SUCCEEDED
    assert result.attempted_job.attempts == 1
    assert result.attempted_job.heartbeat_at_ms == 123
    assert result.summary.output_text == "continued: lookup:42"
    assert observer.summaries == [result.summary]

    request = llm.requests[0]
    assert request.turn_index == 2
    assert request.messages == root.kernel_result.messages
    assert request.tool_context.agent_run_id == "run-cont-1"
    assert request.tool_context.correlation_id == "corr-1"

    completed_state = ContinuationState.from_json(result.completed_run.engine_state_json)
    assert completed_state.turn_offset == 2


async def test_continuation_runner_returns_none_when_queue_empty() -> None:
    runner = ContinuationRunner(
        continuation_queue=InMemoryContinuationQueue(),
        run_persistence=InMemoryRunPersistence(),
        event_log=InMemoryEventLog(),
        llm_client=ScriptedLLMClient([]),
    )

    assert await runner.run_next() is None


async def test_continuation_runner_marks_failed_and_dead_letters_on_error() -> None:
    persistence = InMemoryRunPersistence()
    event_log = InMemoryEventLog()
    root = await _create_continuable_root(
        persistence=persistence,
        event_log=event_log,
    )
    queue = InMemoryContinuationQueue()
    queue.enqueue_for_run(
        ContinuationJobSpec(
            user_request_id="request-1",
            project_id="project-1",
            previous_run_id=root.completed.run_id,
            next_run_id="run-cont-failed",
            max_attempts=1,
        ),
        job_id="job-failed",
    )
    runner = ContinuationRunner(
        continuation_queue=queue,
        run_persistence=persistence,
        event_log=event_log,
        llm_client=ScriptedLLMClient([]),
    )

    with pytest.raises(RuntimeError, match="no scripted LLM turn"):
        await runner.run_next(ContinuationRunnerRequest(worker_id="worker-1"))

    failed = persistence.load_run("run-cont-failed")
    job = queue.load_job("job-failed")
    assert failed is not None
    assert failed.status == RunStatus.FAILED
    assert job is not None
    assert job.status == ContinuationJobStatus.DEAD_LETTER
    assert "no scripted LLM turn" in str(job.last_error)


async def test_continuation_runner_fails_job_when_engine_state_is_invalid() -> None:
    persistence = InMemoryRunPersistence()
    previous = persistence.create_root_run(
        run_id="run-bad-state",
        scope=RunScope(
            user_request_id="request-1",
            project_id="project-1",
        ),
        budget=RunBudget(
            max_turns=1,
            max_tool_calls=1,
            max_wall_clock_s=30,
            total_timeout_s=60,
        ),
        max_continuations=1,
    )
    persistence.mark_completed(
        previous.run_id,
        completion=RunCompletion(
            stop_reason="max_turns",
            status=RunStatus.CONTINUABLE.value,
            engine_state_json="{bad json",
        ),
    )
    queue = InMemoryContinuationQueue()
    queue.enqueue_for_run(
        ContinuationJobSpec(
            user_request_id="request-1",
            project_id="project-1",
            previous_run_id=previous.run_id,
            next_run_id="run-cont-bad-state",
            max_attempts=1,
        ),
        job_id="job-bad-state",
    )
    runner = ContinuationRunner(
        continuation_queue=queue,
        run_persistence=persistence,
        event_log=InMemoryEventLog(),
        llm_client=ScriptedLLMClient([]),
    )

    with pytest.raises(ValueError):
        await runner.run_next(ContinuationRunnerRequest(worker_id="worker-1"))

    job = queue.load_job("job-bad-state")
    assert job is not None
    assert job.status == ContinuationJobStatus.DEAD_LETTER
    assert job.last_error
    assert persistence.load_run("run-cont-bad-state") is None


async def test_continuation_runner_rejects_existing_run_with_wrong_parent() -> None:
    persistence = InMemoryRunPersistence()
    event_log = InMemoryEventLog()
    root = await _create_continuable_root(
        persistence=persistence,
        event_log=event_log,
    )
    unrelated = persistence.create_root_run(
        run_id="run-cont-wrong-parent",
        scope=RunScope(
            user_request_id="request-1",
            project_id="project-1",
        ),
        budget=RunBudget(
            max_turns=1,
            max_tool_calls=1,
            max_wall_clock_s=30,
            total_timeout_s=60,
        ),
    )
    queue = InMemoryContinuationQueue()
    queue.enqueue_for_run(
        ContinuationJobSpec(
            user_request_id="request-1",
            project_id="project-1",
            previous_run_id=root.completed.run_id,
            next_run_id=unrelated.run_id,
            max_attempts=1,
        ),
        job_id="job-wrong-parent",
    )
    runner = ContinuationRunner(
        continuation_queue=queue,
        run_persistence=persistence,
        event_log=event_log,
        llm_client=ScriptedLLMClient([]),
    )

    with pytest.raises(RuntimeError, match="continuation run parent mismatch"):
        await runner.run_next(ContinuationRunnerRequest(worker_id="worker-1"))

    rejected = persistence.load_run(unrelated.run_id)
    job = queue.load_job("job-wrong-parent")
    assert rejected is not None
    assert rejected.status == RunStatus.PENDING
    assert job is not None
    assert job.status == ContinuationJobStatus.DEAD_LETTER


async def test_continuation_runner_fails_job_and_run_when_mark_running_fails() -> None:
    persistence = _MarkRunningFailsPersistence()
    event_log = InMemoryEventLog()
    root = await _create_continuable_root(
        persistence=persistence,
        event_log=event_log,
    )
    queue = InMemoryContinuationQueue()
    queue.enqueue_for_run(
        ContinuationJobSpec(
            user_request_id="request-1",
            project_id="project-1",
            previous_run_id=root.completed.run_id,
            next_run_id="run-cont-running-fails",
            max_attempts=1,
        ),
        job_id="job-running-fails",
    )
    runner = ContinuationRunner(
        continuation_queue=queue,
        run_persistence=persistence,
        event_log=event_log,
        llm_client=ScriptedLLMClient([]),
    )

    with pytest.raises(RuntimeError, match="cannot be marked running"):
        await runner.run_next(ContinuationRunnerRequest(worker_id="worker-1"))

    failed = persistence.load_run("run-cont-running-fails")
    job = queue.load_job("job-running-fails")
    assert failed is not None
    assert failed.status == RunStatus.FAILED
    assert "cannot be marked running" in str(failed.error_message)
    assert job is not None
    assert job.status == ContinuationJobStatus.DEAD_LETTER


def test_in_memory_continuation_queue_heartbeats_and_reclaims_stale_jobs() -> None:
    queue = InMemoryContinuationQueue(timestamp_ms=1_000)
    job = queue.enqueue_for_run(
        ContinuationJobSpec(
            user_request_id="request-1",
            project_id="project-1",
            previous_run_id="run-root",
            next_run_id="run-cont-1",
            max_attempts=2,
        ),
        job_id="job-1",
    )

    claimed = queue.claim_next(worker_id="worker-1", available_at_ms=2_000)
    assert claimed is not None
    assert queue.heartbeat(job.job_id, heartbeat_at_ms=1_500) is not None

    assert queue.reclaim_stale(stale_before_ms=1_600) == 1

    reclaimed = queue.load_job(job.job_id)
    assert reclaimed is not None
    assert reclaimed.status == ContinuationJobStatus.QUEUED
    assert reclaimed.worker_id is None
