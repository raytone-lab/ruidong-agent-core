from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from rd_agent_contracts import (
    AgentEvent,
    EventDraft,
    SubagentRunRecord,
    SubagentTaskRecord,
    SubagentTaskSpec,
    SubagentTaskStatus,
    SubagentWorkspaceMergeResult,
    TextBlock,
    ToolCallCounts,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolUseBlock,
    Usage,
)
from rd_agent_core import (
    SubagentBatchRunner,
    SubagentBatchRunnerRequest,
    SubagentRunner,
    SubagentRunnerRequest,
)
from rd_agent_core.run import RunKernelResult
from rd_agent_core.subagent_runner import _tool_history_from_kernel_result
from rd_agent_core.testing import FunctionToolExecutor, InMemoryEventLog, ScriptedLLMClient
from rd_agent_core.turn import TurnKernelResult
from rd_llm_adapter import TurnDone


class _SubagentTaskPort:
    def __init__(self, *tasks: SubagentTaskRecord) -> None:
        self.tasks = {task.task_id: task for task in tasks}
        self.failures: list[tuple[str, str]] = []

    def create_task(
        self,
        spec: SubagentTaskSpec,
        *,
        task_id: str | None = None,
    ) -> SubagentTaskRecord:
        task = SubagentTaskRecord(
            task_id=task_id or "task-created",
            user_request_id=spec.user_request_id,
            project_id=spec.project_id,
            name=spec.name,
            description=spec.description,
            status=SubagentTaskStatus.PENDING,
            parent_run_id=spec.parent_run_id,
            agent_profile=spec.agent_profile,
            write_scope_json=spec.write_scope_json,
            max_attempts=spec.max_attempts,
        )
        self.tasks[task.task_id] = task
        return task

    def list_tasks(self, *, user_request_id: str) -> list[SubagentTaskRecord]:
        return [
            task for task in self.tasks.values() if task.user_request_id == user_request_id
        ]

    def load_task(self, task_id: str) -> SubagentTaskRecord | None:
        return self.tasks.get(task_id)

    def claim_next_pending(self, **kwargs) -> SubagentTaskRecord | None:
        for task in self.tasks.values():
            user_request_id = kwargs.get("user_request_id")
            if user_request_id is not None and task.user_request_id != user_request_id:
                continue
            if task.status == SubagentTaskStatus.PENDING:
                claimed = replace(
                    task,
                    status=SubagentTaskStatus.RUNNING,
                    worker_id=kwargs.get("worker_id"),
                    started_at_ms=kwargs.get("started_at_ms"),
                )
                self.tasks[task.task_id] = claimed
                return claimed
        return None

    def claim_pending_batch(self, **kwargs) -> list[SubagentTaskRecord]:
        max_count = int(kwargs.get("max_count") or 1)
        claimed: list[SubagentTaskRecord] = []
        for _ in range(max_count):
            task = self.claim_next_pending(**kwargs)
            if task is None:
                break
            claimed.append(task)
        return claimed

    def mark_attempt_started(self, *, task_id: str) -> SubagentTaskRecord | None:
        task = self.tasks.get(task_id)
        if task is None:
            return None
        updated = replace(task, attempts=task.attempts + 1)
        self.tasks[task_id] = updated
        return updated

    def heartbeat(self, *, task_id: str, heartbeat_at_ms: int | None = None) -> None:
        return None

    def release_for_retry(self, **kwargs) -> SubagentTaskRecord | None:
        task = self.tasks.get(kwargs["task_id"])
        if task is None:
            return None
        updated = replace(
            task,
            status=SubagentTaskStatus.PENDING,
            error_message=kwargs["error_message"],
        )
        self.tasks[task.task_id] = updated
        return updated

    def reclaim_stale(self, *, stale_threshold_seconds: int | None = None) -> int:
        return 0

    def mark_completed(
        self,
        *,
        task_id: str,
        result_summary: str | None = None,
        outcome_json: dict | None = None,
        completed_at_ms: int | None = None,
    ) -> SubagentTaskRecord | None:
        return self._update(
            task_id,
            status=SubagentTaskStatus.COMPLETED,
            result_summary=result_summary,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )

    def mark_failed(
        self,
        *,
        task_id: str,
        error_message: str,
        outcome_json: dict | None = None,
        completed_at_ms: int | None = None,
    ) -> SubagentTaskRecord | None:
        return self._update(
            task_id,
            status=SubagentTaskStatus.FAILED,
            error_message=error_message,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )

    def mark_waiting(
        self,
        *,
        task_id: str,
        result_summary: str | None = None,
        outcome_json: dict | None = None,
    ) -> SubagentTaskRecord | None:
        return self._update(
            task_id,
            status=SubagentTaskStatus.WAITING_USER,
            result_summary=result_summary,
            outcome_json=outcome_json,
        )

    def mark_cancelled(
        self,
        *,
        task_id: str,
        error_message: str | None = None,
        outcome_json: dict | None = None,
        completed_at_ms: int | None = None,
    ) -> SubagentTaskRecord | None:
        return self._update(
            task_id,
            status=SubagentTaskStatus.CANCELLED,
            error_message=error_message,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )

    def mark_running(self, *, task_id: str) -> SubagentTaskRecord | None:
        return self._update(task_id, status=SubagentTaskStatus.RUNNING)

    def record_failure(
        self,
        *,
        task_id: str,
        error_message: str,
        outcome_json: dict | None = None,
        delay_seconds: int | None = None,
        completed_at_ms: int | None = None,
    ) -> SubagentTaskRecord | None:
        self.failures.append((task_id, error_message))
        return self.mark_failed(
            task_id=task_id,
            error_message=error_message,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )

    def _update(self, task_id: str, **changes) -> SubagentTaskRecord | None:
        task = self.tasks.get(task_id)
        if task is None:
            return None
        updated = replace(task, **changes)
        self.tasks[task_id] = updated
        return updated


