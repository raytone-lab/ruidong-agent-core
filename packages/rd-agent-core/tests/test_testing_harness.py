from __future__ import annotations

from rd_agent_contracts import ContinuationJobStatus
from rd_agent_core import CoreEventType
from rd_agent_core.testing import (
    HostHarness,
    InMemoryContinuationQueue,
    InMemoryEventLog,
    InMemoryRunPersistence,
    KernelHarness,
    RunnerHarness,
    Scenario,
    certification_scenarios,
)


async def test_runner_harness_runs_single_tool_scenario() -> None:
    result = await RunnerHarness().run(Scenario.single_tool())

    result.assert_run_status("completed").assert_stop_reason("end_turn")
    assert result.kernel_result.tool_call_counts.requested == 1
    assert result.kernel_result.tool_call_counts.executed == 1


async def test_kernel_harness_reports_invalid_tool_without_executor_call() -> None:
    result = await KernelHarness().run(Scenario.invalid_tool())

    result.assert_run_status("completed").assert_stop_reason("end_turn")
    assert result.kernel_result.turn_results[0].invalid_tool_calls[0].id == "tool-invalid"
    assert CoreEventType.TOOL_CALL_INVALID in [event.event_type for event in result.events]


async def test_runner_harness_maps_pause_and_cancellation_scenarios() -> None:
    pause = await RunnerHarness().run(Scenario.pause())
    cancelled = await RunnerHarness().run(Scenario.cancellation_before_start())

    pause.assert_run_status("waiting_user").assert_stop_reason("ask_user")
    cancelled.assert_run_status("cancelled").assert_stop_reason("cancelled")


async def test_host_harness_certifies_standard_scenarios() -> None:
    host = HostHarness(
        persistence=InMemoryRunPersistence(),
        event_log=InMemoryEventLog(),
        continuation_queue=InMemoryContinuationQueue(),
    )

    await host.assert_port_conformance()
    results = await host.certify(certification_scenarios())
    continuation = await host.certify_continuation()

    assert [result.kernel_result.stop_reason for result in results] == [
        "end_turn",
        "end_turn",
        "end_turn",
        "end_turn",
        "ask_user",
        "cancelled",
        "error",
    ]
    assert results[-1].completed.status == "needs_attention"
    assert continuation.completed_run.status == "completed"
    assert continuation.completed_job.status == ContinuationJobStatus.SUCCEEDED
    assert any(
        event.event_type == CoreEventType.TURN_STARTED
        and event.payload.get("turn_index") == 2
        for event in continuation.events
    )
