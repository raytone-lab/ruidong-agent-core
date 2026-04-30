# Phase B 启动备忘录

**日期**：Phase A 完成（2026-04-30）后立即记录
**状态**：Phase B 尚未启动，本文档供下次会话参考

---

## Phase A 完成的 8 类抽象（详见 `docs/superpowers/specs/2026-04-28-paas-runtime-design.md` 在 codesphere-saas 仓库）

| 层 | 包 | 资产 |
|---|---|---|
| **数据契约** | `rd-agent-contracts` | 6 种 ID + StopReason/ToolCallStatus + Message/ToolCall/ToolResult + Usage + BlobRef + BudgetEnvelope + ProviderLock + AgentEvent + 6 横切 ports + Clock |
| **LLM 网关 v1** | `rd-llm-gateway` | StreamChunk + StreamNormalizer + ChatRequest + LLMProvider + OpenAICompatProvider |
| **Replay 工具链** | `rd-replay-evals` | GoldenTrace 文件格式 + dump_event_rows + RecordingEventSink + MockLLMProvider/MockToolExecutor + 5 条一致性检查 |
| **运维工具** | `rd-tools` | dump_run CLI（psycopg2 直连）+ finalize_traces.py |
| **CI/发布** | — | GitHub Actions ci + tag-triggered release wheel |
| **codesphere 接入** | `app/services/rd_recorder.py` | ENV-gated fan-out hook（`RD_RECORD_TRACES=1`） |
| **真实数据** | `traces/golden/` | 3 个真实 chat session trace（634 events） |
| **部署链路** | — | GitHub release wheel → codesphere pyproject `@ URL` 依赖 → saas-test 灰度成功 |

测试：86 passed / ruff 0 errors / GitHub CI 全绿。
Tag：`phase-a-complete`。

---

## ⚠️ Phase B 启动前必须解决的设计冲突

**rd-llm-gateway v1（Phase A 产物）vs codesphere-saas 的 model_adapter（用户独立做的）**

### 现状

- Phase A 期间，rd-llm-gateway 写了 `StreamNormalizer` + `StreamChunk`（6 种 chunk type，简单粒度）
- 同一时期，用户在 codesphere-saas 仓库**独立**做了 `app/services/agent_runner/model_adapter/`（v8 版本，Codex 6 轮 review，2439 行设计文档）
- model_adapter 比 rd-llm-gateway v1 **更成熟、更细粒度、覆盖更全**

### 对比

| 维度 | rd-llm-gateway v1 | model_adapter（codesphere-saas） |
|---|---|---|
| 事件类型 | 6 种 chunk | 9+ 种 StandardEvent（含 ReasoningDelta/ToolCallStart/Id/Name/Args/End/UsageUpdate/TurnDone/TextDelta） |
| Stateful | seq counter | 整 turn 的 StreamParserSession |
| 失败语义 | partial → 标 PARTIAL | shim 抛 transport exception，engine 闭合 |
| Reasoning | 单 THINKING_DELTA | ReasoningBlock + redacted data + signature |
| Tool call | tool_use_id + status | index + call_id + name + args delta + InvalidToolCall + encoding |
| Capabilities | 复用 codesphere 的 model_profile.py | ModelCapabilities + ProtocolLimits + ThinkingExtractionConfig |
| 审视 | Codex 2 轮 | **Codex 6 轮 + selfagency 复核** |
| 设计文档 | spec §4.1 ~150 行 | `docs/design/MODEL-ADAPTER.md` 2439 行 v8 |
| 测试 | 11 单元 | engine golden tests（9 边界） |

### 决定

**Phase B 启动时**：把 model_adapter 移植为 `rd-llm-gateway v2`，**deprecate rd-llm-gateway v1**。

**不要先抽 P5 engine**——因为 engine 依赖的"LLM 边界"层应该是 v2 的形态而不是 v1，先抽 engine 会让 v1 被"凝固"进 engine 接口。

**正确顺序**：

1. 把 codesphere-saas 的 `model_adapter/` 全部内容搬到 `ruido-agent-core/packages/rd-llm-gateway/v2/`（或新建 `rd-llm-adapter` 包，保留 v1 包名）
2. 把 codesphere-saas 的 `MODEL-ADAPTER.md` 设计文档搬到新仓库 `docs/`
3. codesphere-saas 改为 `from rd_llm_gateway_v2 import OpenAICompatAdapter`（保持当前接入，验证移植无 regression）
4. 然后才抽 P5 engine（engine 此时消费 v2 的 StandardEvent）

### 受影响的设计文档

- `~/ruidong/codesphere-saas/docs/superpowers/specs/2026-04-28-paas-runtime-design.md` §4 P2 部分需要更新——v2 是真实形态，v1 文字过时
- Phase A plan T15-T19 已经写完，**不回溯改**——把它们标"v1, deprecated by Phase B v2"