class _SubagentRunPort:
    def __init__(self) -> None:
        self.created: list[SubagentRunRecord] = []

    def create_run_for_task(
        self,
        task: SubagentTaskRecord,
        *,
        session_id: str | None = None,
    ) -> SubagentRunRecord:
        run = SubagentRunRecord(
            task_id=task.task_id,
            run_id=f"run-{task.task_id}",
            user_request_id=task.user_request_id,
            project_id=task.project_id,
            session_id=session_id,
            parent_run_id=task.parent_run_id,
            correlation_id=task.correlation_id,
        )
        self.created.append(run)
        return run


class _FailingRunPort:
    def create_run_for_task(
        self,
        task: SubagentTaskRecord,
        *,
        session_id: str | None = None,
    ) -> SubagentRunRecord:
        raise RuntimeError("run creation failed")


class _FailingWorkspacePort:
    def prepare_workspace(self, _spec):
        raise RuntimeError("workspace prepare failed")


class _MarkAttemptStartedNoneTaskPort(_SubagentTaskPort):
    def mark_attempt_started(self, *, task_id: str) -> SubagentTaskRecord | None:
        return None


class _TrackingWorkspaceHandle:
    def __init__(
        self,
        *,
        task_port: _SubagentTaskPort,
        fail: bool = False,
    ) -> None:
        self.project_id = "project-1"
        self.task_id = "task-1"
        self.run_id = "run-task-1"
        self.write_scope_paths = ["src"]
        self.task_port = task_port
        self.fail = fail
        self.status_at_merge: str | None = None

    def merge_back(self, *, cleanup: bool = True) -> SubagentWorkspaceMergeResult:
        task = self.task_port.load_task(self.task_id)
        self.status_at_merge = task.status if task is not None else None
        if self.fail:
            raise RuntimeError("merge conflict")
        return SubagentWorkspaceMergeResult(
            changed=True,
            merged_paths=["src/app.py"],
            generation=7,
        )

    def cleanup(self) -> None:
        return None


class _TrackingWorkspacePort:
    def __init__(self, *, task_port: _SubagentTaskPort, fail: bool = False) -> None:
        self.handle = _TrackingWorkspaceHandle(task_port=task_port, fail=fail)

    def prepare_workspace(self, _spec) -> _TrackingWorkspaceHandle:
        return self.handle


class _RunSummaryObserver:
    def __init__(self) -> None:
        self.summaries = []

    def record_run_summary(self, summary) -> None:
        self.summaries.append(summary)


class _EventLog(InMemoryEventLog):
    def append_event(
        self,
        run_id: str,
        draft: EventDraft,
        *,
        idempotency_key: str | None = None,
    ) -> AgentEvent:
        return super().append_event(run_id, draft, idempotency_key=idempotency_key)


def _task(agent_profile: str | None = "planner") -> SubagentTaskRecord:
    return SubagentTaskRecord(
        task_id="task-1",
        user_request_id="request-1",
        project_id="project-1",
        name="Inspect docs",
        description="Read project docs and summarize.",
        status=SubagentTaskStatus.PENDING,
        parent_run_id="run-parent",
        agent_profile=agent_profile,
    )


