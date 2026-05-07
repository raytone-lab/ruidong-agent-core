from __future__ import annotations

from rd_agent_contracts import (
    SubagentProfileId,
    SubagentTaskPort,
    SubagentTaskRecord,
    SubagentTaskSpec,
    normalize_subagent_profile_id,
    normalize_write_scope_paths,
    resolve_subagent_profile,
    write_scopes_overlap,
)


def test_write_scope_normalization_and_overlap():
    assert normalize_write_scope_paths({"paths": ["./src", "src/", "", ".", "api\\v1"]}) == [
        "src",
        "api/v1",
    ]
    assert write_scopes_overlap(["src"], ["src/app"])
    assert not write_scopes_overlap(["src/frontend"], ["src/backend"])
    assert write_scopes_overlap([], ["src/backend"])


def test_profile_aliases_and_tool_policy():
    assert normalize_subagent_profile_id("frontend") == SubagentProfileId.FRONTEND_EDITOR.value
    assert normalize_subagent_profile_id("qa") == SubagentProfileId.BROWSER_VERIFIER.value
    assert normalize_subagent_profile_id("unknown") == SubagentProfileId.GENERAL.value

    planner = resolve_subagent_profile("planner")
    assert planner.allows_tool("read_file")
    assert not planner.allows_tool("write_file")

    browser = resolve_subagent_profile("browser")
    assert browser.allows_tool("browser_snapshot")
    assert not browser.allows_tool("write_file")


class _InMemorySubagentTasks:
    def __init__(self):
        self.records: dict[str, SubagentTaskRecord] = {}

    def create_task(
        self,
        spec: SubagentTaskSpec,
        *,
        task_id: str | None = None,
    ) -> SubagentTaskRecord:
        record = SubagentTaskRecord(
            task_id=task_id or "task-1",
            user_request_id=spec.user_request_id,
            project_id=spec.project_id,
            name=spec.name,
            description=spec.description,
            parent_run_id=spec.parent_run_id,
            agent_profile=spec.agent_profile,
            write_scope_json=spec.write_scope_json,
            depends_on_task_ids=spec.depends_on_task_ids,
            status="pending",
        )
        self.records[record.task_id] = record
        return record

    def list_tasks(self, *, user_request_id: str) -> list[SubagentTaskRecord]:
        return [item for item in self.records.values() if item.user_request_id == user_request_id]

    def load_task(self, task_id: str) -> SubagentTaskRecord | None:
        return self.records.get(task_id)

    def claim_next_pending(
        self,
        *,
        user_request_id: str | None = None,
        worker_id: str | None = None,
        started_at_ms: int | None = None,
        parent_completed_grace_seconds: float | None = None,
        skip_user_requests_with_running: bool = False,
    ) -> SubagentTaskRecord | None:
        for record in self.records.values():
            if record.status != "pending":
                continue
            if user_request_id is not None and record.user_request_id != user_request_id:
                continue
            updated = _replace_record(
                record,
                status="running",
                worker_id=worker_id,
                started_at_ms=started_at_ms,
                heartbeat_at_ms=started_at_ms,
            )
            self.records[record.task_id] = updated
            return updated
        return None

    def claim_pending_batch(
        self,
        *,
        user_request_id: str,
        worker_id: str | None = None,
        max_count: int = 1,
        candidate_limit: int | None = None,
        started_at_ms: int | None = None,
    ) -> list[SubagentTaskRecord]:
        claimed: list[SubagentTaskRecord] = []
        for _ in range(max_count):
            record = self.claim_next_pending(
                user_request_id=user_request_id,
                worker_id=worker_id,
                started_at_ms=started_at_ms,
            )
            if record is None:
                break
            claimed.append(record)
        return claimed

    def mark_attempt_started(self, *, task_id: str) -> SubagentTaskRecord | None:
        record = self.records.get(task_id)
        if record is None:
            return None
        updated = _replace_record(record, attempts=record.attempts + 1)
        self.records[task_id] = updated
        return updated

    def heartbeat(self, *, task_id: str, heartbeat_at_ms: int | None = None) -> None:
        record = self.records.get(task_id)
        if record is not None:
            self.records[task_id] = _replace_record(record, heartbeat_at_ms=heartbeat_at_ms)

    def release_for_retry(
        self,
        *,
        task_id: str,
        error_message: str,
        delay_seconds: int | None = None,
    ) -> SubagentTaskRecord | None:
        record = self.records.get(task_id)
        if record is None:
            return None
        updated = _replace_record(record, status="pending", error_message=error_message)
        self.records[task_id] = updated
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
        record = self.records.get(task_id)
        if record is None:
            return None
        updated = _replace_record(
            record,
            status="completed",
            result_summary=result_summary,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )
        self.records[task_id] = updated
        return updated

    def mark_failed(
        self,
        *,
        task_id: str,
        error_message: str,
        outcome_json: dict | None = None,
        completed_at_ms: int | None = None,
    ) -> SubagentTaskRecord | None:
        record = self.records.get(task_id)
        if record is None:
            return None
        updated = _replace_record(
            record,
            status="failed",
            error_message=error_message,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )
        self.records[task_id] = updated
        return updated

    def mark_waiting(
        self,
        *,
        task_id: str,
        result_summary: str | None = None,
        outcome_json: dict | None = None,
    ) -> SubagentTaskRecord | None:
        record = self.records.get(task_id)
        if record is None:
            return None
        updated = _replace_record(
            record,
            status="waiting_user",
            result_summary=result_summary,
            outcome_json=outcome_json,
        )
        self.records[task_id] = updated
        return updated

    def mark_running(self, *, task_id: str) -> SubagentTaskRecord | None:
        record = self.records.get(task_id)
        if record is None:
            return None
        updated = _replace_record(record, status="running")
        self.records[task_id] = updated
        return updated

    def record_failure(
        self,
        *,
        task_id: str,
        error_message: str,
        outcome_json: dict | None = None,
        delay_seconds: int | None = None,
        completed_at_ms: int | None = None,
    ) -> SubagentTaskRecord | None:
        return self.mark_failed(
            task_id=task_id,
            error_message=error_message,
            outcome_json=outcome_json,
            completed_at_ms=completed_at_ms,
        )


def _replace_record(record: SubagentTaskRecord, **changes) -> SubagentTaskRecord:
    payload = record.__dict__.copy()
    payload.update(changes)
    return SubagentTaskRecord(**payload)


def test_subagent_task_port_runtime_protocol():
    port: SubagentTaskPort = _InMemorySubagentTasks()  # type: ignore[assignment]
    assert isinstance(port, SubagentTaskPort)
    record = port.create_task(
        SubagentTaskSpec(
            user_request_id="req-1",
            project_id="proj-1",
            name="Frontend",
            description="Build UI",
            agent_profile="frontend_editor",
            depends_on_task_ids=["task-parent"],
        )
    )
    assert record.task_id == "task-1"
    assert record.depends_on_task_ids == ["task-parent"]
    assert port.load_task("task-1") == record

    completed = port.mark_completed(
        task_id="task-1",
        result_summary="done",
        outcome_json={"status": "completed"},
        completed_at_ms=123,
    )
    assert completed is not None
    assert completed.status == "completed"
    assert completed.outcome_json == {"status": "completed"}
