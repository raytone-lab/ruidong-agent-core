"""Serializable continuation state shared by runners."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from rd_agent_contracts import Message, ToolCall, ToolCallStatus, ToolResult


@dataclass(frozen=True)
class ContinuationState:
    messages: tuple[Message, ...]
    turn_offset: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "messages": [asdict(message) for message in self.messages],
                "turn_offset": self.turn_offset,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> ContinuationState:
        if not raw:
            return cls(messages=(), turn_offset=0)
        payload = json.loads(raw)
        messages = tuple(_message_from_json(item) for item in payload.get("messages", ()))
        return cls(
            messages=messages,
            turn_offset=int(payload.get("turn_offset", 0) or 0),
        )


def continuation_state_from_kernel_result(
    *,
    messages: tuple[Message, ...],
    prior_turn_offset: int = 0,
    turns_count: int,
) -> ContinuationState:
    return ContinuationState(
        messages=messages,
        turn_offset=prior_turn_offset + turns_count,
    )


def _message_from_json(raw: dict[str, Any]) -> Message:
    return Message(
        message_id=str(raw["message_id"]),
        role=raw["role"],
        content=raw["content"],
        turn_id=str(raw["turn_id"]),
        tool_calls=[
            ToolCall(
                tool_use_id=str(item["tool_use_id"]),
                tool_name=str(item["tool_name"]),
                input=dict(item.get("input") or {}),
                status=ToolCallStatus(str(item["status"])),
            )
            for item in raw.get("tool_calls", ())
        ],
        tool_results=[
            ToolResult(
                tool_use_id=str(item["tool_use_id"]),
                ok=bool(item["ok"]),
                content=str(item.get("content") or ""),
                error=item.get("error"),
            )
            for item in raw.get("tool_results", ())
        ],
    )