def _final_turn(_request):
    text = TextBlock("subagent done")
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


def _ask_user_turn(_request):
    text = TextBlock("need input")
    return [
        TurnDone(
            stop_reason="ask_user",
            content=[text],
            text_blocks=[text],
            reasoning_blocks=[],
            tool_calls=[],
            invalid_tool_calls=[],
            raw_stop_reason="ask_user",
        )
    ]


async def _cancelled_turn(_request):
    raise asyncio.CancelledError()
    yield  # pragma: no cover


async def test_subagent_runner_claims_filters_tools_and_marks_completed() -> None:
    task_port = _SubagentTaskPort(_task("planner"))
    run_port = _SubagentRunPort()
    llm = ScriptedLLMClient([_final_turn])
    runner = SubagentRunner(
        task_port=task_port,
        run_port=run_port,
        event_log=_EventLog(),
        llm_client=llm,
        tool_executor=FunctionToolExecutor({}),
    )
    read_tool = ToolDefinition(
        name="read_file",
        description="Read",
        input_schema={"type": "object"},
    )
    write_tool = ToolDefinition(
        name="write_file",
        description="Write",
        input_schema={"type": "object"},
        mutates_workspace=True,
    )

    result = await runner.run_next(
        SubagentRunnerRequest(
            session_id="session-1",
            tools=(read_tool, write_tool),
            tool_context=ToolExecutionContext(project_id="project-ignored"),
        )
    )

    assert result is not None
    assert result.completed_task.status == SubagentTaskStatus.COMPLETED
    assert result.completed_task.result_summary == "subagent done"
    assert result.completed_task.outcome_json is not None
    assert result.completed_task.outcome_json["status"] == "completed"
    assert result.run.run_id == "run-task-1"
    request = llm.requests[0]
    assert [tool.name for tool in request.tools] == ["read_file"]
    assert "Inspect docs" in str(request.system_prompt)
    assert request.tool_context.project_id == "project-1"
    assert request.tool_context.agent_kind == "subagent"
    assert request.tool_context.subagent_task_id == "task-1"


async def test_subagent_runner_records_failure_when_kernel_raises() -> None:
    task_port = _SubagentTaskPort(_task("general"))
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([]),
    )

    with pytest.raises(RuntimeError, match="no scripted LLM turn"):
        await runner.run_next(SubagentRunnerRequest())

    failed = task_port.load_task("task-1")
    assert failed is not None
    assert failed.status == SubagentTaskStatus.FAILED
    assert task_port.failures == [("task-1", "no scripted LLM turn at index 0")]


async def test_subagent_runner_records_failure_when_run_creation_fails() -> None:
    task_port = _SubagentTaskPort(_task("general"))
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_FailingRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn]),
    )

    with pytest.raises(RuntimeError, match="run creation failed"):
        await runner.run_next(SubagentRunnerRequest())

    failed = task_port.load_task("task-1")
    assert failed is not None
    assert failed.status == SubagentTaskStatus.FAILED
    assert failed.attempts == 1
    assert failed.error_message == "run creation failed"
    assert task_port.failures == [("task-1", "run creation failed")]


async def test_subagent_runner_records_failure_when_workspace_prepare_fails() -> None:
    task = replace(
        _task("backend_editor"),
        write_scope_json={"paths": ["src"]},
    )
    task_port = _SubagentTaskPort(task)
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn]),
        workspace_port=_FailingWorkspacePort(),
    )

    with pytest.raises(RuntimeError, match="workspace prepare failed"):
        await runner.run_next(
            SubagentRunnerRequest(
                workspace_isolation_enabled=True,
                inline_parallel_enabled=True,
            )
        )

    failed = task_port.load_task("task-1")
    assert failed is not None
    assert failed.status == SubagentTaskStatus.FAILED
    assert failed.error_message == "workspace prepare failed"
    assert task_port.failures == [("task-1", "workspace prepare failed")]


async def test_subagent_runner_does_not_continue_when_mark_attempt_started_returns_none() -> None:
    task_port = _MarkAttemptStartedNoneTaskPort(_task("general"))
    run_port = _SubagentRunPort()
    runner = SubagentRunner(
        task_port=task_port,
        run_port=run_port,
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn]),
    )

    with pytest.raises(RuntimeError, match="cannot be marked attempt started"):
        await runner.run_next(SubagentRunnerRequest())

    failed = task_port.load_task("task-1")
    assert failed is not None
    assert failed.status == SubagentTaskStatus.FAILED
    assert failed.attempts == 0
    assert failed.error_message == (
        "subagent task cannot be marked attempt started: task-1"
    )
    assert run_port.created == []


