# rd-agent-core v0.1.4

## 变更

- 新增正式 `ModelProfile`，统一描述 provider/model 的 adapter、tool protocol、reasoning protocol、capabilities、protocol limits 和 token 边界。
- `ProviderClientConfig` 新增 `resolve_model_profile()`，OpenAI-compatible / Anthropic native client 会使用规范化 profile 默认值。
- `RunRequest`、`TurnRequest`、`AgentRunnerRequest` 支持传入 `model_profile`，`turn_started` 事件会写入脱敏 profile 摘要。
- 新增 `SubagentRunner`、`SubagentRunnerRequest`、`SubagentRunnerResult`，串起 `SubagentTaskPort`、`SubagentRunPort`、工具 profile 过滤、`RunKernel` 执行和任务终态写回。
- 新增 ModelProfile、provider client profile、SubagentRunner 和公开 API 回归测试。

## 兼容性

- 这是 `rd-agent-core` 的 patch 版本。新增 request 字段均有默认值。
- `OpenAICompatLLMClient` 的 `supports_function_calling` / `supports_stream_usage` 构造参数现在可为 `None`，未显式传入时由 `ModelProfile` 决定；默认 profile 仍保持兼容的开启行为。

## 依赖

- `rd-agent-contracts>=1.14.1,<2.0.0`
- `rd-llm-adapter>=1.1.2,<2.0.0`
