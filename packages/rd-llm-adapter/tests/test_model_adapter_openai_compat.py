from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from rd_llm_adapter.anthropic_transport import (
    AnthropicNativeTransport,
)
from rd_llm_adapter.events import (
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallEnd,
    ToolCallNameDelta,
    TurnDone,
    UsageUpdate,
)
from rd_llm_adapter.openai_compat import (
    OpenAICompatAdapter,
    OpenAICompatParserSession,
    legacy_response_from_turn_done,
    standard_event_to_legacy_delta,
    terminal_events_from_turn_done,
)
from rd_llm_adapter.recorder import StreamRecorder
from rd_llm_adapter.transports import OpenAICompatTransport

# claude_client / model_profile 还在 codesphere-saas，不属于 rd-llm-adapter 抽象边界。
# 涉及 create_streaming_turn 的集成测试在独立包内无法跑，整体 skip；这些测试在
# codesphere-saas 端继续覆盖（参见 codesphere-saas/tests/）。
try:  # pragma: no cover - 依赖只在 codesphere-saas 主仓存在
    from app.services.agent_runner.claude_client import (  # type: ignore[import-not-found]
        LLMClientError,
        create_streaming_turn,
    )
    from app.services.agent_runner.model_profile import (  # type: ignore[import-not-found]
        ResolvedModelProfile,
    )

    _HAS_ENGINE_DEPS = True
except ImportError:  # pragma: no cover
    _HAS_ENGINE_DEPS = False
    LLMClientError = None  # type: ignore[assignment]
    create_streaming_turn = None  # type: ignore[assignment]
    ResolvedModelProfile = None  # type: ignore[assignment]

_requires_engine = pytest.mark.skipif(
    not _HAS_ENGINE_DEPS,
    reason="集成测试依赖 codesphere-saas 的 claude_client / model_profile，"
    "在 rd-llm-adapter 独立包内不可用；该覆盖由 codesphere-saas 端测试维持。",
)


def _chunk(
    *,
    content: str | None = None,
    reasoning: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
    usage: Any | None = None,
    choices: list[Any] | None = None,
) -> Any:
    if choices is None:
        delta = SimpleNamespace(
            content=content,
            model_extra=(
                {"reasoning_content": reasoning} if reasoning is not None else {}
            ),
            tool_calls=tool_calls,
        )
        choices = [SimpleNamespace(delta=delta, finish_reason=finish_reason)]
    return SimpleNamespace(choices=choices, usage=usage)


def _tool_delta(
    *,
    index: int = 0,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> Any:
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_build_request_matches_legacy_openai_message_shape() -> None:
    adapter = OpenAICompatAdapter()

    request = adapter.build_request(
        model="deepseek-reasoner",
        system_prompt="sys",
        messages=[
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "hello"}],
                "reasoning_content": "think",
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will call"},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "search",
                        "input": {"query": "x"},
                    },
                ],
                "reasoning_content": "tool-think",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": {"ok": True},
                    }
                ],
            },
        ],
        tools=[
            {
                "name": "search",
                "description": "Search",
                "input_schema": {"type": "object"},
            }
        ],
        max_tokens=1024,
        supports_function_calling=True,
        supports_stream_usage=True,
    )

    assert request["model"] == "deepseek-reasoner"
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["messages"][0] == {"role": "system", "content": "sys"}
    assert request["messages"][1] == {
        "role": "assistant",
        "content": "hello",
        "reasoning_content": "think",
    }
    assert (
        request["messages"][2]["tool_calls"][0]["function"]["arguments"]
        == '{"query": "x"}'
    )
    assert request["messages"][2]["reasoning_content"] == "tool-think"
    assert request["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"ok": true}',
    }
    assert request["tools"][0]["function"]["name"] == "search"