async def test_subagent_runner_merges_workspace_before_marking_completed() -> None:
    task = replace(
        _task("backend_editor"),
        write_scope_json={"paths": ["src"]},
    )
    task_port = _SubagentTaskPort(task)
    workspace_port = _TrackingWorkspacePort(task_port=task_port)
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn]),
        workspace_port=workspace_port,
    )

    result = await runner.run_next(
        SubagentRunnerRequest(
            workspace_isolation_enabled=True,
            inline_parallel_enabled=True,
        )
    )

    assert result is not None
    assert workspace_port.handle.status_at_merge == SubagentTaskStatus.RUNNING
    assert result.completed_task.status == SubagentTaskStatus.COMPLETED
    assert result.workspace_merge_result == SubagentWorkspaceMergeResult(
        changed=True,
        merged_paths=["src/app.py"],
        generation=7,
    )
    assert result.completed_task.outcome_json is not None
    assert result.completed_task.outcome_json["workspace_merge"] == {
        "attempted": True,
        "ok": True,
        "changed_paths": ["src/app.py"],
        "generation": 7,
        "error": None,
        "skipped_reason": None,
    }


async def test_subagent_runner_marks_failed_when_workspace_merge_fails() -> None:
    task = replace(
        _task("backend_editor"),
        write_scope_json={"paths": ["src"]},
    )
    task_port = _SubagentTaskPort(task)
    workspace_port = _TrackingWorkspacePort(task_port=task_port, fail=True)
    observer = _RunSummaryObserver()
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn]),
        workspace_port=workspace_port,
        run_observer=observer,
    )

    result = await runner.run_next(
        SubagentRunnerRequest(
            workspace_isolation_enabled=True,
            inline_parallel_enabled=True,
        )
    )

    assert result is not None
    assert workspace_port.handle.status_at_merge == SubagentTaskStatus.RUNNING
    assert result.completed_task.status == SubagentTaskStatus.FAILED
    assert result.completed_task.error_message == "Workspace merge failed: merge conflict"
    assert result.summary.status == "failed"
    assert observer.summaries[-1].status == "failed"
    assert result.completed_task.outcome_json is not None
    assert result.completed_task.outcome_json["status"] == "failed"
    assert result.completed_task.outcome_json["failure"] == {
        "type": "workspace_merge_failed",
        "error_type": "RuntimeError",
        "message": "merge conflict",
    }
    assert result.completed_task.outcome_json["workspace_merge"] == {
        "attempted": True,
        "ok": False,
        "changed_paths": [],
        "generation": None,
        "error": {"type": "RuntimeError", "message": "merge conflict"},
        "skipped_reason": None,
    }


async def test_subagent_runner_marks_cancelled_when_task_is_cancelled() -> None:
    task_port = _SubagentTaskPort(_task("general"))
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_cancelled_turn]),
    )

    with pytest.raises(asyncio.CancelledError):
        await runner.run_next(SubagentRunnerRequest())

    cancelled = task_port.load_task("task-1")
    assert cancelled is not None
    assert cancelled.status == SubagentTaskStatus.CANCELLED
    assert cancelled.outcome_json is not None
    assert cancelled.outcome_json["status"] == "cancelled"


async def test_subagent_summary_status_matches_waiting_task_status() -> None:
    task_port = _SubagentTaskPort(_task("general"))
    observer = _RunSummaryObserver()
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_ask_user_turn]),
        run_observer=observer,
    )

    result = await runner.run_next(SubagentRunnerRequest())

    assert result is not None
    assert result.completed_task.status == SubagentTaskStatus.WAITING_USER
    assert result.summary.status == "waiting_user"
    assert result.summary.metadata["subagent_task_status"] == "waiting_user"
    assert observer.summaries[-1].status == "waiting_user"


async def test_subagent_batch_runner_fans_out_and_fans_in_completed_tasks() -> None:
    first = _task("general")
    second = replace(_task("general"), task_id="task-2", name="Check docs")
    task_port = _SubagentTaskPort(first, second)
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn, _final_turn]),
    )
    batch = SubagentBatchRunner(task_port=task_port, runner=runner)

    result = await batch.run_batch(
        SubagentBatchRunnerRequest(
            user_request_id="request-1",
            worker_id="worker-batch",
            max_count=2,
            runner_request=SubagentRunnerRequest(),
        )
    )

    assert [task.task_id for task in result.claimed_tasks] == ["task-1", "task-2"]
    assert [task.status for task in result.completed_tasks] == [
        SubagentTaskStatus.COMPLETED,
        SubagentTaskStatus.COMPLETED,
    ]
    assert len(result.results) == 2
    assert result.errors == ()
    assert result.aggregate_outcome["kind"] == "subagent_aggregate"
    assert result.aggregate_outcome["status"] == "completed"
    assert result.aggregate_outcome["total"] == 2
    assert "Subagent results:" in result.aggregate_text