---

## Phase B 启动检查清单（下次会话开始时按顺序做）

### Step 0：会话启动前的状态确认

```bash
cd ~/ruidong/ruidong-agent-core
git checkout main
git pull
git log --oneline phase-a-complete -5  # 验证 tag 在
```

```bash
cd ~/ruidong/codesphere-saas
git checkout newsaas
git status  # 确认无脏修改，或先 stash/commit 你的工作
git log --oneline -5  # 看 ENV-gated rd_recorder 接入还在
ssh root@13.221.2.57 "grep RD_RECORD /root/codesphere/.env.saas-test"  # ENV 状态
```

### Step 1：拉一晚上的 trace（如果 ENV 还 ON）

```bash
ssh root@13.221.2.57 "ls -la /tmp/rd_traces/"
mkdir -p /tmp/rd_traces_dump_$(date +%F)
scp 'root@13.221.2.57:/tmp/rd_traces/*.jsonl' /tmp/rd_traces_dump_$(date +%F)/

# 用 finalize_traces.py 转成 golden trace 格式
cd ~/ruidong/ruidong-agent-core
uv run python tools/scripts/finalize_traces.py \
    --input-dir /tmp/rd_traces_dump_$(date +%F) \
    --output-dir traces/golden

# 跑自一致性测试
uv run pytest packages/rd-replay-evals/tests/test_golden_traces_self_consistent.py -v
```

如果场景多样（不同 category），可以手动重命名 + 调整 meta.category 让 trace 集合更丰富。

### Step 2：关 ENV（重要！防止 saas-test 一直产生 trace 文件占盘）

```bash
ssh root@13.221.2.57 "
sed -i '/^RD_RECORD_TRACES/d; /^RD_RECORD_DIR/d; /^# Phase A B+/d' /root/codesphere/.env.saas-test
"
cd ~/ruidong/codesphere-saas
bash sync_saas_test.sh --restart
```

trace 录制能力**保留在代码里**，只是 ENV OFF 不录。Phase B 想再录随时 export ENV 重启即可。

### Step 3：启动 Phase B brainstorm

调用：

```
/brainstorm
```

或者直接说："启动 Phase B 设计"。

我会进 `superpowers:brainstorming` skill，按以下顺序：

1. **读取本文档**（PHASE-B-NOTES.md）作为已知资产清单
2. **读取 model_adapter** 设计文档（`~/ruidong/codesphere-saas/docs/design/MODEL-ADAPTER.md`）和源码（`~/ruidong/codesphere-saas/app/services/agent_runner/model_adapter/`）
3. **读取 Phase A spec** 的 §3.2/§4 关于 P2-P9 部分
4. **关键决策点提问**（用 AskUserQuestion）：

   - **Phase B 第一刀切哪？**
     - 选项 A：移植 model_adapter → rd-llm-gateway v2（推荐，最稳）
     - 选项 B：抽 P5 engine（依赖 v2 形态稳定）
     - 选项 C：先做 P8 orchestration（HTTP API 优先，把 engine 放在更后面）
   - **包结构怎么处理 v1 vs v2 冲突？**
     - 选项 A：rd-llm-gateway v2 完全替换 v1（v1 包从仓库删除）
     - 选项 B：v1 保留为简化视图，v2 是新主线（同名包多版本）
     - 选项 C：新建 rd-llm-adapter 包，rd-llm-gateway 保留为更高层封装
   - **codesphere-saas 怎么演进？**
     - 选项 A：Phase B 早期 codesphere `model_adapter/` 改 import 到新仓库（验证移植）
     - 选项 B：Phase B 末尾才切，先在新仓库稳定 v2
   - **HTTP API 在 Phase B 哪个里程碑？**
     - 选项 A：Phase B 末尾（B-3）
     - 选项 B：Phase B 中段（B-2，engine 抽完立刻包 API）
     - 选项 C：Phase B 不做（Phase C）
   - **A1 saas-adapter 怎么演进？**
     - 选项 A：Phase B 第一件事就抽（codesphere 当下就用 ports 接所有依赖）
     - 选项 B：Phase B 末尾（先抽 engine，最后接管 codesphere）
   - **新增审视环节？**
     - codesphere model_adapter 已经走过 Codex 6 轮，移植到新仓库时是否还需要再审？
     - Phase B 整体是否需要 outside voice 审 spec（Codex / 用户的另一个朋友 / etc）

5. **让 Codex 走对抗审视**（Phase A spec v3 之后没有再大审一次，Phase B 应该补）

6. **输出 Phase B spec**：写到 `~/ruidong/codesphere-saas/docs/superpowers/specs/YYYY-MM-DD-phase-b-design.md`