def test_build_request_preserves_explicit_empty_reasoning_content() -> None:
    adapter = OpenAICompatAdapter()

    request = adapter.build_request(
        model="deepseek-reasoner",
        system_prompt="",
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_empty_reasoning",
                        "name": "noop",
                        "input": {},
                    },
                ],
                "reasoning_content": "",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_empty_reasoning",
                        "content": "ok",
                    }
                ],
            },
        ],
        tools=[],
        max_tokens=16,
        supports_function_calling=True,
        supports_stream_usage=True,
    )

    assert request["messages"][0]["role"] == "assistant"
    assert request["messages"][0]["reasoning_content"] == ""


def test_parser_preserves_reasoning_text_usage_and_terminal_response() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(session.feed(_chunk(reasoning="plan ", content="hel")))
    events.extend(
        session.feed(_chunk(reasoning="done", content="lo", finish_reason="stop"))
    )
    events.extend(
        session.feed(
            _chunk(
                usage=SimpleNamespace(
                    prompt_tokens=10, completion_tokens=20, total_tokens=30
                ),
                choices=[],
            )
        )
    )
    events.extend(session.finalize())

    assert any(
        isinstance(event, ReasoningDelta) and event.text == "plan " for event in events
    )
    assert any(isinstance(event, TextDelta) and event.text == "hel" for event in events)
    assert any(
        isinstance(event, UsageUpdate) and event.total_tokens == 30 for event in events
    )

    turn_done = next(event for event in events if isinstance(event, TurnDone))
    response = legacy_response_from_turn_done(
        turn_done, latency_ms=12, first_chunk_latency_ms=3
    )
    assert response == {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        "stop_reason": "stop",
        "latency_ms": 12,
        "first_chunk_latency_ms": 3,
        "reasoning_text": "plan done",
        "text_content": "hello",
    }


def test_parser_reads_direct_reasoning_content_from_dict_chunks() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(
        session.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "content": None,
                            "reasoning_content": "plan ",
                            "tool_calls": None,
                        },
                        "finish_reason": None,
                    }
                ],
                "usage": None,
            }
        )
    )
    events.extend(
        session.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "content": None,
                            "reasoning_content": "done",
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            }
        )
    )
    events.extend(session.finalize())

    assert [
        event.text for event in events if isinstance(event, ReasoningDelta)
    ] == ["plan ", "done"]
    turn_done = next(event for event in events if isinstance(event, TurnDone))
    response = legacy_response_from_turn_done(
        turn_done, latency_ms=12, first_chunk_latency_ms=3
    )
    assert response["reasoning_text"] == "plan done"


def test_parser_reads_openrouter_reasoning_field_from_dict_chunks() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(
        session.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "content": None,
                            "reasoning": "hidden plan",
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            }
        )
    )
    events.extend(session.finalize())

    assert [
        event.text for event in events if isinstance(event, ReasoningDelta)
    ] == ["hidden plan"]
    turn_done = next(event for event in events if isinstance(event, TurnDone))
    assert turn_done.reasoning_blocks[0].text == "hidden plan"