async def test_subagent_batch_runner_collects_errors_into_failed_aggregate() -> None:
    first = _task("general")
    second = replace(_task("general"), task_id="task-2", name="Check docs")
    task_port = _SubagentTaskPort(first, second)
    runner = SubagentRunner(
        task_port=task_port,
        run_port=_SubagentRunPort(),
        event_log=_EventLog(),
        llm_client=ScriptedLLMClient([_final_turn]),
    )
    batch = SubagentBatchRunner(task_port=task_port, runner=runner)

    result = await batch.run_batch(
        SubagentBatchRunnerRequest(
            user_request_id="request-1",
            max_count=2,
            runner_request=SubagentRunnerRequest(),
        )
    )

    assert len(result.results) == 1
    assert len(result.errors) == 1
    assert result.errors[0].task_id == "task-2"
    assert result.errors[0].error_type == "RuntimeError"
    assert result.completed_tasks[1].status == SubagentTaskStatus.FAILED
    assert result.aggregate_outcome["status"] == "failed"
    assert result.aggregate_outcome["failed"] == 1


def test_subagent_tool_history_pairs_by_tool_use_id_not_position() -> None:
    first_call = ToolUseBlock(id="tool-1", name="read_file", input={"path": "a.txt"})
    second_call = ToolUseBlock(id="tool-2", name="write_file", input={"path": "b.txt"})
    turn_result = TurnKernelResult(
        stop_reason="end_turn",
        raw_stop_reason="stop",
        content=(first_call, second_call),
        usage=Usage(),
        tool_results=(
            ToolExecutionResult(
                ok=True,
                content="second",
                tool_use_id="tool-2",
                duration_ms=20,
            ),
            ToolExecutionResult(
                ok=False,
                content="first",
                tool_use_id="tool-1",
                error={"type": "read_failed"},
                duration_ms=10,
            ),
        ),
        invalid_tool_calls=(),
        events=(),
        tool_call_counts=ToolCallCounts(requested=2, executed=2, denied=0),
    )
    kernel_result = RunKernelResult(
        stop_reason="end_turn",
        messages=(),
        turns_count=1,
        tool_calls_count=2,
        tool_call_counts=ToolCallCounts(requested=2, executed=2, denied=0),
        usage=Usage(),
        turn_results=(turn_result,),
        events=(),
        tool_results=turn_result.tool_results,
    )

    history = _tool_history_from_kernel_result(kernel_result)

    assert history == [
        {
            "tool_use_id": "tool-1",
            "tool_name": "read_file",
            "tool_input": {"path": "a.txt"},
            "ok": False,
            "error": {"type": "read_failed"},
            "duration_ms": 10,
        },
        {
            "tool_use_id": "tool-2",
            "tool_name": "write_file",
            "tool_input": {"path": "b.txt"},
            "ok": True,
            "error": None,
            "duration_ms": 20,
        },
    ]


def test_subagent_tool_history_records_missing_tool_result() -> None:
    tool_call = ToolUseBlock(id="tool-missing", name="read_file", input={"path": "a"})
    turn_result = TurnKernelResult(
        stop_reason="end_turn",
        raw_stop_reason="stop",
        content=(tool_call,),
        usage=Usage(),
        tool_results=(),
        invalid_tool_calls=(),
        events=(),
        tool_call_counts=ToolCallCounts(requested=1, executed=0, denied=0),
    )
    kernel_result = RunKernelResult(
        stop_reason="end_turn",
        messages=(),
        turns_count=1,
        tool_calls_count=0,
        tool_call_counts=ToolCallCounts(requested=1, executed=0, denied=0),
        usage=Usage(),
        turn_results=(turn_result,),
        events=(),
        tool_results=(),
    )

    history = _tool_history_from_kernel_result(kernel_result)

    assert history == [
        {
            "tool_use_id": "tool-missing",
            "tool_name": "read_file",
            "tool_input": {"path": "a"},
            "ok": False,
            "error": {
                "type": "tool_result_missing",
                "message": "Missing tool result for tool-missing",
            },
            "duration_ms": None,
        }
    ]
