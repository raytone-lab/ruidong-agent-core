from __future__ import annotations

from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from rd_agent_contracts import (
    AgentEvent,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    Usage,
)
from ruidong.agent.v1 import events_pb2, runtime_pb2, transcript_pb2


def agent_event_to_proto(event: AgentEvent) -> events_pb2.AgentEvent:
    message = events_pb2.AgentEvent(
        seq=event.seq,
        timestamp_ms=event.timestamp_ms,
        run_id=event.run_id,
        turn_id=event.turn_id,
        event_type=event.event_type,
        payload=_struct_from_dict(event.payload),
        schema_version=event.schema_version,
    )
    if event.message_id is not None:
        message.message_id = event.message_id
    if event.action_id is not None:
        message.action_id = event.action_id
    return message


def agent_event_from_proto(message: events_pb2.AgentEvent) -> AgentEvent:
    return AgentEvent(
        seq=message.seq,
        timestamp_ms=message.timestamp_ms,
        run_id=message.run_id,
        turn_id=message.turn_id,
        event_type=message.event_type,
        payload=_dict_from_struct(message.payload),
        schema_version=message.schema_version,
        message_id=message.message_id if message.HasField("message_id") else None,
        action_id=message.action_id if message.HasField("action_id") else None,
    )


def usage_to_proto(usage: Usage) -> transcript_pb2.Usage:
    return transcript_pb2.Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
    )


def usage_from_proto(message: transcript_pb2.Usage) -> Usage:
    return Usage(
        input_tokens=message.input_tokens,
        output_tokens=message.output_tokens,
        cache_creation_input_tokens=message.cache_creation_input_tokens,
        cache_read_input_tokens=message.cache_read_input_tokens,
    )


def tool_definition_to_proto(tool: ToolDefinition) -> runtime_pb2.ToolDefinition:
    return runtime_pb2.ToolDefinition(
        name=tool.name,
        description=tool.description,
        input_schema=_struct_from_dict(tool.input_schema),
        mutates_workspace=tool.mutates_workspace,
        metadata=_struct_from_dict(tool.metadata),
    )


def tool_definition_from_proto(message: runtime_pb2.ToolDefinition) -> ToolDefinition:
    return ToolDefinition(
        name=message.name,
        description=message.description,
        input_schema=_dict_from_struct(message.input_schema),
        mutates_workspace=message.mutates_workspace,
        metadata=_dict_from_struct(message.metadata),
    )


def tool_execution_context_to_proto(
    context: ToolExecutionContext,
) -> runtime_pb2.ToolExecutionContext:
    message = runtime_pb2.ToolExecutionContext(
        project_id=context.project_id,
        agent_kind=context.agent_kind,
        metadata=_struct_from_dict(context.metadata),
    )
    for field_name in (
        "tenant_id",
        "lease_id",
        "correlation_id",
        "session_id",
        "user_request_id",
        "agent_run_id",
        "subagent_task_id",
    ):
        value = getattr(context, field_name)
        if value is not None:
            setattr(message, field_name, value)
    return message


def tool_execution_context_from_proto(
    message: runtime_pb2.ToolExecutionContext,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        project_id=message.project_id,
        tenant_id=_optional_string(message, "tenant_id"),
        lease_id=_optional_string(message, "lease_id"),
        correlation_id=_optional_string(message, "correlation_id"),
        session_id=_optional_string(message, "session_id"),
        user_request_id=_optional_string(message, "user_request_id"),
        agent_run_id=_optional_string(message, "agent_run_id"),
        agent_kind=message.agent_kind or "orchestrator",
        subagent_task_id=_optional_string(message, "subagent_task_id"),
        metadata=_dict_from_struct(message.metadata),
    )


def tool_execution_request_to_proto(
    request: ToolExecutionRequest,
) -> runtime_pb2.ToolExecutionRequest:
    message = runtime_pb2.ToolExecutionRequest(
        tool_name=request.tool_name,
        tool_input=_struct_from_dict(request.tool_input),
        context=tool_execution_context_to_proto(request.context),
        turn=request.turn,
    )
    if request.tool_use_id is not None:
        message.tool_use_id = request.tool_use_id
    return message


def tool_execution_request_from_proto(
    message: runtime_pb2.ToolExecutionRequest,
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_name=message.tool_name,
        tool_input=_dict_from_struct(message.tool_input),
        context=tool_execution_context_from_proto(message.context),
        tool_use_id=_optional_string(message, "tool_use_id"),
        turn=message.turn,
    )


def tool_execution_result_to_proto(
    result: ToolExecutionResult,
) -> runtime_pb2.ToolExecutionResult:
    message = runtime_pb2.ToolExecutionResult(
        ok=result.ok,
        content=result.content,
        tool_use_id=result.tool_use_id,
        metadata=_struct_from_dict(result.metadata),
    )
    if result.error is not None:
        message.error.CopyFrom(_struct_from_dict(result.error))
    if result.duration_ms is not None:
        message.duration_ms = result.duration_ms
    return message


def tool_execution_result_from_proto(
    message: runtime_pb2.ToolExecutionResult,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        ok=message.ok,
        content=message.content,
        tool_use_id=message.tool_use_id,
        error=_dict_from_struct(message.error) if message.HasField("error") else None,
        duration_ms=message.duration_ms if message.HasField("duration_ms") else None,
        metadata=_dict_from_struct(message.metadata),
    )


def _struct_from_dict(value: dict[str, Any] | None) -> Struct:
    struct = Struct()
    ParseDict(value or {}, struct)
    return struct


def _dict_from_struct(value: Struct) -> dict[str, Any]:
    return MessageToDict(value, preserving_proto_field_name=True)


def _optional_string(message: Any, field_name: str) -> str | None:
    return getattr(message, field_name) if message.HasField(field_name) else None