def test_parser_reads_reasoning_details_when_direct_reasoning_absent() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(
        session.feed(
            {
                "choices": [
                    {
                        "delta": {
                            "content": None,
                            "reasoning_details": [
                                {"type": "reasoning.text", "text": "step 1 "},
                                {"type": "reasoning.text", "text": "step 2"},
                            ],
                            "tool_calls": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            }
        )
    )
    events.extend(session.finalize())

    assert [
        event.text for event in events if isinstance(event, ReasoningDelta)
    ] == ["step 1 step 2"]


def test_parser_preserves_usage_detail_tokens() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(
        session.feed(
            _chunk(
                usage={
                    "prompt_tokens": 0,
                    "completion_tokens": 5,
                    "total_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 123},
                    "completion_tokens_details": {"reasoning_tokens": 4},
                },
                choices=[],
            )
        )
    )
    events.extend(session.finalize())

    usage = next(event for event in events if isinstance(event, UsageUpdate))
    assert usage.to_dict() == {
        "input_tokens": 0,
        "output_tokens": 5,
        "total_tokens": 5,
        "cached_input_tokens": 123,
        "reasoning_tokens": 4,
    }
    turn_done = next(event for event in events if isinstance(event, TurnDone))
    response = legacy_response_from_turn_done(
        turn_done, latency_ms=1, first_chunk_latency_ms=1
    )
    assert response["usage"] == usage.to_dict()


def test_parser_preserves_invalid_tool_call_raw_arguments_in_legacy_output() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(
        session.feed(
            _chunk(
                tool_calls=[
                    _tool_delta(
                        call_id="ask_1",
                        name="ask_user",
                        arguments='{"questions":',
                    )
                ],
                finish_reason="tool_calls",
            )
        )
    )
    events.extend(session.finalize())

    turn_done = next(event for event in events if isinstance(event, TurnDone))
    response = legacy_response_from_turn_done(
        turn_done, latency_ms=1, first_chunk_latency_ms=1
    )
    tool_use = response["content"][0]
    assert tool_use["input_parse_error"] is True
    assert tool_use["raw_args"] == '{"questions":'
    assert "parse_error" in tool_use
    assert tool_use["index"] == 0
    assert terminal_events_from_turn_done(turn_done)[0]["raw_args"] == '{"questions":'


def test_parser_keeps_legacy_tool_name_assignment_behavior() -> None:
    session = OpenAICompatParserSession()

    events = []
    events.extend(
        session.feed(_chunk(tool_calls=[_tool_delta(call_id="call_1", name="search")]))
    )
    events.extend(
        session.feed(_chunk(tool_calls=[_tool_delta(name="search", arguments='{"q"')]))
    )
    events.extend(
        session.feed(
            _chunk(
                tool_calls=[_tool_delta(arguments=':"abc"}')],
                finish_reason="tool_calls",
            )
        )
    )
    events.extend(session.finalize())

    name_events = [event for event in events if isinstance(event, ToolCallNameDelta)]
    assert [event.name_delta for event in name_events] == ["search", "search"]

    args_events = [event for event in events if isinstance(event, ToolCallArgsDelta)]
    assert [standard_event_to_legacy_delta(event) for event in args_events] == [
        {
            "type": "tool_use_delta",
            "tool_use_id": "call_1",
            "index": 0,
            "name_delta": None,
            "arguments_delta": '{"q"',
        },
        {
            "type": "tool_use_delta",
            "tool_use_id": "call_1",
            "index": 0,
            "name_delta": None,
            "arguments_delta": ':"abc"}',
        },
    ]

    end = next(event for event in events if isinstance(event, ToolCallEnd))
    assert end.name == "search"
    assert end.parsed_input == {"q": "abc"}
    turn_done = next(event for event in events if isinstance(event, TurnDone))
    response = legacy_response_from_turn_done(
        turn_done, latency_ms=1, first_chunk_latency_ms=1
    )
    assert response["stop_reason"] == "tool_calls"
    assert response["content"] == [
        {"type": "tool_use", "id": "call_1", "name": "search", "input": {"q": "abc"}}
    ]


@_requires_engine
@pytest.mark.asyncio
async def test_create_streaming_turn_uses_shim_and_preserves_legacy_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        _chunk(reasoning="think", content="hi "),
        _chunk(
            tool_calls=[
                _tool_delta(call_id="call_1", name="search", arguments='{"q":"x"}')
            ],
            finish_reason="tool_calls",
        ),
        _chunk(
            usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            choices=[],
        ),
    ]

    async def fake_stream(
        self: OpenAICompatTransport, request_body: dict[str, Any], **kwargs: Any
    ):
        assert request_body["model"] == "fake-model"
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(OpenAICompatTransport, "stream", fake_stream)
    seen: list[dict[str, Any]] = []

    response = await create_streaming_turn(
        api_key="sk-test",
        model="fake-model",
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "name": "search",
                "description": "Search",
                "input_schema": {"type": "object"},
            }
        ],
        max_tokens=128,
        on_stream_event=seen.append,
        profile=None,
    )

    assert [event["type"] for event in seen] == [
        "reasoning_delta",
        "text_delta",
        "tool_use_delta",
        "reasoning",
        "text",
        "tool_use",
    ]
    assert seen[2]["name_delta"] == "search"
    assert seen[2]["arguments_delta"] == '{"q":"x"}'
    assert response["stop_reason"] == "tool_calls"
    assert response["reasoning_text"] == "think"
    assert response["text_content"] == "hi "
    assert response["usage"] == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }


