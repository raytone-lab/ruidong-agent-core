from __future__ import annotations

from dataclasses import replace

import pytest
from rd_agent_contracts import (
    AgentEvent,
    EventDraft,
    SubagentRunRecord,
    SubagentTaskRecord,
    SubagentTaskSpec,
    SubagentTaskStatus,
    TextBlock,
    ToolDefinition,
    ToolExecutionContext,
)
from rd_agent_core import SubagentRunner, SubagentRunnerRequest
from rd_agent_core.testing import FunctionToolExecutor, InMemoryEventLog, ScriptedLLMClient
from rd_llm_adapter import TurnDone


class _SubagentTaskPort:
    def __init__(self, task: SubagentTaskRecord) -> None:
        self.tasks = {task.task_id: task}
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

    def claim_next_pending(self, **_kwargs) -> SubagentTaskRecord | None:
        for task in self.tasks.values():
            if task.status == SubagentTaskStatus.PENDING:
                claimed = replace(task, status=SubagentTaskStatus.RUNNING)
                self.tasks[task.task_id] = claimed
                return claimed
        return None

    def claim_pending_batch(self, **_kwargs) -> list[SubagentTaskRecord]:
        task = self.claim_next_pending()
        return [task] if task is not None else []

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
