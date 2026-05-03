"""Model adapter primitives used by the AgentRunner LLM boundary."""

from .anthropic_native import AnthropicNativeAdapter, AnthropicNativeParserSession
from .anthropic_transport import AnthropicNativeTransport
from .capabilities import ModelCapabilities, ProtocolLimits, ThinkingExtractionConfig
from .events import (
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallEnd,
    ToolCallIdDelta,
    ToolCallNameDelta,
    ToolCallStart,
    TurnDone,
    UsageUpdate,
)
from .openai_compat import OpenAICompatAdapter, OpenAICompatParserSession
from .recorder import RecordedTurn, ReplayEvents, StreamRecorder
from .registry import (
    AdapterNotSupportedError,
    TransportNotSupportedError,
    resolve_adapter,
    resolve_adapter_for_profile,
    resolve_transport,
    resolve_transport_for_profile,
    supported_adapter_kinds,
    supported_transport_kinds,
)
from .transports import OpenAICompatTransport

__all__ = [
    "AdapterNotSupportedError",
    "AnthropicNativeAdapter",
    "AnthropicNativeParserSession",
    "AnthropicNativeTransport",
    "OpenAICompatAdapter",
    "OpenAICompatParserSession",
    "OpenAICompatTransport",
    "RecordedTurn",
    "ReplayEvents",
    "StreamRecorder",
    "TransportNotSupportedError",
    "resolve_adapter",
    "resolve_adapter_for_profile",
    "resolve_transport",
    "resolve_transport_for_profile",
    "supported_adapter_kinds",
    "supported_transport_kinds",
    "ModelCapabilities",
    "ProtocolLimits",
    "ReasoningDelta",
    "TextDelta",
    "ThinkingExtractionConfig",
    "ToolCallArgsDelta",
    "ToolCallEnd",
    "ToolCallIdDelta",
    "ToolCallNameDelta",
    "ToolCallStart",
    "TurnDone",
    "UsageUpdate",
]