@_requires_engine
@pytest.mark.asyncio
async def test_create_streaming_turn_falls_back_to_openai_runtime_when_native_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("MODEL_ADAPTER_ENABLE_NATIVE_RUNTIME", raising=False)
    monkeypatch.setenv("MODEL_ADAPTER_RECORD_TURNS", "1")
    monkeypatch.setenv("MODEL_ADAPTER_RECORD_DIR", str(tmp_path))
    chunks = [_chunk(content="hi", finish_reason="stop")]

    async def fake_stream(
        self: OpenAICompatTransport, request_body: dict[str, Any], **kwargs: Any
    ):
        assert request_body["messages"][0] == {"role": "system", "content": "sys"}
        assert request_body["messages"][1] == {"role": "user", "content": "hello"}
        assert "system" not in request_body
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(OpenAICompatTransport, "stream", fake_stream)
    profile = ResolvedModelProfile(
        requested_model="claude-sonnet-4-5",
        provider_model_name="claude-sonnet-4-5",
        base_url="https://api.anthropic.com",
        api_key="sk-test",
        max_output_tokens=128,
        adapter_kind="anthropic_native",
    )

    response = await create_streaming_turn(
        api_key="sk-test",
        model="claude-sonnet-4-5",
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        max_tokens=128,
        on_stream_event=None,
        profile=profile,
    )

    assert response["stop_reason"] == "stop"
    assert response["text_content"] == "hi"
    recorded_files = list(tmp_path.glob("*.jsonl.gz"))
    assert len(recorded_files) == 1
    recorded = StreamRecorder().load_turn(recorded_files[0])
    assert recorded.profile_snapshot["adapter_kind"] == "openai_compat"


@_requires_engine
@pytest.mark.asyncio
async def test_create_streaming_turn_can_use_anthropic_native_runtime_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_ADAPTER_ENABLE_NATIVE_RUNTIME", "1")

    async def fake_stream(
        self: AnthropicNativeTransport, request_body: dict[str, Any], **kwargs: Any
    ):
        assert request_body == {
            "model": "claude-sonnet-4-5",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                }
            ],
            "max_tokens": 128,
            "stream": True,
            "system": [{"type": "text", "text": "sys"}],
        }
        assert kwargs["base_url"] == "https://api.anthropic.com"
        for chunk in [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hi"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
            {"type": "message_stop"},
        ]:
            yield chunk

    monkeypatch.setattr(AnthropicNativeTransport, "stream", fake_stream)
    seen: list[dict[str, Any]] = []
    profile = ResolvedModelProfile(
        requested_model="claude-sonnet-4-5",
        provider_model_name="claude-sonnet-4-5",
        base_url="https://api.anthropic.com",
        api_key="sk-test",
        max_output_tokens=128,
        adapter_kind="anthropic_native",
    )

    response = await create_streaming_turn(
        api_key="sk-test",
        model="claude-sonnet-4-5",
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        max_tokens=128,
        on_stream_event=seen.append,
        profile=profile,
    )

    assert seen == [
        {"type": "text_delta", "text": "hi"},
        {"type": "text", "text": "hi"},
    ]
    assert response["stop_reason"] == "stop"
    assert response["text_content"] == "hi"
    assert response["usage"] == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }


