from __future__ import annotations

from rd_agent_contracts import (
    AgentEvent,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    Usage,
)
from rd_agent_proto import (
    agent_event_from_proto,
    agent_event_to_proto,
    tool_definition_from_proto,
    tool_definition_to_proto,
    tool_execution_request_from_proto,
    tool_execution_request_to_proto,
    tool_execution_result_from_proto,
    tool_execution_result_to_proto,
    usage_from_proto,
    usage_to_proto,
)


def test_agent_event_proto_roundtrip() -> None:
    event = AgentEvent(
        seq=1,
        timestamp_ms=1710000000000,
        run_id="run-1",
        turn_id="turn-1",
        event_type="tool_call_completed",
        payload={
            "call_id": "call-1",
            "name": "read_file",
            "index": 0,
            "parsed_input": {"path": "README.md"},
        },
        message_id="msg-1",
        action_id="act-1",
    )

    assert agent_event_from_proto(agent_event_to_proto(event)) == event


def test_usage_proto_roundtrip() -> None:
    usage = Usage(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=2,
        cache_read_input_tokens=3,
    )

    assert usage_from_proto(usage_to_proto(usage)) == usage


def test_tool_contract_proto_roundtrip() -> None:
    definition = ToolDefinition(
        name="read_file",
        description="Read a file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        mutates_workspace=False,
        metadata={"profile": "read_only"},
    )
    request = ToolExecutionRequest(
        tool_name="read_file",
        tool_input={"path": "README.md"},
        context=ToolExecutionContext(
            project_id="project-1",
            tenant_id="tenant-1",
            correlation_id="corr-1",
            session_id="session-1",
            agent_kind="orchestrator",
            metadata={"source": "test"},
        ),
        tool_use_id="tool-1",
        turn=2,
    )
    result = ToolExecutionResult(
        ok=True,
        content="ok",
        tool_use_id="tool-1",
        duration_ms=7,
        metadata={"executed": True},
    )

    assert tool_definition_from_proto(tool_definition_to_proto(definition)) == definition
    assert tool_execution_request_from_proto(tool_execution_request_to_proto(request)) == request
    assert tool_execution_result_from_proto(tool_execution_result_to_proto(result)) == result

