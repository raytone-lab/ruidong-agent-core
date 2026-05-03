from __future__ import annotations

import pytest
from rd_llm_adapter.anthropic_native import (
    AnthropicNativeAdapter,
    AnthropicNativeParserSession,
)
from rd_llm_adapter.events import (
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallEnd,
    ToolCallStart,
    TurnDone,
    UsageUpdate,
)
from rd_llm_adapter.messages import (
    InvalidToolCall,
    ReasoningBlock,
    TextBlock,
    ToolUseBlock,
)


def _feed_all(session: AnthropicNativeParserSession, chunks: list[dict]) -> list:
    events = []
    for chunk in chunks:
        events.extend(session.feed(chunk))
    return events


def test_anthropic_build_request_serializes_legacy_messages_and_tools() -> None:
    adapter = AnthropicNativeAdapter()

    request = adapter.build_request(
        model="claude-sonnet-4-5",
        system_prompt="sys",
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "reasoning_blocks": [
                    {
                        "type": "reasoning",
                        "text": "plan",
                        "signature": "sig-1",
                    }
                ],
                "content": [
                    {"type": "text", "text": "I will search"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "search",
                        "input": {"q": "x"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": {"ok": True},
                    }
                ],
            },
        ],
        tools=[
            {
                "name": "search",
                "description": "Search",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        max_tokens=1024,
        thinking_budget_tokens=256,
    )

    assert request["model"] == "claude-sonnet-4-5"
    assert request["stream"] is True
    assert request["system"] == [{"type": "text", "text": "sys"}]
    assert request["thinking"] == {"type": "enabled", "budget_tokens": 256}
    assert request["tools"] == [
        {
            "name": "search",
            "description": "Search",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert request["messages"][0] == {
        "role": "user",
        "content": [{"type": "text", "text": "hello"}],
    }
    assert request["messages"][1]["content"] == [
        {"type": "thinking", "thinking": "plan", "signature": "sig-1"},
        {"type": "text", "text": "I will search"},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "search",
            "input": {"q": "x"},
        },
    ]
    assert request["messages"][2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": '{"ok": true}',
            }
        ],
    }


def test_anthropic_build_request_serializes_redacted_thinking() -> None:
    adapter = AnthropicNativeAdapter()

    request = adapter.build_request(
        model="claude-sonnet-4-5",
        system_prompt="",
        messages=[
            {
                "role": "assistant",
                "reasoning_blocks": [
                    {
                        "type": "reasoning",
                        "redacted": True,
                        "data": "encrypted-thinking",
                    }
                ],
                "content": [{"type": "text", "text": "visible"}],
            }
        ],
        tools=[],
        max_tokens=128,
    )

    assert request["messages"][0]["content"] == [
        {"type": "redacted_thinking", "data": "encrypted-thinking"},
        {"type": "text", "text": "visible"},
    ]


def test_anthropic_build_request_rejects_unsigned_legacy_reasoning() -> None:
    adapter = AnthropicNativeAdapter()

    with pytest.raises(ValueError, match="legacy reasoning_content"):
        adapter.build_request(
            model="claude-sonnet-4-5",
            system_prompt="",
            messages=[
                {
                    "role": "assistant",
                    "reasoning_content": "plan without signature",
                    "content": [{"type": "text", "text": "visible"}],
                }
            ],
            tools=[],
            max_tokens=128,
        )

    with pytest.raises(ValueError, match="requires signature"):
        adapter.build_request(
            model="claude-sonnet-4-5",
            system_prompt="",
            messages=[
                {
                    "role": "assistant",
                    "reasoning_blocks": [{"type": "reasoning", "text": "plan"}],
                    "content": [{"type": "text", "text": "visible"}],
                }
            ],
            tools=[],
            max_tokens=128,
        )


