"""High-level host-neutral subagent runner."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from rd_agent_contracts import (
    AgentEvent,
    CancellationToken,
    EventLogPort,
    IdGenerator,
    Message,
    SubagentRunPort,
    SubagentRunRecord,
    SubagentTaskPort,
    SubagentTaskRecord,
    SubagentTaskStatus,
    SubagentWorkspaceHandle,
    SubagentWorkspaceMergeResult,
    SubagentWorkspacePort,
    SubagentWorkspaceSpec,
    ToolDefinition,
    ToolExecutionContext,
    ToolObservabilityPort,
    ToolUseBlock,
    build_subagent_aggregate_outcome,
    build_subagent_instruction_text,
    build_subagent_outcome_json,
    decide_subagent_finalization,
    filter_subagent_tools_for_profile,
    format_subagent_aggregate,
    needs_attention_for_stop_reason,
    should_merge_subagent_workspace,
)

from .errors import CoreErrorType
from .events import CoreEventWriter
from .model_profile import ModelProfile
from .observability import RunObserverLike, notify_run_observer
from .policies import RunLimits
from .run import RunKernel, RunKernelResult, RunRequest
from .summary import RunSummary, summarize_failed_run, summarize_kernel_result
from .turn import CoreToolPolicy, LLMClientPort, ToolExecutorLike


@dataclass(frozen=True)
class SubagentRunnerRequest:
    user_request_id: str | None = None
    worker_id: str | None = None
    session_id: str | None = None
    messages: Sequence[Message] = ()
    tools: Sequence[ToolDefinition] = ()
    tool_context: ToolExecutionContext | None = None
    model: str | None = None
    model_profile: ModelProfile | None = None
    system_prompt: str | None = None
    limits: RunLimits = field(default_factory=RunLimits)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken | None = None
    workspace_isolation_enabled: bool = False
    inline_parallel_enabled: bool = False
    retryable_needs_attention: bool = False
    failure_retry_delay_seconds: int | None = None
    parent_completed_grace_seconds: float | None = None
    skip_user_requests_with_running: bool = False


@dataclass(frozen=True)
class SubagentRunnerResult:
    task: SubagentTaskRecord
    attempted_task: SubagentTaskRecord
    run: SubagentRunRecord
    completed_task: SubagentTaskRecord
    kernel_result: RunKernelResult
    events: tuple[AgentEvent, ...]
    summary: RunSummary
    workspace: SubagentWorkspaceHandle | None = None
    workspace_merge_result: SubagentWorkspaceMergeResult | None = None


@dataclass(frozen=True)
class SubagentBatchRunnerRequest:
    user_request_id: str
    worker_id: str | None = None
    max_count: int = 4
    candidate_limit: int | None = None
    started_at_ms: int | None = None
    runner_request: SubagentRunnerRequest = field(default_factory=SubagentRunnerRequest)

    def __post_init__(self) -> None:
        if self.max_count < 1:
            raise ValueError("max_count must be >= 1")


@dataclass(frozen=True)
class SubagentBatchRunnerError:
    task_id: str
    error_type: str
    message: str


@dataclass(frozen=True)
class SubagentBatchRunnerResult:
    claimed_tasks: tuple[SubagentTaskRecord, ...]
    results: tuple[SubagentRunnerResult, ...]
    completed_tasks: tuple[SubagentTaskRecord, ...]
    aggregate_outcome: dict[str, Any]
    aggregate_text: str
    errors: tuple[SubagentBatchRunnerError, ...] = ()


class SubagentTaskClaimLostError(RuntimeError):
    """Current worker no longer owns the claimed task."""

    def __init__(self, task_id: str, status: str | None = None) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(f"subagent task claim lost: {task_id}; status={status}")


class SubagentTaskLostError(RuntimeError):
    """Claimed task disappeared before this worker could start an attempt."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"subagent task disappeared before attempt: {task_id}")


