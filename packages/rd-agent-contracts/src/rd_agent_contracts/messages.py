"""Message / ToolCall / ToolResult — transcript 的基本单元。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .enums import ToolCallStatus

Role = Literal["user", "assistant", "system", "tool"]
_VALID_ROLES = {"user", "assistant", "system", "tool"}


@dataclass(frozen=True)
class Message:
    """对话历史中的一条消息。

    content 可以是 str（纯文本）或 list[dict]（多 block，对齐 Anthropic content blocks）。
    """

    message_id: str
    role: Role
    content: str | list[dict[str, Any]]
    turn_id: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.role not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}, got {self.role!r}")


@dataclass(frozen=True)
class ToolCall:
    """LLM 发起的工具调用。

    status 是契约硬约束：P5 engine 仅执行 COMPLETE，PARTIAL/INVALID 永不执行。
    """

    tool_use_id: str
    tool_name: str
    input: dict[str, Any]
    status: ToolCallStatus


@dataclass(frozen=True)
class ToolResult:
    """工具执行结果。tool_use_id 必须配对某个 ToolCall.tool_use_id。

    content 永远是 str。大输出场景由 core executor middleware 将 BlobRef
    放在 ToolExecutionResult.metadata["blob_ref"] 和对应事件 payload 中；
    transcript 中只保留 inline 内容或 inline 前缀。
    """

    tool_use_id: str
    ok: bool
    content: str
    error: dict[str, Any] | None = None
