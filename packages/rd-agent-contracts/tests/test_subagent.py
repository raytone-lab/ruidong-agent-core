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


def test_subagent_task_port_runtime_protocol():
    port: SubagentTaskPort = _InMemorySubagentTasks()  # type: ignore[assignment]
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
