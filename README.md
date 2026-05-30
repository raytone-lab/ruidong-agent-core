# ruidong-agent-core

Agent Runtime PaaS — 把 codesphere-saas 中的 agent 能力抽象为可被任何项目调用的库与服务。

## 状态

Phase B 进行中。

- `rd-agent-contracts`：当前开发版 `1.13.0`，新增 RunPersistencePort / EventLogPort / ContinuationQueuePort / SubagentTaskPort / TimelineReadPort / ToolRegistryPort 等 Agent lifecycle contract；`SCHEMA_VERSION` 仍为 `1.2.0`。
- `rd-agent-core`：新增 host-neutral turn/run kernel、业务 Agent adapter 协议、事件写入 facade、运行限制/重复工具调用策略；只依赖 contracts 与 llm adapter，不依赖 SaaS DB / 前端 / PPT 业务实现。
- `rd-agent-core.testing`：可复用 host integration harness，提供内存 event log/run persistence、脚本化 LLM、函数式工具执行器与端到端 run 入口。
- `rd-llm-adapter`：已从 `codesphere-saas` model_adapter 抽出，当前发布 tag 为 `rd-llm-adapter-v1.1.0`。
- `rd-llm-gateway`：保留 Phase A v1 产物，暂不作为 Phase B engine 边界。
- `rd-replay-evals` / `rd-tools`：保留 Phase A replay 和运维工具链。

## 仓库结构

```
ruidong-agent-core/
├── packages/
│   ├── rd-agent-contracts/    # P1 跨包共享协议（types/ports/event envelope）
│   ├── rd-agent-core/         # Phase B host-neutral turn kernel + business adapter contracts
│   ├── rd-llm-adapter/        # Phase B provider adapter + raw chunk replay
│   ├── rd-llm-gateway/        # Phase A LLMProvider + stream chunk normalizer
│   └── rd-replay-evals/       # P9 录制器 + replay 引擎 + golden traces
├── tools/                     # 独立 CLI 工具（dump_run 等）
└── pyproject.toml             # uv workspace root
```

## 设计文档

- `docs/agent-core-abstraction.md`：core 的抽象边界与 SaaS 接入方式。
- `docs/HOST-INTEGRATION-CONTRACT.md`：host 接入契约、职责分界与 release gate。
- `docs/superpowers/specs/2026-04-28-paas-runtime-design.md`（在 codesphere-saas 仓库）。

## 开发

```bash
cd ~/ruidong/ruidong-agent-core
uv sync --all-extras
uv run pytest
uv run ruff check .
```
