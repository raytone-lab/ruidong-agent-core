"""contracts 1.1 typed transcript blocks 测试。

验证：
- TextBlock / ReasoningBlock / ToolUseBlock / InvalidToolCall / ProviderState 是 frozen dataclass
- Anthropic signature / redacted thinking 有专门字段（ReasoningBlock.signature, .data）
- ToolUseBlock 含 tool_use_id / name / input
- InvalidToolCall 含错误信息（解析失败的 tool_call）
- ProviderState 是 unstructured dict（让 adapter 透明传递 provider-specific state）
"""
from dataclasses import FrozenInstanceError

import pytest
from rd_agent_contracts import (
    InvalidToolCall,
    ProviderState,
    ReasoningBlock,
    TextBlock,
    ToolUseBlock,
)


def test_text_block_is_frozen():
    block = TextBlock(text="hello")
    with pytest.raises(FrozenInstanceError):
        block.text = "modified"  # type: ignore[misc]


def test_reasoning_block_with_signature():
    block = ReasoningBlock(
        text="thinking...",
        signature="sig-abc",
        redacted=False,
        block_index=0,
    )
    assert block.text == "thinking..."
    assert block.signature == "sig-abc"
    assert block.redacted is False


def test_reasoning_block_redacted_data():
    """Anthropic redacted_thinking 用 data 字段而非 text。"""
    block = ReasoningBlock(
        text="",
        data="encrypted-blob-base64",
        redacted=True,
        block_index=0,
    )
    assert block.redacted is True
    assert block.data == "encrypted-blob-base64"


def test_tool_use_block_basic():
    block = ToolUseBlock(
        tool_use_id="toolu_abc",
        name="run_command",
        input={"command": "ls"},
    )
    assert block.tool_use_id == "toolu_abc"
    assert block.name == "run_command"
    assert block.input == {"command": "ls"}


def test_invalid_tool_call_carries_error():
    block = InvalidToolCall(
        index=0,
        call_id="toolu_xyz",
        name_partial="run_com",
        raw_args="{ ",
        parse_error="JSON truncated",
    )
    assert block.parse_error == "JSON truncated"


def test_provider_state_is_dict():
    state = ProviderState(data={"some_key": "some_val"})
    assert state.data["some_key"] == "some_val"


def test_blocks_can_be_listed_in_content():
    """Message.content 可 list[StandardContentBlock]，与 TurnDone.content 一致。"""
    blocks: list = [
        TextBlock(text="hello"),
        ReasoningBlock(text="thinking", signature="sig", block_index=0),
        ToolUseBlock(tool_use_id="t1", name="ls", input={}),
    ]
    assert len(blocks) == 3
    assert isinstance(blocks[0], TextBlock)
    assert isinstance(blocks[1], ReasoningBlock)
    assert isinstance(blocks[2], ToolUseBlock)