class SubagentRunner:
    """Claim and execute one subagent task using public core/contracts ports."""

    def __init__(
        self,
        *,
        task_port: SubagentTaskPort,
        run_port: SubagentRunPort,
        event_log: EventLogPort,
        llm_client: LLMClientPort,
        tool_executor: ToolExecutorLike | None = None,
        tool_observability: ToolObservabilityPort | None = None,
        tool_policy: CoreToolPolicy | None = None,
        workspace_port: SubagentWorkspacePort | None = None,
        run_observer: RunObserverLike | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._task_port = task_port
        self._run_port = run_port
        self._event_log = event_log
        self._llm_client = llm_client
        self._tool_executor = tool_executor
        self._tool_observability = tool_observability
        self._tool_policy = tool_policy
        self._workspace_port = workspace_port
        self._run_observer = run_observer
        self._id_generator = id_generator

    async def run_next(
        self,
        request: SubagentRunnerRequest | None = None,
    ) -> SubagentRunnerResult | None:
        resolved_request = request or SubagentRunnerRequest()
        task = self._task_port.claim_next_pending(
            user_request_id=resolved_request.user_request_id,
            worker_id=resolved_request.worker_id,
            parent_completed_grace_seconds=(
                resolved_request.parent_completed_grace_seconds
            ),
            skip_user_requests_with_running=(
                resolved_request.skip_user_requests_with_running
            ),
        )
        if task is None:
            return None
        return await self.run_claimed_task(task, resolved_request)

    async def run_claimed_task(
        self,
        task: SubagentTaskRecord,
        request: SubagentRunnerRequest | None = None,
    ) -> SubagentRunnerResult:
        resolved_request = request or SubagentRunnerRequest()
        attempted_task = task
        run: SubagentRunRecord | None = None
        workspace: SubagentWorkspaceHandle | None = None
        merge_attempted = False
        merge_result: SubagentWorkspaceMergeResult | None = None
        merge_error: Exception | None = None
        merge_cleanup_ok: bool | None = None
        merge_cleanup_error: Exception | None = None
        try:
            marked_task = self._task_port.mark_attempt_started(task_id=task.task_id)
            if marked_task is None:
                latest_task = self._task_port.load_task(task.task_id)
                if latest_task is None:
                    raise SubagentTaskLostError(task.task_id)
                raise SubagentTaskClaimLostError(task.task_id, str(latest_task.status))
            attempted_task = marked_task
            run = self._run_port.create_run_for_task(
                attempted_task,
                session_id=resolved_request.session_id,
            )
            workspace = self._prepare_workspace(attempted_task, run, resolved_request)

            kernel = RunKernel(
                llm_client=self._llm_client,
                event_writer=CoreEventWriter(self._event_log, run_id=run.run_id),
                tool_executor=self._tool_executor,
                tool_observability=self._tool_observability,
                tool_policy=self._tool_policy,
                id_generator=self._id_generator,
            )
            kernel_result = await kernel.run(
                RunRequest(
                    run_id=run.run_id,
                    messages=tuple(resolved_request.messages),
                    tool_context=self._resolve_tool_context(
                        attempted_task,
                        run,
                        resolved_request,
                    ),
                    tools=tuple(
                        filter_subagent_tools_for_profile(
                            resolved_request.tools,
                            agent_profile=attempted_task.agent_profile,
                        )
                    ),
                    model=resolved_request.model,
                    model_profile=resolved_request.model_profile,
                    system_prompt=self._build_system_prompt(
                        attempted_task,
                        resolved_request,
                    ),
                    limits=resolved_request.limits,
                    metadata={
                        **dict(resolved_request.metadata),
                        "subagent_task_id": attempted_task.task_id,
                        "subagent_profile": attempted_task.agent_profile,
                    },
                    cancellation_token=resolved_request.cancellation_token,
                )
            )
            events = tuple(self._event_log.stream_events(run.run_id))
            summary = summarize_kernel_result(
                run_id=run.run_id,
                status="running",
                kernel_result=kernel_result,
                events=events,
                metadata={"subagent_task_id": attempted_task.task_id},
            )
            merge_attempted = self._should_merge_workspace(
                workspace,
                kernel_result.stop_reason,
                resolved_request,
            )
            if merge_attempted:
                try:
                    merge_result = self._merge_workspace_if_needed(
                        workspace,
                        kernel_result.stop_reason,
                        resolved_request,
                    )
                    merge_cleanup_ok = True
                except Exception as exc:
                    merge_error = exc
                    try:
                        if workspace is not None:
                            workspace.cleanup()
                        merge_cleanup_ok = True
                    except Exception as cleanup_exc:
                        merge_cleanup_ok = False
                        merge_cleanup_error = cleanup_exc
            completed_task = self._finalize_task(
                attempted_task,
                kernel_result,
                summary,
                resolved_request,
                run_id=run.run_id,
                merge_attempted=merge_attempted,
                merge_result=merge_result,
                merge_error=merge_error,
                merge_cleanup_ok=merge_cleanup_ok,
                merge_cleanup_error=merge_cleanup_error,
            )
            summary = summarize_kernel_result(
                run_id=run.run_id,
                status=str(completed_task.status),
                kernel_result=kernel_result,
                events=events,
                error_message=completed_task.error_message,
                metadata={
                    "subagent_task_id": completed_task.task_id,
                    "subagent_task_status": str(completed_task.status),
                    "subagent_profile": completed_task.agent_profile,
                },
            )
            await notify_run_observer(self._run_observer, summary)
            return SubagentRunnerResult(
                task=task,
                attempted_task=attempted_task,
                run=run,
                completed_task=completed_task,
                kernel_result=kernel_result,
                events=events,
                summary=summary,
                workspace=workspace,
                workspace_merge_result=merge_result,
            )
        except asyncio.CancelledError:
            events = (
                tuple(self._event_log.stream_events(run.run_id))
                if run is not None
                else ()
            )
            workspace_cleanup_ok: bool | None = None
            workspace_cleanup_error: Exception | None = None
            if workspace is not None and not merge_attempted:
                workspace_cleanup_ok, workspace_cleanup_error = (
                    _cleanup_workspace_after_failure(workspace)
                )
            summary = summarize_failed_run(
                run_id=run.run_id if run is not None else attempted_task.task_id,
                status="cancelled",
                stop_reason=CoreErrorType.CANCELLED.value,
                error_message="cancelled",
                events=events,
                metadata={"subagent_task_id": attempted_task.task_id},
            )
            self._record_task_cancelled(
                attempted_task,
                run_id=run.run_id if run is not None else None,
                workspace_cleanup_ok=workspace_cleanup_ok,
                workspace_cleanup_error=workspace_cleanup_error,
            )
            await notify_run_observer(self._run_observer, summary)
            raise
        except (SubagentTaskClaimLostError, SubagentTaskLostError):
            raise
        except Exception as exc:
            events = (
                tuple(self._event_log.stream_events(run.run_id))
                if run is not None
                else ()
            )
            workspace_cleanup_ok: bool | None = None
            workspace_cleanup_error: Exception | None = None
            if workspace is not None and not merge_attempted:
                workspace_cleanup_ok, workspace_cleanup_error = (
                    _cleanup_workspace_after_failure(workspace)
                )
            summary = summarize_failed_run(
                run_id=run.run_id if run is not None else attempted_task.task_id,
                error_message=str(exc),
                events=events,
                metadata={"subagent_task_id": attempted_task.task_id},
            )
            self._record_task_failure(
                attempted_task,
                exc,
                run_id=run.run_id if run is not None else None,
                delay_seconds=resolved_request.failure_retry_delay_seconds,
                merge_attempted=merge_attempted,
                merge_result=merge_result,
                merge_error=merge_error,
                merge_cleanup_ok=merge_cleanup_ok,
                merge_cleanup_error=merge_cleanup_error,
                workspace_cleanup_ok=workspace_cleanup_ok,
                workspace_cleanup_error=workspace_cleanup_error,
                failure_stage=(
                    "finalize_after_merge"
                    if merge_attempted
                    else "runtime"
                ),
            )
            await notify_run_observer(self._run_observer, summary)
            raise

    def _prepare_workspace(
        self,
        task: SubagentTaskRecord,
        run: SubagentRunRecord,
        request: SubagentRunnerRequest,
    ) -> SubagentWorkspaceHandle | None:
        if self._workspace_port is None or not request.workspace_isolation_enabled:
            return None
        if not request.inline_parallel_enabled:
            return None
        if not task.write_scope_json:
            return None
        return self._workspace_port.prepare_workspace(
            SubagentWorkspaceSpec(
                project_id=task.project_id,
                task_id=task.task_id,
                run_id=run.run_id,
                write_scope_json=task.write_scope_json,
            )
        )

    def _resolve_tool_context(
        self,
        task: SubagentTaskRecord,
        run: SubagentRunRecord,
        request: SubagentRunnerRequest,
    ) -> ToolExecutionContext:
        if request.tool_context is not None:
            return replace(
                request.tool_context,
                project_id=task.project_id,
                correlation_id=task.correlation_id
                or request.tool_context.correlation_id,
                session_id=run.session_id or request.tool_context.session_id,
                user_request_id=task.user_request_id,
                agent_run_id=run.run_id,
                agent_kind="subagent",
                subagent_task_id=task.task_id,
                metadata={
                    **dict(request.tool_context.metadata),
                    "subagent_task_id": task.task_id,
                    "subagent_profile": task.agent_profile,
                },
            )
        return ToolExecutionContext(
            project_id=task.project_id,
            correlation_id=task.correlation_id,
            session_id=run.session_id,
            user_request_id=task.user_request_id,
            agent_run_id=run.run_id,
            agent_kind="subagent",
            subagent_task_id=task.task_id,
            metadata={
                "subagent_task_id": task.task_id,
                "subagent_profile": task.agent_profile,
            },
        )

    def _build_system_prompt(
        self,
        task: SubagentTaskRecord,
        request: SubagentRunnerRequest,
    ) -> str:
        instruction = build_subagent_instruction_text(
            name=task.name,
            description=task.description,
            agent_profile=task.agent_profile,
            write_scope_json=task.write_scope_json,
        )
        return "\n\n".join(
            part for part in (request.system_prompt, instruction) if part
        )

    def _finalize_task(
        self,
        task: SubagentTaskRecord,
        kernel_result: RunKernelResult,
        summary: RunSummary,
        request: SubagentRunnerRequest,
        *,
        run_id: str | None,
        merge_attempted: bool,
        merge_result: SubagentWorkspaceMergeResult | None,
        merge_error: Exception | None,
        merge_cleanup_ok: bool | None,
        merge_cleanup_error: Exception | None,
    ) -> SubagentTaskRecord:
        workspace_merge = _workspace_merge_outcome(
            attempted=merge_attempted,
            result=merge_result,
            error=merge_error,
            cleanup_ok=merge_cleanup_ok,
            cleanup_error=merge_cleanup_error,
        )
        if kernel_result.stop_reason == CoreErrorType.CANCELLED.value:
            failure = {"type": "CancelledError", "message": "cancelled"}
            if merge_error is not None:
                failure = _workspace_merge_failure(merge_error)
            outcome = build_subagent_outcome_json(
                stop_reason=kernel_result.stop_reason,
                tool_history=_tool_history_from_kernel_result(kernel_result),
                tool_calls_count=kernel_result.tool_calls_count,
                tool_call_counts=kernel_result.tool_call_counts,
                turns_count=kernel_result.turns_count,
                summary="cancelled",
                task_status=SubagentTaskStatus.CANCELLED.value,
                task_id=task.task_id,
                run_id=run_id,
                workspace_merge=workspace_merge,
                agent_profile=task.agent_profile,
                write_scope_json=task.write_scope_json,
                error_message="cancelled",
                failure=failure,
            )
            completed = self._task_port.mark_cancelled(
                task_id=task.task_id,
                error_message="cancelled",
                outcome_json=outcome,
            )
            if completed is None:
                raise RuntimeError(f"subagent task disappeared: {task.task_id}")
            return completed

        if merge_error is not None:
            error_message = f"Workspace merge failed: {merge_error}"
            outcome = build_subagent_outcome_json(
                stop_reason=kernel_result.stop_reason,
                tool_history=_tool_history_from_kernel_result(kernel_result),
                tool_calls_count=kernel_result.tool_calls_count,
                tool_call_counts=kernel_result.tool_call_counts,
                turns_count=kernel_result.turns_count,
                summary=summary.output_text or error_message,
                task_status=SubagentTaskStatus.FAILED.value,
                task_id=task.task_id,
                run_id=run_id,
                workspace_merge=workspace_merge,
                agent_profile=task.agent_profile,
                write_scope_json=task.write_scope_json,
                error_message=error_message,
                failure=_workspace_merge_failure(merge_error),
            )
            completed = self._task_port.mark_failed(
                task_id=task.task_id,
                error_message=error_message,
                outcome_json=outcome,
            )
            if completed is None:
                raise RuntimeError(f"subagent task disappeared: {task.task_id}")
            return completed

        needs_attention = needs_attention_for_stop_reason(kernel_result.stop_reason)
        result_summary = summary.output_text or kernel_result.stop_reason
        decision = decide_subagent_finalization(
            stop_reason=kernel_result.stop_reason,
            queued_continuation=False,
            needs_attention=needs_attention,
            summary=result_summary,
            failure_message=(
                f"Subagent stopped with {kernel_result.stop_reason}"
            ),
            retryable_needs_attention=request.retryable_needs_attention,
        )
        outcome = build_subagent_outcome_json(
            stop_reason=kernel_result.stop_reason,
            tool_history=_tool_history_from_kernel_result(kernel_result),
            tool_calls_count=kernel_result.tool_calls_count,
            tool_call_counts=kernel_result.tool_call_counts,
            turns_count=kernel_result.turns_count,
            summary=result_summary,
            task_status=decision.task_status,
            task_id=task.task_id,
            run_id=run_id,
            workspace_merge=workspace_merge,
            agent_profile=task.agent_profile,
            write_scope_json=task.write_scope_json,
            error_message=decision.error_message,
        )
        if decision.operation == "mark_waiting":
            completed = self._task_port.mark_waiting(
                task_id=task.task_id,
                result_summary=decision.result_summary,
                outcome_json=outcome,
            )
        elif decision.operation == "record_failure":
            completed = self._task_port.record_failure(
                task_id=task.task_id,
                error_message=decision.error_message or "Subagent needs attention.",
                outcome_json=outcome,
                delay_seconds=request.failure_retry_delay_seconds,
            )
        elif decision.operation == "mark_failed":
            completed = self._task_port.mark_failed(
                task_id=task.task_id,
                error_message=decision.error_message or "Subagent failed.",
                outcome_json=outcome,
            )
        elif decision.operation == "mark_running":
            completed = self._task_port.mark_running(task_id=task.task_id)
        else:
            completed = self._task_port.mark_completed(
                task_id=task.task_id,
                result_summary=decision.result_summary,
                outcome_json=outcome,
            )
        if completed is None:
            raise RuntimeError(f"subagent task disappeared: {task.task_id}")
        return completed

    def _record_task_failure(
        self,
        task: SubagentTaskRecord,
        exc: Exception,
        *,
        run_id: str | None = None,
        delay_seconds: int | None = None,
        merge_attempted: bool = False,
        merge_result: SubagentWorkspaceMergeResult | None = None,
        merge_error: Exception | None = None,
        merge_cleanup_ok: bool | None = None,
        merge_cleanup_error: Exception | None = None,
        workspace_cleanup_ok: bool | None = None,
        workspace_cleanup_error: Exception | None = None,
        failure_stage: str = "runtime",
    ) -> SubagentTaskRecord | None:
        failure_type = (
            "finalize_failed_after_merge"
            if failure_stage == "finalize_after_merge"
            else exc.__class__.__name__
        )
        workspace_merge = _workspace_merge_outcome(
            attempted=merge_attempted,
            result=merge_result,
            error=merge_error,
            cleanup_ok=merge_cleanup_ok,
            cleanup_error=merge_cleanup_error,
        )
        outcome = build_subagent_outcome_json(
            stop_reason=None,
            tool_history=(),
            tool_calls_count=0,
            turns_count=0,
            summary=str(exc),
            task_status=SubagentTaskStatus.FAILED.value,
            task_id=task.task_id,
            run_id=run_id,
            agent_profile=task.agent_profile,
            write_scope_json=task.write_scope_json,
            error_message=str(exc),
            workspace_merge=workspace_merge,
            workspace_cleanup=_workspace_cleanup_outcome(
                ok=workspace_cleanup_ok,
                error=workspace_cleanup_error,
            ),
            failure={
                "type": failure_type,
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            },
        )
        recorded = self._task_port.record_failure(
            task_id=task.task_id,
            error_message=str(exc),
            outcome_json=outcome,
            delay_seconds=delay_seconds,
        )
        if recorded is not None:
            return recorded
        return self._task_port.mark_failed(
            task_id=task.task_id,
            error_message=str(exc),
            outcome_json=outcome,
        )

    def _record_task_cancelled(
        self,
        task: SubagentTaskRecord,
        *,
        run_id: str | None = None,
        workspace_cleanup_ok: bool | None = None,
        workspace_cleanup_error: Exception | None = None,
    ) -> SubagentTaskRecord | None:
        outcome = build_subagent_outcome_json(
            stop_reason=CoreErrorType.CANCELLED.value,
            tool_history=(),
            tool_calls_count=0,
            turns_count=0,
            summary="cancelled",
            task_status=SubagentTaskStatus.CANCELLED.value,
            task_id=task.task_id,
            run_id=run_id,
            agent_profile=task.agent_profile,
            write_scope_json=task.write_scope_json,
            error_message="cancelled",
            workspace_cleanup=_workspace_cleanup_outcome(
                ok=workspace_cleanup_ok,
                error=workspace_cleanup_error,
            ),
            failure={"type": "CancelledError", "message": "cancelled"},
        )
        return self._task_port.mark_cancelled(
            task_id=task.task_id,
            error_message="cancelled",
            outcome_json=outcome,
        )

    def _merge_workspace_if_needed(
        self,
        workspace: SubagentWorkspaceHandle | None,
        stop_reason: str | None,
        request: SubagentRunnerRequest,
    ) -> SubagentWorkspaceMergeResult | None:
        if not self._should_merge_workspace(workspace, stop_reason, request):
            return None
        assert workspace is not None
        return workspace.merge_back(cleanup=True)

    def _should_merge_workspace(
        self,
        workspace: SubagentWorkspaceHandle | None,
        stop_reason: str | None,
        request: SubagentRunnerRequest,
    ) -> bool:
        if workspace is None:
            return False
        needs_attention = needs_attention_for_stop_reason(stop_reason)
        return should_merge_subagent_workspace(
            will_queue_continuation=False,
            needs_attention=needs_attention,
            retryable_needs_attention=request.retryable_needs_attention,
        )


class SubagentBatchRunner:
    """Provisional sequential batch helper for aggregating subagent outcomes.

    Production hosts should prefer single-task workers around
    ``SubagentRunner.run_next()`` and implement lease, heartbeat, reclaim, and
    concurrency in the host queue.
    """

    def __init__(
        self,
        *,
        task_port: SubagentTaskPort,
        runner: SubagentRunner,
    ) -> None:
        self._task_port = task_port
        self._runner = runner

    async def run_batch(
        self,
        request: SubagentBatchRunnerRequest,
    ) -> SubagentBatchRunnerResult:
        tasks = tuple(
            self._task_port.claim_pending_batch(
                user_request_id=request.user_request_id,
                worker_id=request.worker_id,
                max_count=request.max_count,
                candidate_limit=request.candidate_limit,
                started_at_ms=request.started_at_ms,
            )
        )
        results: list[SubagentRunnerResult] = []
        errors: list[SubagentBatchRunnerError] = []

        for task in tasks:
            try:
                results.append(
                    await self._runner.run_claimed_task(
                        task,
                        request.runner_request,
                    )
                )
            except Exception as exc:
                errors.append(
                    SubagentBatchRunnerError(
                        task_id=task.task_id,
                        error_type=exc.__class__.__name__,
                        message=str(exc),
                    )
                )

        completed_tasks = tuple(
            self._task_port.load_task(task.task_id) or task for task in tasks
        )
        return SubagentBatchRunnerResult(
            claimed_tasks=tasks,
            results=tuple(results),
            completed_tasks=completed_tasks,
            aggregate_outcome=build_subagent_aggregate_outcome(completed_tasks),
            aggregate_text=format_subagent_aggregate(completed_tasks),
            errors=tuple(errors),
        )


def _workspace_merge_outcome(
    *,
    attempted: bool,
    result: SubagentWorkspaceMergeResult | None,
    error: Exception | None,
    cleanup_ok: bool | None = None,
    cleanup_error: Exception | None = None,
) -> dict[str, Any]:
    cleanup_error_json = (
        {
            "type": cleanup_error.__class__.__name__,
            "message": str(cleanup_error),
        }
        if cleanup_error is not None
        else None
    )
    if error is not None:
        return {
            "attempted": attempted,
            "ok": False,
            "changed_paths": [],
            "generation": None,
            "error": {
                "type": error.__class__.__name__,
                "message": str(error),
            },
            "cleanup_ok": cleanup_ok,
            "cleanup_error": cleanup_error_json,
        }
    if result is not None:
        return {
            "attempted": attempted,
            "ok": True,
            "changed_paths": list(result.merged_paths),
            "generation": result.generation,
            "error": None,
            "cleanup_ok": cleanup_ok,
            "cleanup_error": cleanup_error_json,
        }
    return {
        "attempted": attempted,
        "ok": None,
        "changed_paths": [],
        "generation": None,
        "error": None,
        "cleanup_ok": cleanup_ok,
        "cleanup_error": cleanup_error_json,
        "skipped_reason": None if attempted else "not_required",
    }


def _cleanup_workspace_after_failure(
    workspace: SubagentWorkspaceHandle | None,
) -> tuple[bool | None, Exception | None]:
    if workspace is None:
        return None, None
    try:
        workspace.cleanup()
        return True, None
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask run failure.
        return False, exc


def _workspace_cleanup_outcome(
    *,
    ok: bool | None,
    error: Exception | None,
) -> dict[str, Any]:
    return {
        "attempted": ok is not None or error is not None,
        "ok": ok,
        "error": (
            {
                "type": error.__class__.__name__,
                "message": str(error),
            }
            if error is not None
            else None
        ),
    }


def _workspace_merge_failure(error: Exception) -> dict[str, str]:
    return {
        "type": "workspace_merge_failed",
        "error_type": error.__class__.__name__,
        "message": str(error),
    }


def _tool_history_from_kernel_result(
    kernel_result: RunKernelResult,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for turn_result in kernel_result.turn_results:
        results_by_id = {
            result.tool_use_id: result
            for result in turn_result.tool_results
            if result.tool_use_id
        }
        tool_calls = [
            block for block in turn_result.content if isinstance(block, ToolUseBlock)
        ]
        for tool_call in tool_calls:
            result = results_by_id.get(tool_call.id)
            if result is None:
                history.append(
                    {
                        "tool_use_id": tool_call.id,
                        "tool_name": tool_call.name,
                        "tool_input": dict(tool_call.input),
                        "ok": False,
                        "error": {
                            "type": "tool_result_missing",
                            "message": f"Missing tool result for {tool_call.id}",
                        },
                        "duration_ms": None,
                    }
                )
                continue
            history.append(
                {
                    "tool_use_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "tool_input": dict(tool_call.input),
                    "ok": result.ok,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                }
            )
    return history
