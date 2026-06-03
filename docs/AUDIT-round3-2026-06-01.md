# 第三轮整体审核报告

> **审核日期**：2026-06-01
> **审核对象**：从上次评审基线 commit `9570956` 到当时 HEAD 的一批改动（启动审核时为 8 commit / +6764 行；运行期间又增加 commit，详见下方「快照时点说明」）
> **审核维度**：cache 修复延续性 / 新 testing harness / openai_compat 重构 / rd-agent-core 入库回归 / release 工具链与 CI / 跨切面（架构·安全·一致性）
> **审核方法**：6 个主题单元并行（每单元双重目标：① 验证改动正确闭环 ② 揪出新引入回归/缺陷）→ 每条发现独立 skeptic 对抗证伪 → 去重分级。23 个 agent、1059 次工具调用。
> **关键结论经主会话人工实机复现验证**（P2-A 往返、testpaths 收集、双 details 累加、版本自洽）。

---

## ⚠️ 快照时点说明（重要）

本仓库在多轮审核期间持续高频提交，**版本号与测试基线一直在变动**。各数字的时间切片：

| 时点 | rd-agent-core 版本 | 测试基线 | commit 数（自 9570956） |
|------|-------------------|---------|------------------------|
| 启动本轮审核时 | 0.1.0 | 225 passed / 18 skipped | 8 |
| workflow 运行结束时 | 0.1.1 | 282 passed / 1 skipped | 9（新增 reference host） |
| 落盘核对时 | **0.1.3** | （持续变动） | 9+ |

**结论不受数字漂移影响**：每个时点 pyproject 与 `__init__.__version__` 始终自洽，ruff 始终全过。下文结论按「workflow 结束时点」（0.1.1 / 282 测试）表述，发布时以实际 HEAD 版本为准。

---

## 1. 总体结论

**✅ 这批改动质量高，闭环完整，可合入并发布，无阻断问题。**

- **P2-A（cache token 往返翻倍）已彻底修复**，实机往返验证幂等稳定，未引入新雷。
- **P1-1（cache 拆分计费）闭环依然完整**（`turn._usage_from_update` 四字段映射）。
- 全套测试通过（落盘时 282 passed / 1 skipped），ruff 全过。
- **host-neutral 铁律未被破坏**：新增的两个公共面（`testing.py`、`examples/reference_host`）均只依赖 contracts + adapter + stdlib，无宿主泄漏。
- **集成测试覆盖较第一轮实质改善**：不再依赖注定 skip 的 engine golden，真集成由默认 suite 内的真实 RunKernel e2e 承担。

---

## 2. 逐主题判定表

| 主题 | 判定 | 一句话 |
|------|------|--------|
| **cache 修复延续（P1-1/P2-A）** | ✅ CORRECT | 守卫 `_usage.py:158-169` 检测到拆分字段时跳过 `cached_input_tokens` 累加，往返幂等（实机 3/5/8 跨 2 轮稳定）；`__post_init__` 双向兼容（legacy→read 迁移、拆分→cached 重导）。 |
| **testing harness（testing.py 496 行）** | ✅ CORRECT | 7 个公共测试替身，只 import contracts + adapter + 本包内部 + stdlib，**零 pytest/mock 依赖**，端到端数据流验证通过，未在主 `__init__` 导出（opt-in 子模块，设计合理）。 |
| **openai_compat 重构（+139/-139）** | ✅ CORRECT | 前轮 4 处修复全部坐实：cache 拆分字段分离、usage 触发含拆分字段、非 dict JSON tool 入参显式报错、`finalize_on_error` 真正吐 partial output。 |
| **core 入库（turn.py/run.py）** | ✅ CORRECT | kernel 逻辑首 commit 即完整，9 commit 内无回归；唯一改动是测试断言 `timeout_ms`→`max_wall_clock` 对齐 policy。 |
| **release 工具 + CI + 版本** | ✅ CORRECT* | `verify_release_tag.py` 校验 tag 格式 + pyproject 版本一致；release workflow 门槛顺序正确（verify→lint→test→build→wheel-smoke→publish）；setup-uv/checkout 已 pin 版本。（*见待办 #1 版本号对齐） |
| **跨切面（架构/安全/一致性）** | ✅ CORRECT | `test_architecture_boundaries.py` 通过，rd-agent-core src 无 fastapi/sqlalchemy/boto3/redis 等禁止 import；cache 字段全链路读写一致，无孤儿字段。 |

---

## 3. 待办问题（去重，按修正严重度）

> 经实机核实，对抗验证存活的问题中**多数为「实现正确，无需改动」的确认项**，不构成待办（含 4 条原标 P0 的设计正确性确认、1 条 P1「tool name 初值」因初值总被立即覆盖降为非 bug）。下表只列真正需要动作的项，**全部为 P3，无 P0/P1/P2，无新回归/安全/架构违规**。

| # | 严重度 | 类别 | 问题 | 证据 |
|---|--------|------|------|------|
| 1 | **P3** | doc-consistency | **发布前对齐版本号事实**。审核期间 rd-agent-core 已从 0.1.0 推进（落盘时 0.1.3），各处版本自洽但持续变动。打 tag 发布前确认要发的具体版本号，`verify_release_tag.py` 会校验 tag 与 pyproject 一致。 | `packages/rd-agent-core/pyproject.toml`、`src/rd_agent_core/__init__.py`、`docs/releases/` |
| 2 | **P3** | test-gap（防御性） | `normalize_usage` 同一调用若同时存在 `prompt_tokens_details` 与 `input_tokens_details` 且都含 `cached_tokens`，会累加两边（实机验证：各 10 → cache_read=20）。**实践中单 provider 只出其一**（OpenAI 出前者、Gemini 出后者），故为理论风险；无显式测试覆盖「双 details 同现」。 | `_usage.py:160-169` 双 detail key 循环 |
| 3 | **P3** | release-scope（提示） | release workflow 同时 build/publish `rd-llm-gateway`、`rd-replay-evals` wheel，但 `verify_release_tag.py` 只校验被 tag 包的版本一致性。非本批缺陷，仅提示：附带包的版本一致性不在 tag 校验范围内。 | `.github/workflows/release.yml`、`tools/scripts/verify_release_tag.py` |

