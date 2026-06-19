"""rd-agent-proto — protobuf bindings and Python contract converters."""

from .converters import (
    agent_event_from_proto,
    agent_event_to_proto,
    tool_definition_from_proto,
    tool_definition_to_proto,
    tool_execution_context_from_proto,
    tool_execution_context_to_proto,
    tool_execution_request_from_proto,
    tool_execution_request_to_proto,
    tool_execution_result_from_proto,
    tool_execution_result_to_proto,
    usage_from_proto,
    usage_to_proto,
)

__version__ = "0.1.0"

__all__ = [
    "agent_event_from_proto",
    "agent_event_to_proto",
    "tool_definition_from_proto",
    "tool_definition_to_proto",
    "tool_execution_context_from_proto",
    "tool_execution_context_to_proto",
    "tool_execution_request_from_proto",
    "tool_execution_request_to_proto",
    "tool_execution_result_from_proto",
    "tool_execution_result_to_proto",
    "usage_from_proto",
    "usage_to_proto",
]

