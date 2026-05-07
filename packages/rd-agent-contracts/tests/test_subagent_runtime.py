from __future__ import annotations

from rd_agent_contracts import (
    SubagentFinalizeOperation,
    SubagentTaskRecord,
    adjusted_subagent_stop_reason_for_profile,
    build_subagent_instruction_text,
    build_subagent_outcome_json,
    build_subagent_run_record,
    build_subagent_task_payload,
    decide_subagent_finalization,
    extract_subagent_changed_paths,
    format_subagent_aggregate,
)


def test_subagent_instruction_text_includes_profile_scope_and_continuation():
    instruction = build_subagent_instruction_text(
        name="Frontend slice",
        description="Implement the UI",
        agent_profile="frontend_editor",
        write_scope_json={"paths": ["client/src"]},
        continuation_index=1,
    )

    assert "子任务名称: Frontend slice" in instruction
    assert "frontend_editor" in instruction
    assert "client/src" in instruction
    assert "续跑" in instruction


def test_subagent_outcome_schema_extracts_paths_validation_and_errors():
    outcome = build_subagent_outcome_json(
        stop_reason="loop_break:max_tool_calls",
        tool_history=[
            {
                "tool_name": "write_file",
                "tool_input": {"path": "client/src/App.tsx"},
                "tool_output": "ok",
                "ok": True,
            },
            {
                "tool_name": "browser_snapshot",
                "tool_input": {},
                "tool_output": "directory",
                "ok": False,
                "error": {"type": "is_directory", "code": "IS_DIRECTORY"},
                "duration_ms": 12,
            },
        ],
        tool_calls_count=2,
        turns_count=3,
        summary="stopped",
        task_status="failed",
        agent_profile="browser_verifier",
        write_scope_json={"paths": ["client"]},
        error_message="tool limit",
        failure={"type": "max_tool_calls_reached", "code": "MAX_TOOL_CALLS_REACHED"},
    )

    assert outcome["changed_paths"] == ["client/src/App.tsx"]
    assert outcome["validation"]["ok"] is False
    assert outcome["validation"]["tools"][0]["name"] == "browser_snapshot"
    assert outcome["error_type"] == "max_tool_calls_reached"
    assert outcome["tool_error_type"] == "is_directory"
    assert outcome["turns_count"] == 3


def test_subagent_finalize_decision_maps_runtime_states():
    waiting = decide_subagent_finalization(
        stop_reason="ask_user",
        queued_continuation=False,
        needs_attention=False,
        summary="need input",
        failure_message="unused",
        retryable_needs_attention=False,
    )
    assert waiting.operation == SubagentFinalizeOperation.MARK_WAITING
    assert waiting.task_status == "waiting_user"

    retry = decide_subagent_finalization(
        stop_reason="empty_response",
        queued_continuation=False,
        needs_attention=True,
        summary="empty",
        failure_message="provider returned empty response",
        retryable_needs_attention=True,
    )
    assert retry.operation == SubagentFinalizeOperation.RECORD_FAILURE
    assert retry.task_status == "failed"

    running = decide_subagent_finalization(
        stop_reason="loop_break:max_turns",
        queued_continuation=True,
        needs_attention=True,
        summary="continue",
        failure_message="turn limit",
        retryable_needs_attention=False,
    )
    assert running.operation == SubagentFinalizeOperation.MARK_RUNNING

    completed = decide_subagent_finalization(
        stop_reason="stop",
        queued_continuation=False,
        needs_attention=False,
        summary="done",
        failure_message="unused",
        retryable_needs_attention=False,
    )
    assert completed.operation == SubagentFinalizeOperation.MARK_COMPLETED
    assert completed.task_status == "completed"


def test_browser_verifier_requires_validation_tool_success():
    assert (
        adjusted_subagent_stop_reason_for_profile(
            agent_profile="browser_verifier",
            stop_reason="stop",
            tool_history=[],
            needs_attention=False,
        )
        == "verifier_tool_error"
    )
    assert (
        adjusted_subagent_stop_reason_for_profile(
            agent_profile="browser_verifier",
            stop_reason="stop",
            tool_history=[{"tool_name": "browser_snapshot", "ok": True}],
            needs_attention=False,
        )
        == "stop"
    )


def test_subagent_payload_and_aggregate_are_record_based():
    record = SubagentTaskRecord(
        task_id="task-1",
        user_request_id="req-1",
        project_id="proj-1",
        name="Verifier",
        description="Check UI",
        status="completed",
        result_summary="looks good",
        outcome_json={
            "summary": "validated",
            "changed_paths": ["client/src/App.tsx"],
            "validation": {"tools": [{"name": "browser_snapshot"}], "ok": True},
        },
    )

    payload = build_subagent_task_payload(record, error={"code": "IGNORED"})
    assert payload["id"] == "task-1"
    assert payload["error"] == {"code": "IGNORED"}

    aggregate = format_subagent_aggregate([record])
    assert aggregate.startswith("Subagent results:")
    assert "[completed] Verifier: validated" in aggregate
    assert "changed: client/src/App.tsx" in aggregate


def test_build_subagent_run_record_copies_task_context():
    task = SubagentTaskRecord(
        task_id="task-1",
        user_request_id="req-1",
        project_id="proj-1",
        name="Verifier",
        description="Check UI",
        status="running",
        parent_run_id="run-parent",
        correlation_id="corr-1",
    )

    record = build_subagent_run_record(task=task, run_id="run-child", session_id="session-1")

    assert record.task_id == "task-1"
    assert record.run_id == "run-child"
    assert record.user_request_id == "req-1"
    assert record.project_id == "proj-1"
    assert record.session_id == "session-1"
    assert record.parent_run_id == "run-parent"
    assert record.correlation_id == "corr-1"


def test_extract_subagent_changed_paths_accepts_objects():
    class Entry:
        tool_name = "apply_patch"
        tool_input = {"paths": ["a.py", "b.py"]}
        ok = True
        error = None
        duration_ms = None

    assert extract_subagent_changed_paths([Entry()]) == ["a.py", "b.py"]