7. **进 `superpowers:writing-plans`**：拆 Phase B-1 / B-2 / B-3 几个里程碑

8. **执行**：仍然用 `superpowers:subagent-driven-development`

---

## 启动 Phase B 时给我看的"开机消息"模板

下次会话开始，复制下面这段给我（你不需要记忆，文档在仓库里）：

```
Phase A 已完成（tag phase-a-complete，commit 5ace0e3）。
启动 Phase B：读 ~/ruidong/ruidong-agent-core/PHASE-B-NOTES.md。
```

或更简：

```
启动 Phase B
```

我会自动找到本文档 + 已有的 spec / plan，进 brainstorming。

---

## Phase A 学到的 5 条经验（影响 Phase B 决策）

1. **engine 已经是 callback 模式**——意外的红利。Phase B 抽 P5 时不需要重构 engine.py 的内部，只需要换 callback 实现。
2. **codesphere events 表只有状态机事件**——chunk 级 trace 必须靠 RecordingEventSink hook，不能从 events 表 dump 出来（这是 D 路径不可行的真因）。
3. **GitHub release wheel 路径完美**——HTTPS URL 依赖 + uv sync 一气呵成。Phase B 多包发布可以直接复用同一个 release.yml workflow，只换 tag 名。
4. **rsync 部署绕过 git 分支保护**——sync_saas_test.sh 推 working dir，不走 git。Phase B 触及 codesphere-saas 时要小心：feature 分支没 merge 到 newsaas 也能"误部署"。
5. **私有→公开仓库切换无成本**——rd-agent-contracts wheel 的 404 问题靠 `gh repo edit --visibility public` 一键修。Phase B 起仓库就保持 public，不要再切。

---

## 没做的（Phase B 必须补）

- ❌ engine 主循环抽出（P5）
- ❌ tools 层（fs/shell/web/subagent，P6）
- ❌ 上下文工程（compaction/budget/assembler，P3）
- ❌ memory 系统（P4）
- ❌ 持久化（RunPersistence/EventLog/BlobStore，S1）
- ❌ orchestration（run service / continuation queue / subagent queue，P8）
- ❌ HTTP API（/v1/runs，D1）
- ❌ A1 saas-adapter 完整形态（仅有 rd_recorder hook 是预演，不是完整 adapter）
- ❌ workspace runtime / sandbox（Phase C，不是 Phase B）

---

## 已识别的"占位字段"债（Phase B 可顺手清的）

调研 2026-04-30 发现：

### 思考配额 (thinking budget) — 当前完全无效

**两个字段都是死代码**：

1. `app/api/codesphere/project.py:152` 定义 `ReasoningEffort` enum（Think / Think Hard / Think Harder / Ultrathink）
   - `ActProxyRequest.reasoning_effort` 字段公开给 API 客户端
   - **`grep services/ reasoning_effort` 零结果**——服务端完全不消费

2. `app/services/agent_runner/model_adapter/capabilities.py:16` 定义 `ThinkingExtractionConfig.budget_tokens: int | None`
   - **`grep budget_tokens` 仅这一处**——从未被读取

3. `model_adapter/openai_compat.py` 的 `build_request` 不传任何 thinking 相关参数到 LLM
   - Anthropic 原生 `thinking={"type":"enabled","budget_tokens":N}` 没接
   - OpenAI o1/o3 `reasoning_effort` 参数没接
   - DeepSeek/Kimi reasoning_content 配置没接

**意思**：前端能传 reasoning_effort，后端默默丢弃。**用户主观感觉"我选了 Ultrathink 应该更深思考"，实际效果跟 Think 一样**。

### MODEL-ADAPTER spec v8 是否兼容此功能？

**设计层面：✅ 完全设计了**
- `ThinkingExtractionConfig.budget_tokens: int | None`（capabilities.py:16，spec §4.2）
- `AnthropicNativeAdapter.build_request` 伪代码已写（spec 行 1433-1437）：
  ```python
  if profile.capabilities.thinking.mode == "anthropic_block" 
     and profile.capabilities.thinking.budget_tokens:
      body["thinking"] = {
          "type": "enabled",
          "budget_tokens": profile.capabilities.thinking.budget_tokens,
      }
  ```
- ReasoningEffort enum 4 档已定义在 API 层

**实现层面：❌ 三个 gap**

1. **`OpenAICompatAdapter.build_request` 不传 thinking budget**
   - 现状：completely 不看 `capabilities.thinking`
   - 但根本问题：**OpenAI chat/completions 协议本身没有 budget_tokens 字段**
   - Replacement：OpenAI o1/o3 用 `reasoning_effort: "low"|"medium"|"high"`（档位不是 token 数）
   - DeepSeek / Kimi / GLM-Zero 完全没文档支持 budget 控制