---

## 4. 重点专项结论

### (a) P2-A 修复是否彻底 —— ✅ 彻底
实机验证：`UsageRecord(read=3,creation=5).to_dict()` → `{...,cache_read=3,cache_creation=5,cached=8}` → `normalize_usage` 回读得 3/5/8，**第二轮往返仍 3/5/8（幂等）**。守卫在检测到拆分字段时跳过 `cached_input_tokens` 累加；`to_dict` 三字段输出保兼容；`__post_init__` 对 legacy-only 输入（`{cached:10}`→read=10）正确迁移，对 mismatch 输入正确自纠。无放大、无回归。

### (b) testing.py 新公共面是否安全可用 —— ✅ 安全可用
import 清单只有 stdlib + `rd_agent_contracts` + `rd_llm_adapter.events` + 本包内部模块，**无任何 SaaS/DB/web 依赖**，无 pytest/mock 强依赖（不会强迫宿主装测试框架）。全仓 grep 确认 rd-agent-core src 零禁止 import。属 opt-in 子模块、未在主 `__init__` 暴露，设计得当。
**额外**：第 9 commit 的 `examples/reference_host/sqlite_reference_host.py`（534 行新公共面）经核实同样 host-neutral（仅 contracts + stdlib `sqlite3`），自带测试驱动真实 `RunKernel` 端到端（含 async e2e），事件追加用专表 `(run_id, idempotency_key)` 实现幂等，文件头明确声明「executable example, not a production persistence layer」。

### (c) tests_external 是否真被 CI 覆盖 —— 不被覆盖，但这是正确设计（结论较第一轮实质改善）
- `pytest --collect-only` 实测从 tests_external 收集 **0** 条；root `testpaths` 不含 tests_external；`.github/` 无 `tests_external` 引用。tests_external 独立跑得 17 skipped（依赖 codesphere-saas 私有模块的 engine golden）。
- **关键改善**：CI 的集成覆盖**不靠** tests_external —— 真正的集成由默认 suite 内的 `test_adapter_core_integration.py` 与 `examples/reference_host/tests/`（真 RunKernel e2e，5 passed）承担，**这部分是真覆盖不是摆设**。engine golden 作为 opt-in 外部测试合理排除，CI 信号干净。
- 对比第一轮审核「18 skip 掩盖集成链路」的结论：本批通过「把注定 skip 的 saas 依赖测试隔离到 tests_external + 在默认 suite 补真 e2e」**实质性解决了该问题**，不是搬家。

### (d) 版本一致性 —— ✅ 内部一致（数字随提交持续变动）
落盘核对时：rd-agent-core pyproject `0.1.3` == `__version__` `0.1.3`；contracts `1.14.1`。包间依赖约束（`contracts>=…,<2.0`、`adapter>=…,<2.0`）正确。**每个时点都自洽**，仅具体数字随高频提交漂移，发布时以实际 HEAD 为准。

---

## 5. 放行建议

**✅ 可发布。无阻断、无返工项。**

发布前 30 秒确认：
- **对齐版本号**：确认本次要发的 rd-agent-core 具体版本（审核期间已多次推进），打 tag 时 `verify_release_tag.py` 会校验 tag 与 pyproject 一致 —— 内部已自洽，按当前 HEAD 版本打即可。

可选跟进（不阻塞发布，建议排入技术债）：
- 待办 #2：补「双 details 同现」的防御性测试，固化「不累加两边」或明确「实践不会同现」的假设。
- 待办 #3：将附带 publish 的 gateway/replay-evals 纳入 tag 版本校验。

---

## 附：审核方法与可信度说明

- 本报告由 6 主题单元并行 workflow 生成，每条发现经独立 skeptic 对抗证伪（原始发现 → 证伪剔除约半数臆测）。
- workflow 运行期间仓库新增了第 9 个 commit，导致部分输入数字（commit 数、测试基线、版本号）过时；**主会话已用当前 HEAD 实机重新核实所有关键结论**（P2-A 往返、testpaths 收集 0 条、examples e2e 5 passed、双 details 累加 20、版本自洽、ruff 全过），并据此修正了基于旧快照的判断。
- 三轮审核脉络：第一轮发现 P1-1（计费缺陷）+ 23 条问题 → 第二轮评审修复发现 P2-A（往返放大）→ 本轮确认 P2-A 已修 + 集成覆盖实质改善 + 新公共面安全。质量曲线持续向好。

### 关键文件证据索引
- P2-A 守卫：`packages/rd-llm-adapter/src/rd_llm_adapter/_usage.py:158-169`、`__post_init__` 80-88、`to_dict` 90-104
- P1-1 闭环：`packages/rd-agent-core/src/rd_agent_core/turn.py`（`_usage_from_update` 四字段映射）
- openai_compat 修复：`packages/rd-llm-adapter/src/rd_llm_adapter/openai_compat.py`（usage 条件 + 拆分字段、finalize_on_error）
- testing harness：`packages/rd-agent-core/src/rd_agent_core/testing.py:8-44`（import 清单）
- 新公共面：`examples/reference_host/sqlite_reference_host.py`、`examples/reference_host/tests/test_sqlite_reference_host.py`
- CI/release 门槛：`.github/workflows/release.yml`、`ci.yml`；testpaths `pyproject.toml:42`
