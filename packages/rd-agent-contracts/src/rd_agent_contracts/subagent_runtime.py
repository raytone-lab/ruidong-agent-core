"""Host-neutral subagent runtime helpers.

This module contains pure subagent orchestration logic that can be reused by a
host runtime without depending on its database, web framework, or event bus.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .subagent import (
    SubagentRunRecord,
    SubagentTaskRecord,
    SubagentTaskStatus,
    resolve_subagent_profile,
)

VERIFIER_VALIDATION_TOOLS = frozenset(
    {
        "run_command",
        "start_server",
        "browser_open_preview",
        "browser_snapshot",
        "browser_assert_text",
        "browser_console_logs",
        "browser_network_errors",
    }
)

MUTATING_TOOLS = frozenset(
    {
        "append_file",
        "write_file",
        "edit_file",
        "replace_range",
        "apply_patch",
        "delete_file",
        "move_file",
        "copy_file",
        "create_directory",
    }
)


class SubagentFinalizeOperation(StrEnum):
    MARK_COMPLETED = "mark_completed"
    MARK_FAILED = "mark_failed"
    MARK_RUNNING = "mark_running"
    MARK_WAITING = "mark_waiting"
    RECORD_FAILURE = "record_failure"


@dataclass(frozen=True)
class SubagentToolHistoryEntry:
    tool_name: str
    tool_input: Mapping[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: Mapping[str, Any] | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class SubagentFinalizeDecision:
    operation: SubagentFinalizeOperation
    task_status: str
    result_summary: str | None = None
    error_message: str | None = None


def build_subagent_instruction_text(
    *,
    name: str,
    description: str,
    agent_profile: str | None,
    write_scope_json: Mapping[str, Any] | None,
    continuation_index: int = 0,
) -> str:
    profile = resolve_subagent_profile(agent_profile)
    scope = ""
    if write_scope_json:
        scope = (
            "\n建议写入范围: "
            f"{json.dumps(dict(write_scope_json), ensure_ascii=False)}"
        )
    continuation_note = ""
    if continuation_index > 0:
        continuation_note = "\n这是该子任务的续跑，请基于已有上下文继续完成。"
    return (
        "你是一个子任务执行 agent。请只完成下面这个子任务，不要扩大范围。"
        f"\n子任务名称: {name}"
        f"\n子任务描述: {description}"
        f"\n专业 profile: {profile.profile_id} ({profile.label})"
        f"\nprofile 目标: {profile.purpose}"
        f"\nprofile 执行约束: {profile.system_guidance}"
        f"{scope}"
        f"{continuation_note}"
        "\n系统已根据 profile 限制可用工具。完成后用简短总结说明改动、验证和剩余风险。"
    )


def normalize_subagent_tool_history_entry(raw: Any) -> SubagentToolHistoryEntry:
    if isinstance(raw, SubagentToolHistoryEntry):
        return raw
    if isinstance(raw, Mapping):
        raw_input = raw.get("tool_input") or raw.get("input") or {}
        raw_error = raw.get("error")
        return SubagentToolHistoryEntry(
            tool_name=str(raw.get("tool_name") or raw.get("name") or ""),
            tool_input=raw_input if isinstance(raw_input, Mapping) else {},
            ok=bool(raw.get("ok", True)),
            error=raw_error if isinstance(raw_error, Mapping) else None,
            duration_ms=_coerce_int(raw.get("duration_ms")),
        )
    raw_input = getattr(raw, "tool_input", {}) or {}
    raw_error = getattr(raw, "error", None)
    return SubagentToolHistoryEntry(
        tool_name=str(getattr(raw, "tool_name", "") or ""),
        tool_input=raw_input if isinstance(raw_input, Mapping) else {},
        ok=bool(getattr(raw, "ok", True)),
        error=raw_error if isinstance(raw_error, Mapping) else None,
        duration_ms=_coerce_int(getattr(raw, "duration_ms", None)),
    )


def normalize_subagent_tool_history(
    tool_history: Iterable[Any],
) -> list[SubagentToolHistoryEntry]:
    return [
        item
        for item in (normalize_subagent_tool_history_entry(raw) for raw in tool_history)
        if item.tool_name
    ]


def extract_subagent_changed_paths(tool_history: Iterable[Any]) -> list[str]:
    paths: set[str] = set()
    for entry in normalize_subagent_tool_history(tool_history):
        if not entry.ok or entry.tool_name not in MUTATING_TOOLS:
            continue
        for key in (
            "path",
            "file_path",
            "target_path",
            "source_path",
            "dest_path",
            "destination_path",
        ):
            value = entry.tool_input.get(key)
            if isinstance(value, str) and value.strip():
                paths.add(value.strip())
        raw_paths = entry.tool_input.get("paths")
        if isinstance(raw_paths, list):
            paths.update(str(path).strip() for path in raw_paths if str(path).strip())
    return sorted(paths)


def build_subagent_outcome_json(
    *,
    stop_reason: str | None,
    tool_history: Iterable[Any],
    tool_calls_count: int,
    turns_count: int,
    summary: str,
    task_status: str,
    agent_profile: str | None = None,
    write_scope_json: Mapping[str, Any] | None = None,
    error_message: str | None = None,
    failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entries = normalize_subagent_tool_history(tool_history)
    validation_entries = [
        entry
        for entry in entries
        if entry.tool_name in VERIFIER_VALIDATION_TOOLS
        or entry.tool_name.startswith("run_")
    ]
    failed_entries = [entry for entry in entries if not entry.ok]
    return {
        "schema_version": "1.0",
        "status": task_status,
        "summary": summary[:4000],
        "stop_reason": stop_reason,
        "agent_profile": agent_profile,
        "write_scope": dict(write_scope_json) if write_scope_json else None,
        "changed_paths": extract_subagent_changed_paths(entries),
        "validation": {
            "tools": [
                {
                    "name": entry.tool_name,
                    "ok": entry.ok,
                    "duration_ms": entry.duration_ms,
                }
                for entry in validation_entries
            ],
            "ok": (
                all(entry.ok for entry in validation_entries)
                if validation_entries
                else None
            ),
        },
        "risks": [],
        "artifacts": [],
        "error": dict(failure) if failure else None,
        "error_type": _failure_error_type(failure),
        "tool_error_type": first_failed_tool_error_type(failed_entries),
        "error_message": error_message[:1000] if error_message else None,
        "tool_calls_count": tool_calls_count,
        "turns_count": turns_count,
    }


def first_failed_tool_error_type(tool_history: Iterable[Any]) -> str | None:
    for entry in normalize_subagent_tool_history(tool_history):
        if entry.ok or not entry.error:
            continue
        error_type = entry.error.get("type") or entry.error.get("code")
        if error_type:
            return str(error_type)
    return None


def adjusted_subagent_stop_reason_for_profile(
    *,
    agent_profile: str | None,
    stop_reason: str | None,
    tool_history: Iterable[Any],
    needs_attention: bool,
) -> str | None:
    if agent_profile != "browser_verifier" or needs_attention:
        return stop_reason
    validation_entries = [
        entry
        for entry in normalize_subagent_tool_history(tool_history)
        if entry.tool_name in VERIFIER_VALIDATION_TOOLS
    ]
    if not validation_entries or not any(entry.ok for entry in validation_entries):
        return "verifier_tool_error"
    return stop_reason


def decide_subagent_finalization(
    *,
    stop_reason: str | None,
    queued_continuation: bool,
    needs_attention: bool,
    summary: str,
    failure_message: str,
    retryable_needs_attention: bool,
) -> SubagentFinalizeDecision:
    if stop_reason == "ask_user":
        return SubagentFinalizeDecision(
            operation=SubagentFinalizeOperation.MARK_WAITING,
            task_status=SubagentTaskStatus.WAITING_USER.value,
            result_summary=summary,
        )
    if queued_continuation:
        return SubagentFinalizeDecision(
            operation=SubagentFinalizeOperation.MARK_RUNNING,
            task_status=SubagentTaskStatus.RUNNING.value,
        )
    if needs_attention:
        return SubagentFinalizeDecision(
            operation=(
                SubagentFinalizeOperation.RECORD_FAILURE
                if retryable_needs_attention
                else SubagentFinalizeOperation.MARK_FAILED
            ),
            task_status=SubagentTaskStatus.FAILED.value,
            error_message=failure_message,
        )
    return SubagentFinalizeDecision(
        operation=SubagentFinalizeOperation.MARK_COMPLETED,
        task_status=SubagentTaskStatus.COMPLETED.value,
        result_summary=summary,
    )


def build_subagent_task_payload(
    record: SubagentTaskRecord,
    *,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": record.task_id,
        "name": record.name,
        "description": record.description,
        "agent_profile": record.agent_profile,
        "status": record.status,
        "attempts": record.attempts,
        "max_attempts": record.max_attempts,
        "write_scope": record.write_scope_json,
        "depends_on_task_ids": record.depends_on_task_ids,
        "result_summary": record.result_summary,
        "outcome_json": record.outcome_json,
        "error_message": record.error_message,
        "error": dict(error) if error else None,
        "parent_run_id": record.parent_run_id,
    }


def build_subagent_run_record(
    *,
    task: SubagentTaskRecord,
    run_id: str,
    session_id: str | None = None,
) -> SubagentRunRecord:
    return SubagentRunRecord(
        task_id=task.task_id,
        run_id=run_id,
        user_request_id=task.user_request_id,
        project_id=task.project_id,
        session_id=session_id,
        parent_run_id=task.parent_run_id,
        correlation_id=task.correlation_id,
    )


def format_subagent_aggregate(records: Iterable[SubagentTaskRecord]) -> str:
    items = list(records)
    if not items:
        return ""
    lines = ["Subagent results:"]
    for index, record in enumerate(items, start=1):
        outcome = record.outcome_json if isinstance(record.outcome_json, dict) else {}
        summary = (
            outcome.get("summary")
            or record.result_summary
            or record.error_message
            or "No summary"
        )
        summary = " ".join(str(summary).split())
        if len(summary) > 500:
            summary = summary[:500] + "..."
        changed_paths = outcome.get("changed_paths")
        validation = outcome.get("validation")
        detail_parts: list[str] = []
        if isinstance(changed_paths, list) and changed_paths:
            detail_parts.append(
                "changed: " + ", ".join(str(path) for path in changed_paths[:8])
            )
        if isinstance(validation, dict) and validation.get("tools"):
            detail_parts.append(
                "validation: " + ("passed" if validation.get("ok") else "failed")
            )
        detail = f" ({'; '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"{index}. [{record.status}] {record.name}: {summary}{detail}")
    return "\n".join(lines)


def _failure_error_type(failure: Mapping[str, Any] | None) -> str | None:
    if not failure:
        return None
    error_type = failure.get("type") or failure.get("code")
    return str(error_type) if error_type else None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
