from __future__ import annotations

from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from rd_agent_contracts import (
    AgentEvent,
    Message,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolResult,
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


def message_to_proto(message: Message) -> transcript_pb2.Message:
    proto = transcript_pb2.Message(
        message_id=message.message_id,
        role=message.role,
        turn_id=message.turn_id,
    )
    if isinstance(message.content, str):
        proto.content_text = message.content
    else:
        proto.content_blocks.extend(
            _content_block_to_proto(block) for block in message.content
        )
    proto.tool_calls.extend(_tool_call_to_proto(call) for call in message.tool_calls)
    proto.tool_results.extend(
        _tool_result_to_proto(result) for result in message.tool_results
    )
    return proto


def message_from_proto(proto: transcript_pb2.Message) -> Message:
    content: str | list[dict[str, Any]]
    if proto.content_blocks:
        content = [_content_block_from_proto(block) for block in proto.content_blocks]
    else:
        content = proto.content_text
    return Message(
        message_id=proto.message_id,
        role=proto.role,
        content=content,
        turn_id=proto.turn_id,
        tool_calls=[_tool_call_from_proto(call) for call in proto.tool_calls],
        tool_results=[_tool_result_from_proto(result) for result in proto.tool_results],
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


def _content_block_to_proto(block: dict[str, Any]) -> transcript_pb2.ContentBlock:
    block_type = block.get("type")
    proto = transcript_pb2.ContentBlock()
    if block_type == "text":
        proto.text.text = str(block.get("text") or "")
        provider_data = block.get("provider_data")
        if isinstance(provider_data, dict):
            proto.text.provider_data.CopyFrom(_struct_from_dict(provider_data))
        return proto
    if block_type == "reasoning":
        proto.reasoning.text = str(block.get("text") or "")
        if block.get("signature") is not None:
            proto.reasoning.signature = str(block["signature"])
        proto.reasoning.redacted = bool(block.get("redacted", False))
        if block.get("data") is not None:
            proto.reasoning.data = str(block["data"])
        provider_data = block.get("provider_data")
        if isinstance(provider_data, dict):
            proto.reasoning.provider_data.CopyFrom(_struct_from_dict(provider_data))
        return proto
    if block_type == "tool_use":
        proto.tool_use.id = str(block.get("id") or "")
        proto.tool_use.name = str(block.get("name") or "")
        proto.tool_use.input.CopyFrom(_struct_from_dict(block.get("input") or {}))
        return proto
    if block_type == "invalid_tool_call":
        proto.invalid_tool_call.id = str(block.get("id") or "")
        proto.invalid_tool_call.name = str(block.get("name") or "")
        proto.invalid_tool_call.raw_args = str(block.get("raw_args") or "")
        proto.invalid_tool_call.parse_error = str(block.get("parse_error") or "")
        proto.invalid_tool_call.index = int(block.get("index", 0) or 0)
        if block.get("encoding") is not None:
            proto.invalid_tool_call.encoding = str(block["encoding"])
        return proto
    raise ValueError(f"unsupported content block type: {block_type!r}")


def _content_block_from_proto(proto: transcript_pb2.ContentBlock) -> dict[str, Any]:
    block_type = proto.WhichOneof("block")
    if block_type == "text":
        block = {"type": "text", "text": proto.text.text}
        if proto.text.HasField("provider_data"):
            block["provider_data"] = _dict_from_struct(proto.text.provider_data)
        return block
    if block_type == "reasoning":
        block: dict[str, Any] = {
            "type": "reasoning",
            "text": proto.reasoning.text,
            "redacted": proto.reasoning.redacted,
        }
        if proto.reasoning.HasField("signature"):
            block["signature"] = proto.reasoning.signature
        if proto.reasoning.HasField("data"):
            block["data"] = proto.reasoning.data
        if proto.reasoning.HasField("provider_data"):
            block["provider_data"] = _dict_from_struct(proto.reasoning.provider_data)
        return block
    if block_type == "tool_use":
        return {
            "type": "tool_use",
            "id": proto.tool_use.id,
            "name": proto.tool_use.name,
            "input": _dict_from_struct(proto.tool_use.input),
        }
    if block_type == "invalid_tool_call":
        block = {
            "type": "invalid_tool_call",
            "id": proto.invalid_tool_call.id,
            "name": proto.invalid_tool_call.name,
            "raw_args": proto.invalid_tool_call.raw_args,
            "parse_error": proto.invalid_tool_call.parse_error,
            "index": proto.invalid_tool_call.index,
        }
        if proto.invalid_tool_call.HasField("encoding"):
            block["encoding"] = proto.invalid_tool_call.encoding
        return block
    raise ValueError("content block oneof is not set")


def _tool_call_to_proto(call: ToolCall) -> transcript_pb2.ToolCall:
    return transcript_pb2.ToolCall(
        tool_use_id=call.tool_use_id,
        tool_name=call.tool_name,
        input=_struct_from_dict(call.input),
        status=str(call.status),
    )


def _tool_call_from_proto(proto: transcript_pb2.ToolCall) -> ToolCall:
    return ToolCall(
        tool_use_id=proto.tool_use_id,
        tool_name=proto.tool_name,
        input=_dict_from_struct(proto.input),
        status=ToolCallStatus(proto.status),
    )


def _tool_result_to_proto(result: ToolResult) -> transcript_pb2.ToolResult:
    proto = transcript_pb2.ToolResult(
        tool_use_id=result.tool_use_id,
        ok=result.ok,
        content=result.content,
    )
    if result.error is not None:
        proto.error.CopyFrom(_struct_from_dict(result.error))
    return proto


def _tool_result_from_proto(proto: transcript_pb2.ToolResult) -> ToolResult:
    return ToolResult(
        tool_use_id=proto.tool_use_id,
        ok=proto.ok,
        content=proto.content,
        error=_dict_from_struct(proto.error) if proto.HasField("error") else None,
    )


def _dict_from_struct(value: Struct) -> dict[str, Any]:
    return _restore_json_ints(
        MessageToDict(value, preserving_proto_field_name=True)
    )


def _restore_json_ints(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _restore_json_ints(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore_json_ints(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _optional_string(message: Any, field_name: str) -> str | None:
    return getattr(message, field_name) if message.HasField(field_name) else None