2. **`AnthropicNativeAdapter` 未实现**
   - `model_adapter/` 目录只有 `openai_compat.py`
   - spec 标"阶段 2 PoC 草图"
   - **只有 anthropic_native 才能真正传 `thinking.budget_tokens`**

3. **ReasoningEffort enum → ThinkingExtractionConfig 映射不存在**
   - 4 档 → budget_tokens 数值 / o1 reasoning_effort 档位的映射函数空白

### 完整修复路径（Phase B 时做）

```
Step 1: 实现 AnthropicNativeAdapter（spec §4.1.1 + 行 1300-1500 伪代码）
        ~150 行代码

Step 2: 加 ReasoningEffort 映射函数
        THINK         → budget_tokens=2000  (or mode="none")
        THINK_HARD    → budget_tokens=5000
        THINK_HARDER  → budget_tokens=10000
        ULTRATHINK    → budget_tokens=24000

Step 3: ResolvedModelProfile 支持 per-request budget_tokens override
        （capabilities 当前是 per-model 静态，需要 per-request 动态覆盖）

Step 4: executor 链路 wire reasoning_effort：
        ActProxyRequest.reasoning_effort
          → ResolvedModelProfile.capabilities.thinking.budget_tokens
          → AnthropicNativeAdapter.build_request body.thinking

Step 5: codesphere model_channels 表里 Claude 系列加
        anthropic_native_base_url（OpenRouter Anthropic-direct 或自建网关）

Step 6: 适配器选择逻辑：当 reasoning_effort 非 None 且模型支持
        anthropic_block thinking 时，自动切到 AnthropicNativeAdapter
        （否则 fallback 到 OpenAICompatAdapter）

Step 7: OpenAI o1/o3 单独支持 reasoning_effort 透传（独立 task，
        不依赖 budget_tokens 路径）
```

### 简化版快速修复（仅 Claude 生效，1-2 天）

```
W1: 实现最小 AnthropicNativeAdapter（仅支持 thinking + 普通 text + tool_use）
W2: ReasoningEffort enum → budget_tokens 映射 + executor wire
W3: saas-test 灰度验证 4 档真生效
```

工作量评估：**~150 行 adapter + 50 行 executor 改 + 30 行测试**。

**这个修复的价值**：
- 修复线上 P0 级体验缺陷（"用户付费选了 Ultrathink，等同 Think"）
- 验证 model_adapter v8 spec 落地路径
- 让 Phase B "移植 model_adapter v2 到新仓库" 时少一个未实现的 adapter

### Phase B 启动决策树更新（含 thinking budget）

```
Phase B 启动选项：
A. 移植 model_adapter → rd-llm-gateway v2（最稳，但工作量大）
B. 抽 P5 engine（依赖 v2 形态稳定）
C. 先做 P8 orchestration
D. (新) Warm-up: 实现 AnthropicNativeAdapter + thinking budget 链路
   → 修复用户付费体验缺陷
   → 完整化 model_adapter（让它从"OpenAI compat 单 adapter" 进化到"多 adapter"）
   → 然后再走 A
```

推荐路径：**D → A → B**。先修线上看得见的缺陷 + 让 model_adapter 完整化（多 adapter），再做架构搬家，最后抽 engine。

**Phase B 启动决策树更新**：

```
Phase B 第一刀候选：
A. 移植 model_adapter → rd-llm-gateway v2（之前推荐）
B. 抽 P5 engine
C. 先做 P8 orchestration
D. (新) Warm-up: thinking budget pass-through 修死代码
   → 然后再走 A
```

推荐路径：**D → A → B**。先修线上看得见的缺陷，再做架构搬家，最后抽 engine。

---

## 关键文件路径速查

| 路径 | 用途 |
|---|---|
| `~/ruidong/ruidong-agent-core/PHASE-B-NOTES.md` | 本文档 |
| `~/ruidong/codesphere-saas/docs/superpowers/specs/2026-04-28-paas-runtime-design.md` | Phase A v3 spec |
| `~/ruidong/codesphere-saas/docs/superpowers/plans/2026-04-29-paas-runtime-phase-a.md` | Phase A 完整 plan（已完成）|
| `~/ruidong/codesphere-saas/docs/design/MODEL-ADAPTER.md` | model_adapter v8 设计（Phase B 必读）|
| `~/ruidong/codesphere-saas/app/services/agent_runner/model_adapter/` | model_adapter 源码（Phase B 移植目标）|
| `~/ruidong/codesphere-saas/app/services/agent_runner/engine.py` | 1766 行 engine（Phase B 抽出目标）|
| `~/ruidong/codesphere-saas/app/services/rd_recorder.py` | Phase A B+ track 接入 hook |
| `~/ruidong/ruidong-agent-core/traces/golden/*.jsonl` | 3 个真实 trace（Phase B 验证基线）|
