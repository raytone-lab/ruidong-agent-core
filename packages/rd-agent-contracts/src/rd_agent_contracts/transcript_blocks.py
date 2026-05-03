"""Typed transcript content blocks（contracts 1.1 新增）。

参考 codesphere-saas/app/services/agent_runner/model_adapter/messages.py
和 MODEL-ADAPTER.md spec §4.2。

使用方：
- rd-llm-adapter 的 TurnDone.content 用这些类型
- rd-agent-core engine 的 transcript invariants 用这些类型
- saas-adapter 持久化时 byte-equal 保留 ReasoningBlock.signature / .data

ReasoningBlock 是 Anthropic native thinking 的 first-class 表达：
- 普通 thinking：text + signature + block_index
- redacted_thinking：data（加密 blob）+ redacted=True

ProviderState 是 unstructured dict，让 adapter 透明传递 provider-specific
状态（如 Anthropic 的 stop_sequence 上下文），engine 不解析。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextBlock:
    """普通文本 block。"""
    text: str
    block_index: int = 0


@dataclass(frozen=True)
class ReasoningBlock:
    """思维链 block。Anthropic thinking / redacted_thinking 的 first-class 表达。

    - 普通 thinking：text + signature（必须保留以支持 multi-turn）+ block_index
    - redacted_thinking：data（加密 blob）+ redacted=True
    - DeepSeek/Kimi/GLM 的 reasoning_content：text + signature=None + redacted=False
    """
    text: str = ""
    signature: str | None = None  # Anthropic native thinking 的 block 签名
    data: str | None = None  # Anthropic redacted_thinking 的加密 blob
    redacted: bool = False
    block_index: int = 0


@dataclass(frozen=True)
class ToolUseBlock:
    """LLM 发起的工具调用（complete 状态）。"""
    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class InvalidToolCall:
    """解析失败的 tool_call（partial JSON / 格式错误等）。

    P5 engine 永不执行 InvalidToolCall。保留这个类型让 adapter 能精确
    报告"模型试图调工具但参数解析失败"，跟"complete tool call"区分开。
    """
    index: int
    call_id: str | None = None
    name_partial: str | None = None
    raw_args: str = ""
    parse_error: str | None = None


@dataclass(frozen=True)
class ProviderState:
    """Provider-specific 状态（透明 dict）。

    让 adapter 把 provider 返回的额外字段（stop_sequence、cache 信息、
    content filter 决策等）原样透传给 engine，engine 不解析、persistence
    透明保留。
    """
    data: dict[str, Any] = field(default_factory=dict)


# Type alias：Message.content 可以是 str（旧形态）或 list[StandardContentBlock]（v1.1+）
StandardContentBlock = TextBlock | ReasoningBlock | ToolUseBlock | InvalidToolCall
