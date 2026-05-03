# rd-llm-adapter

低层 LLM provider 适配器包：协议定义 + adapter 实现 + stream parser session + recorder。

## Hero use case

实现 Adapter / Transport / StreamParserSession 协议接入新 provider：

```python
from rd_llm_adapter import Adapter, Transport, StreamParserSession

class MyProviderAdapter(Adapter):
    adapter_kind = "my_provider"

    def build_request(self, ...):
        return {...}

    def create_parser_session(self, profile=None):
        return MyProviderParserSession(profile)

# 注册到 registry
from rd_llm_adapter.registry import resolve_adapter
adapter = resolve_adapter("my_provider")
```

## 暴露符号

- 协议：`Adapter` / `Transport` / `StreamParserSession`
- StandardEvent 9 类：`TextDelta` / `ReasoningDelta` / `ToolCallStart` / `ToolCallIdDelta` /
  `ToolCallNameDelta` / `ToolCallArgsDelta` / `ToolCallEnd` / `UsageUpdate` / `TurnDone`
- Capabilities：`ModelCapabilities` / `ProtocolLimits` / `ThinkingExtractionConfig`
- Adapter 实现：`OpenAICompatAdapter` / `AnthropicNativeAdapter`
- Transport 实现：`OpenAICompatTransport` / `AnthropicNativeTransport`
- Recorder：`StreamRecorder` / `RecordedTurn` / `ReplayEvents`
- Registry：`resolve_adapter` / `resolve_transport` / `resolve_adapter_for_profile`

## 不暴露

- Channel router（rd-llm-gateway 2.0 职责）
- Provider lock 实施（rd-orchestration 职责）
- Retry 策略（rd-llm-gateway 2.0 职责）

## 设计文档

详见 [`docs/MODEL-ADAPTER.md`](../../docs/MODEL-ADAPTER.md)（v8 spec，2707 行）。
