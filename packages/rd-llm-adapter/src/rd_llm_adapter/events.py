from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextDelta:
    text: str
    block_index: int = 0


@dataclass(frozen=True)
class ReasoningDelta:
    text: str
    block_index: int = 0
    provider_data: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCallStart:
    index: int
    call_id: str | None = None
    name: str | None = None
    encoding_hint: str | None = None


@dataclass(frozen=True)
class ToolCallIdDelta:
    index: int
    call_id: str


@dataclass(frozen=True)
class ToolCallNameDelta:
    index: int
    name_delta: str
    call_id: str | None = None


@dataclass(frozen=True)
class ToolCallArgsDelta:
    index: int
    delta: str
    call_id: str | None = None


@dataclass(frozen=True)
class ToolCallEnd:
    call_id: str
    name: str
    index: int
    encoding: str
    raw_args: str
    parsed_input: dict[str, Any] | None
    parse_error: str | None


@dataclass(frozen=True)
class UsageUpdate:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        total = self.total_tokens or (self.input_tokens + self.output_tokens)
        payload = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": total,
        }
        if self.cached_input_tokens:
            payload["cached_input_tokens"] = self.cached_input_tokens
        if self.reasoning_tokens:
            payload["reasoning_tokens"] = self.reasoning_tokens
        return payload


@dataclass(frozen=True)
class TurnDone:
    stop_reason: str
    content: list[Any]
    text_blocks: list[Any]
    reasoning_blocks: list[Any]
    tool_calls: list[Any]
    invalid_tool_calls: list[Any]
    sources: list[Any] = field(default_factory=list)
    usage: UsageUpdate | None = None
    provider_state: Any | None = None
    raw_stop_reason: str = ""


StandardEvent = (
    TextDelta
    | ReasoningDelta
    | ToolCallStart
    | ToolCallIdDelta
    | ToolCallNameDelta
    | ToolCallArgsDelta
    | ToolCallEnd
    | UsageUpdate
    | TurnDone
)
