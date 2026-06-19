# ruidong-agent-core

Agent Runtime PaaS — 把 codesphere-saas 中的 agent 能力抽象为可被任何项目调用的库与服务。

## 状态

Phase B release candidate。

- `rd-agent-contracts`：当前发布候选版 `1.14.1`，新增 RunPersistencePort / EventLogPort / ContinuationQueuePort / SubagentTaskPort / TimelineReadPort / ToolRegistryPort 等 Agent lifecycle contract；`SCHEMA_VERSION` 仍为 `1.2.0`，并发布 `py.typed` 类型标记。
- `rd-agent-proto`：当前发布候选版 `0.1.0`，发布 `proto/ruidong/agent/v1` wire contract、生成的 Python protobuf bindings、dataclass/proto converters、协议 examples 与 golden trace protobuf roundtrip gate。
- `rd-agent-core`：首发候选版 `0.1.4`，提供 host-neutral turn/run kernel、AgentRunner facade、provider LLM client glue、正式 ModelProfile、SubagentRunner、业务 Agent adapter 协议、事件写入 facade、运行限制/重复工具调用、协作式取消、运行摘要/观测 hook、conformance suite 与工具安全策略；只依赖 contracts 与 llm adapter，不依赖 SaaS DB / 前端 / PPT 业务实现。
- `rd-agent-core.testing`：可复用 host integration harness，提供内存 event log/run persistence、脚本化 LLM、函数式工具执行器与端到端 run 入口。
- `rd-llm-adapter`：当前发布候选版 `1.1.2`，已从 `codesphere-saas` model_adapter 抽出，并对 Anthropic/OpenAI partial error、usage normalize 与 replay 边界做了回归保护，同时发布 `py.typed` 类型标记。
- `rd-llm-gateway`：保留 Phase A v1 历史产物，不作为当前 SDK 推荐 engine 边界；新接入应使用 `rd-llm-adapter` + `rd-agent-core`。
- `rd-replay-evals` / `rd-tools`：保留 Phase A replay 和运维工具链。

## 仓库结构

```
ruidong-agent-core/
├── packages/
│   ├── rd-agent-contracts/    # P1 跨包共享协议（types/ports/event envelope）
│   ├── rd-agent-proto/        # Protobuf wire contract + Python generated bindings
│   ├── rd-agent-core/         # Phase B host-neutral turn kernel + business adapter contracts
│   ├── rd-llm-adapter/        # Phase B provider adapter + raw chunk replay
│   ├── rd-llm-gateway/        # Phase A LLMProvider + stream chunk normalizer
│   └── rd-replay-evals/       # P9 录制器 + replay 引擎 + golden traces
├── tools/                     # 独立 CLI 工具（dump_run 等）
├── examples/                  # 可运行 reference host 和接入示例
└── pyproject.toml             # uv workspace root
```

## 设计文档

- `docs/README.md`：文档入口，区分产品、架构、协议、治理、发布和历史审计。
- `docs/PRODUCT-DESIGN.md`：产品定位、用户、产品面、非目标与质量标准。
- `docs/ARCHITECTURE.md`：包边界、依赖方向、运行时数据流和代码证据。
- `docs/PROTOCOL-CONTRACT.md`：协议真源、proto 文件、Python contract 与行为 contract 的边界。
- `docs/PROTO-RELEASE.md`：`rd-agent-proto` 发布单元、生成、构建和 tag 规则。
- `docs/MULTILANGUAGE-CONSUMPTION.md`：Go/TS/Python 多语言消费准备和边界。
- `docs/REPOSITORY-GOVERNANCE.md`：仓库治理、owner、release gate、文档规则和依赖策略。
- `docs/GLOSSARY.md`：runtime、contract、host、adapter 和 replay 术语表。
- `docs/agent-core-abstraction.md`：core 的抽象边界与 SaaS 接入方式。
- `docs/HOST-INTEGRATION-CONTRACT.md`：host 接入契约、职责分界与 release gate。
- `docs/SDK-OVERVIEW.md`：底座定位、功能清单、架构分层与推荐接入路线。
- `docs/API-REFERENCE.md`：当前 SDK 对外接口文档。
- `docs/API-STABILITY.md`：0.x/1.x API 稳定性、兼容性与弃用策略。
- `docs/EVENT-PAYLOAD-SCHEMA.md`：core 事件 payload schema。
- `docs/QUICKSTART.md`：安装、最小 harness 运行、host 接入顺序与发布验证命令。
- `docs/adr/0001-protocol-source-of-truth.md`：协议真源分层决策。
- `examples/reference_host/README.md`：SQLite reference host 示例。
- `docs/releases/README.md`：版本化文档和 release note 入口。
- `docs/superpowers/specs/2026-04-28-paas-runtime-design.md`（在 codesphere-saas 仓库）。

## 协议

- `proto/ruidong/agent/v1/events.proto`：`AgentEvent` envelope 和 core event type。
- `proto/ruidong/agent/v1/transcript.proto`：transcript block 与 usage wire contract。
- `proto/ruidong/agent/v1/runtime.proto`：tool、run metadata 与 trace identity wire contract。

当前 proto 文件与 Python contract 通过 `tools/scripts/verify_protocol.py` 和
`tools/scripts/verify_governance.py` 做一致性检查。

## 开发

```bash
cd ~/ruidong/ruidong-agent-core
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run python tools/scripts/verify_protocol.py
uv run python tools/scripts/verify_governance.py
```