@_requires_engine
@pytest.mark.asyncio
async def test_create_streaming_turn_respects_native_runtime_adapter_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_ADAPTER_ENABLE_NATIVE_RUNTIME", "1")
    monkeypatch.setenv("MODEL_ADAPTER_NATIVE_RUNTIME_ADAPTERS", "gemini_native")

    async def fake_stream(
        self: OpenAICompatTransport, request_body: dict[str, Any], **kwargs: Any
    ):
        assert request_body["messages"][0] == {"role": "user", "content": "hello"}
        for chunk in [_chunk(content="hi", finish_reason="stop")]:
            yield chunk

    monkeypatch.setattr(OpenAICompatTransport, "stream", fake_stream)
    profile = ResolvedModelProfile(
        requested_model="claude-sonnet-4-5",
        provider_model_name="claude-sonnet-4-5",
        base_url="https://api.anthropic.com",
        api_key="sk-test",
        max_output_tokens=128,
        adapter_kind="anthropic_native",
    )

    response = await create_streaming_turn(
        api_key="sk-test",
        model="claude-sonnet-4-5",
        system_prompt="",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        max_tokens=128,
        on_stream_event=None,
        profile=profile,
    )

    assert response["stop_reason"] == "stop"
    assert response["text_content"] == "hi"


@_requires_engine
@pytest.mark.asyncio
async def test_create_streaming_turn_native_request_build_error_is_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_ADAPTER_ENABLE_NATIVE_RUNTIME", "1")
    profile = ResolvedModelProfile(
        requested_model="claude-sonnet-4-5",
        provider_model_name="claude-sonnet-4-5",
        base_url="https://api.anthropic.com",
        api_key="sk-test",
        max_output_tokens=128,
        adapter_kind="anthropic_native",
    )

    with pytest.raises(LLMClientError) as exc_info:
        await create_streaming_turn(
            api_key="sk-test",
            model="claude-sonnet-4-5",
            system_prompt="sys",
            messages=[
                {
                    "role": "assistant",
                    "content": "previous",
                    "reasoning_content": "unsigned thinking",
                },
                {"role": "user", "content": "hello"},
            ],
            tools=[],
            max_tokens=128,
            on_stream_event=None,
            profile=profile,
        )

    assert exc_info.value.details["error_code"] == "MODEL_PROTOCOL_ERROR"
    assert exc_info.value.details["retryable"] is False
    assert exc_info.value.details["partial_output"] is False


@_requires_engine
@pytest.mark.asyncio
async def test_create_streaming_turn_records_fixture_when_env_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    chunks = [
        _chunk(content="hi", finish_reason="stop"),
        _chunk(
            usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            choices=[],
        ),
    ]

    async def fake_stream(
        self: OpenAICompatTransport, request_body: dict[str, Any], **kwargs: Any
    ):
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(OpenAICompatTransport, "stream", fake_stream)
    monkeypatch.setenv("MODEL_ADAPTER_RECORD_TURNS", "1")
    monkeypatch.setenv("MODEL_ADAPTER_RECORD_DIR", str(tmp_path))

    seen: list[dict[str, Any]] = []
    response = await create_streaming_turn(
        api_key="sk-test",
        model="fake-model",
        system_prompt="sys",
        messages=[{"role": "user", "content": "sensitive input"}],
        tools=[],
        max_tokens=128,
        on_stream_event=seen.append,
        profile=None,
    )

    files = list(tmp_path.glob("*.jsonl.gz"))
    assert len(files) == 1
    recorded = StreamRecorder().load_turn(files[0])
    assert recorded.expected_events == seen
    assert recorded.expected_legacy_dict == response
    assert recorded.request_body["messages"][1]["content"] == "[redacted:15 chars]"
    assert recorded.raw_chunks[0]["choices"][0]["delta"]["content"] == "hi"