def test_anthropic_parser_preserves_thinking_signature_text_and_usage() -> None:
    session = AnthropicNativeParserSession()

    events = _feed_all(
        session,
        [
            {
                "type": "message_start",
                "message": {"usage": {"input_tokens": 10}},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "plan "},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig-1"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "hello"},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 7},
            },
            {"type": "message_stop"},
        ],
    )

    assert any(
        isinstance(event, ReasoningDelta) and event.text == "plan " for event in events
    )
    assert any(
        isinstance(event, TextDelta) and event.text == "hello" for event in events
    )
    usage_updates = [event for event in events if isinstance(event, UsageUpdate)]
    assert [event.to_dict() for event in usage_updates] == [
        {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
        {"input_tokens": 10, "output_tokens": 7, "total_tokens": 17},
    ]

    turn_done = next(event for event in events if isinstance(event, TurnDone))
    assert turn_done.stop_reason == "stop"
    assert turn_done.usage is not None
    assert turn_done.usage.to_dict() == {
        "input_tokens": 10,
        "output_tokens": 7,
        "total_tokens": 17,
    }
    assert isinstance(turn_done.content[0], ReasoningBlock)
    assert turn_done.content[0].text == "plan "
    assert turn_done.content[0].signature == "sig-1"
    assert isinstance(turn_done.content[1], TextBlock)
    assert turn_done.content[1].text == "hello"


def test_anthropic_parser_preserves_redacted_thinking_data() -> None:
    session = AnthropicNativeParserSession()

    events = _feed_all(
        session,
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "redacted_thinking",
                    "data": "encrypted-thinking",
                },
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ],
    )

    assert not any(isinstance(event, ReasoningDelta) for event in events)
    turn_done = next(event for event in events if isinstance(event, TurnDone))
    block = turn_done.reasoning_blocks[0]
    assert block.redacted is True
    assert block.data == "encrypted-thinking"
    assert block.text == ""


def test_anthropic_parser_accumulates_tool_input_json() -> None:
    session = AnthropicNativeParserSession()

    events = _feed_all(
        session,
        [
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "search",
                },
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '{"q"'},
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": ':"x"}'},
            },
            {"type": "content_block_stop", "index": 2},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
            },
            {"type": "message_stop"},
        ],
    )

    assert any(
        isinstance(event, ToolCallStart)
        and event.call_id == "toolu_1"
        and event.name == "search"
        for event in events
    )
    assert [
        event.delta for event in events if isinstance(event, ToolCallArgsDelta)
    ] == ['{"q"', ':"x"}']

    end = next(event for event in events if isinstance(event, ToolCallEnd))
    assert end.parsed_input == {"q": "x"}
    assert end.parse_error is None

    turn_done = next(event for event in events if isinstance(event, TurnDone))
    assert turn_done.stop_reason == "tool_use"
    assert isinstance(turn_done.content[0], ToolUseBlock)
    assert turn_done.content[0].input == {"q": "x"}
    assert turn_done.tool_calls[0].id == "toolu_1"


def test_anthropic_parser_invalid_tool_json_becomes_invalid_tool_call() -> None:
    session = AnthropicNativeParserSession()

    events = _feed_all(
        session,
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_bad",
                    "name": "search",
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"q"'},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ],
    )

    end = next(event for event in events if isinstance(event, ToolCallEnd))
    assert end.parsed_input is None
    assert end.parse_error

    turn_done = next(event for event in events if isinstance(event, TurnDone))
    assert isinstance(turn_done.content[0], InvalidToolCall)
    assert turn_done.content[0].raw_args == '{"q"'
    assert turn_done.invalid_tool_calls[0].id == "toolu_bad"


def test_anthropic_parser_stream_error_raises_without_turn_done() -> None:
    session = AnthropicNativeParserSession()

    with pytest.raises(RuntimeError, match="upstream failed"):
        list(
            session.feed(
                {
                    "type": "error",
                    "error": {"message": "upstream failed"},
                }
            )
        )

    assert list(session.finalize_on_error()) == []
