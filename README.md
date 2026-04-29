# ruidong-agent-core

Agent Runtime PaaS — 把 codesphere-saas 中的 agent 能力抽象为可被任何项目调用的库与服务。

## 状态

Phase A（库形态 + replay 基线），版本 1.0.0。

## 仓库结构

```
ruidong-agent-core/
├── packages/
│   ├── rd-agent-contracts/    # P1 跨包共享协议（types/ports/event envelope）
│   ├── rd-llm-gateway/        # P2 LLMProvider + stream chunk normalizer
│   └── rd-replay-evals/       # P9 录制器 + replay 引擎 + golden traces
├── tools/                     # 独立 CLI 工具（dump_run 等）
└── pyproject.toml             # uv workspace root
```

## 设计文档

`docs/superpowers/specs/2026-04-28-paas-runtime-design.md`（在 codesphere-saas 仓库）

## 开发

```bash
cd ~/ruidong/ruidong-agent-core
uv sync --all-extras
uv run pytest
uv run ruff check .
```
