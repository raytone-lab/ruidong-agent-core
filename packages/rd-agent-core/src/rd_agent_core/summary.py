"""Run summary objects for metrics, tracing, and host projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from rd_agent_contracts import AgentEvent, StandardContentBlock, TextBlock, ToolCallCounts, Usage

from .run import RunKernelResult


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    stop_reason: str | None
    usage: Usage = field(default_factory=Usage)
    turns_count: int = 0
    tool_calls_count: int = 0
    tool_call_counts: ToolCallCounts = field(default_factory=ToolCallCounts)
    invalid_tool_calls_count: int = 0
    event_count: int = 0
    output_text: str = ""
    error_message: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.usage.total()


def summarize_kernel_result(
    *,
    run_id: str,
    status: str,
    kernel_result: RunKernelResult,
    events: Iterable[AgentEvent] | None = None,
    error_message: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RunSummary:
    materialized_events = tuple(events) if events is not None else kernel_result.events
    return RunSummary(
        run_id=run_id,
        status=status,
        stop_reason=kernel_result.stop_reason,
        usage=kernel_result.usage,
        turns_count=kernel_result.turns_count,
        tool_calls_count=kernel_result.tool_calls_count,
        tool_call_counts=kernel_result.tool_call_counts,
        invalid_tool_calls_count=sum(
            len(turn.invalid_tool_calls) for turn in kernel_result.turn_results
        ),
        event_count=len(materialized_events),
        output_text=_joined_text(kernel_result.turn_results[-1].content)
        if kernel_result.turn_results
        else "",
        error_message=error_message,
        metadata=dict(metadata or {}),
    )


def summarize_failed_run(
    *,
    run_id: str,
    error_message: str,
    status: str = "failed",
    stop_reason: str | None = None,
    events: Iterable[AgentEvent] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        status=status,
        stop_reason=stop_reason,
        event_count=len(tuple(events or ())),
        error_message=error_message,
        metadata=dict(metadata or {}),
    )


def _joined_text(content: Sequence[StandardContentBlock]) -> str:
    return "".join(block.text for block in content if isinstance(block, TextBlock))
