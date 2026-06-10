"""Host-neutral tool registry, execution, and observability contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    mutates_workspace: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionContext:
    project_id: str
    tenant_id: str | None = None
    lease_id: str | None = None
    correlation_id: str | None = None
    session_id: str | None = None
    user_request_id: str | None = None
    agent_run_id: str | None = None
    agent_kind: str = "orchestrator"
    subagent_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionRequest:
    tool_name: str
    tool_input: dict[str, Any]
    context: ToolExecutionContext
    tool_use_id: str | None = None
    turn: int = 0


@dataclass(frozen=True)
class ToolCallCounts:
    requested: int = 0
    executed: int = 0
    denied: int = 0

    def __post_init__(self) -> None:
        for field_name in ("requested", "executed", "denied"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be >= 0")

    def to_json(self) -> dict[str, int]:
        return {
            "requested": self.requested,
            "executed": self.executed,
            "denied": self.denied,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> ToolCallCounts:
        if raw is None:
            return cls()
        return cls(
            requested=int(raw.get("requested", 0) or 0),
            executed=int(raw.get("executed", 0) or 0),
            denied=int(raw.get("denied", 0) or 0),
        )


@dataclass(frozen=True)
class ToolExecutionResult:
    ok: bool
    content: str
    tool_use_id: str
    error: dict[str, Any] | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolObservabilityRecord:
    project_id: str
    session_id: str | None
    tool_name: str
    tool_input: Mapping[str, Any]
    tool_output: str
    ok: bool
    correlation_id: str | None = None
    error: dict[str, Any] | None = None
    duration_ms: int | None = None
    tool_use_id: str | None = None
    turn: int = 0


@runtime_checkable
class ToolRegistryPort(Protocol):
    def list_tools(self, *, context: ToolExecutionContext) -> list[ToolDefinition]: ...


@runtime_checkable
class ToolExecutorPort(Protocol):
    def execute_tool(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


@runtime_checkable
class ToolObservabilityPort(Protocol):
    def record_tool_calls(self, records: list[ToolObservabilityRecord]) -> None: ...
