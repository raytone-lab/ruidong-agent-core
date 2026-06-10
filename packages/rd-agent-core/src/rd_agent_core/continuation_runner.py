"""Continuation orchestration over public run/queue ports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from rd_agent_contracts import (
    AgentEvent,
    CancellationToken,
    ContinuationJobRecord,
    ContinuationQueuePort,
    EventLogPort,
    IdGenerator,
    RunBudget,
    RunCompletion,
    RunFailure,
    RunPersistencePort,
    RunRecord,
    RunResultMetadata,
    RunStatus,
    ToolDefinition,
    ToolExecutionContext,
    ToolObservabilityPort,
    completion_status_for_stop_reason,
    should_auto_continue_run,
)

from .continuation_state import (
    ContinuationState,
    continuation_state_from_kernel_result,
)
from .events import CoreEventWriter
from .model_profile import ModelProfile
from .observability import RunObserverLike, notify_run_observer
from .policies import RunLimits
from .run import RunKernel, RunKernelResult, RunRequest
from .summary import RunSummary, summarize_failed_run, summarize_kernel_result
from .turn import CoreToolPolicy, LLMClientPort, ToolExecutorLike


@dataclass(frozen=True)
class ContinuationRunnerRequest:
    worker_id: str = "continuation-worker"
    budget: RunBudget | None = None
    limits: RunLimits | None = None
    tools: tuple[ToolDefinition, ...] = ()
    tool_context: ToolExecutionContext | None = None
    model: str | None = None
    model_profile: ModelProfile | None = None
    system_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken | None = None
    heartbeat_at_ms: int | None = None
    retry_available_at_ms: int | None = None


@dataclass(frozen=True)
class ContinuationRunnerResult:
    job: ContinuationJobRecord
    attempted_job: ContinuationJobRecord
    previous_run: RunRecord
    run: RunRecord
    completed_run: RunRecord
    completed_job: ContinuationJobRecord
    kernel_result: RunKernelResult
    events: tuple[AgentEvent, ...]
    summary: RunSummary


class ContinuationRunner:
    def __init__(
        self,
        *,
        continuation_queue: ContinuationQueuePort,
        run_persistence: RunPersistencePort,
        event_log: EventLogPort,
        llm_client: LLMClientPort,
        tool_executor: ToolExecutorLike | None = None,
        tool_observability: ToolObservabilityPort | None = None,
        tool_policy: CoreToolPolicy | None = None,
        run_observer: RunObserverLike | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._queue = continuation_queue
        self._run_persistence = run_persistence
        self._event_log = event_log
        self._llm_client = llm_client
        self._tool_executor = tool_executor
        self._tool_observability = tool_observability
        self._tool_policy = tool_policy
        self._run_observer = run_observer
        self._id_generator = id_generator

    async def run_next(
        self,
        request: ContinuationRunnerRequest | None = None,
    ) -> ContinuationRunnerResult | None:
        resolved = request or ContinuationRunnerRequest()
        job = self._queue.claim_next(worker_id=resolved.worker_id)
        if job is None:
            return None
        return await self.run_claimed_job(job, resolved)

    async def run_claimed_job(
        self,
        job: ContinuationJobRecord,
        request: ContinuationRunnerRequest | None = None,
    ) -> ContinuationRunnerResult:
        resolved = request or ContinuationRunnerRequest()
        attempted = self._queue.mark_attempt_started(
            job.job_id,
            heartbeat_at_ms=resolved.heartbeat_at_ms,
        ) or job
        previous = self._run_persistence.load_run(job.previous_run_id)
        if previous is None:
            completed_job = self._queue.complete_failure(
                job.job_id,
                error=f"previous run not found: {job.previous_run_id}",
                retry_available_at_ms=resolved.retry_available_at_ms,
            )
            raise RuntimeError(
                f"previous run not found: {job.previous_run_id}; job={completed_job}"
            )

        state = ContinuationState.from_json(previous.engine_state_json)
        run = self._ensure_continuation_run(
            job=job,
            previous=previous,
            state=state,
        )
        running = self._run_persistence.mark_running(run.run_id)
        if running is None:
            raise RuntimeError(f"continuation run cannot be marked running: {run.run_id}")

        try:
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
                    messages=state.messages,
                    tool_context=_resolve_tool_context(
                        request=resolved,
                        previous=previous,
                        run=run,
                    ),
                    tools=resolved.tools,
                    model=resolved.model,
                    model_profile=resolved.model_profile,
                    system_prompt=resolved.system_prompt,
                    limits=resolved.limits or _limits_from_budget(run.budget),
                    metadata=dict(resolved.metadata),
                    turn_offset=state.turn_offset,
                    cancellation_token=resolved.cancellation_token,
                )
            )
            events = tuple(self._event_log.stream_events(run.run_id))
            final_status = completion_status_for_stop_reason(
                stop_reason=kernel_result.stop_reason,
                can_auto_continue=should_auto_continue_run(
                    auto_continue_enabled=run.max_continuations > 0,
                    agent_kind=str(run.scope.agent_kind),
                    subagent_task_id=run.scope.subagent_task_id,
                    stop_reason=kernel_result.stop_reason,
                    continuation_index=run.continuation_index,
                    max_continuations=run.max_continuations,
                ),
            )
            completed_run = self._run_persistence.mark_completed(
                run.run_id,
                completion=RunCompletion(
                    stop_reason=kernel_result.stop_reason,
                    status=final_status,
                    metadata=RunResultMetadata(
                        usage=kernel_result.usage,
                        turns_count=kernel_result.turns_count,
                        tool_call_counts=kernel_result.tool_call_counts,
                        extra={"event_count": len(kernel_result.events)},
                    ),
                    engine_state_json=continuation_state_from_kernel_result(
                        messages=kernel_result.messages,
                        prior_turn_offset=state.turn_offset,
                        turns_count=kernel_result.turns_count,
                    ).to_json(),
                ),
            )
            if completed_run is None:
                raise RuntimeError(f"completed continuation run disappeared: {run.run_id}")
            completed_job = self._queue.complete_success(job.job_id)
            if completed_job is None:
                raise RuntimeError(f"completed continuation job disappeared: {job.job_id}")
            summary = summarize_kernel_result(
                run_id=run.run_id,
                status=str(completed_run.status),
                kernel_result=kernel_result,
                events=events,
            )
            await notify_run_observer(self._run_observer, summary)
            return ContinuationRunnerResult(
                job=job,
                attempted_job=attempted,
                previous_run=previous,
                run=run,
                completed_run=completed_run,
                completed_job=completed_job,
                kernel_result=kernel_result,
                events=events,
                summary=summary,
            )
        except asyncio.CancelledError:
            events = tuple(self._event_log.stream_events(run.run_id))
            self._run_persistence.mark_completed(
                run.run_id,
                completion=RunCompletion(
                    stop_reason="cancelled",
                    status=RunStatus.CANCELLED.value,
                    metadata=RunResultMetadata(),
                ),
            )
            self._queue.complete_failure(
                job.job_id,
                error="cancelled",
                retry_available_at_ms=resolved.retry_available_at_ms,
            )
            summary = summarize_failed_run(
                run_id=run.run_id,
                status=RunStatus.CANCELLED.value,
                stop_reason="cancelled",
                error_message="cancelled",
                events=events,
            )
            await notify_run_observer(self._run_observer, summary)
            raise
        except Exception as exc:
            events = tuple(self._event_log.stream_events(run.run_id))
            self._run_persistence.mark_failed(
                run.run_id,
                failure=RunFailure(error_message=str(exc)),
            )
            self._queue.complete_failure(
                job.job_id,
                error=str(exc),
                retry_available_at_ms=resolved.retry_available_at_ms,
            )
            summary = summarize_failed_run(
                run_id=run.run_id,
                error_message=str(exc),
                events=events,
            )
            await notify_run_observer(self._run_observer, summary)
            raise

    def _ensure_continuation_run(
        self,
        *,
        job: ContinuationJobRecord,
        previous: RunRecord,
        state: ContinuationState,
    ) -> RunRecord:
        existing = self._run_persistence.load_run(job.next_run_id)
        if existing is not None:
            return existing
        run = self._run_persistence.create_continuation_run(
            previous_run_id=previous.run_id,
            engine_state_json=state.to_json(),
            run_id=job.next_run_id,
        )
        if run is not None:
            return run
        raise RuntimeError(
            "continuation run could not be created: "
            f"previous_run_id={previous.run_id!r}, next_run_id={job.next_run_id!r}"
        )


def _resolve_tool_context(
    *,
    request: ContinuationRunnerRequest,
    previous: RunRecord,
    run: RunRecord,
) -> ToolExecutionContext:
    if request.tool_context is not None:
        return request.tool_context
    return ToolExecutionContext(
        project_id=previous.scope.project_id,
        correlation_id=previous.scope.correlation_id,
        session_id=previous.scope.session_id,
        user_request_id=previous.scope.user_request_id,
        agent_run_id=run.run_id,
        agent_kind=str(previous.scope.agent_kind),
        subagent_task_id=previous.scope.subagent_task_id,
    )


def _limits_from_budget(budget: RunBudget | None) -> RunLimits:
    if budget is None:
        return RunLimits()
    return RunLimits(
        max_turns=budget.max_turns,
        max_tool_calls=budget.max_tool_calls,
        timeout_ms=budget.max_wall_clock_s * 1000,
    )

