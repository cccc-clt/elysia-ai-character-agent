# Elysia V2 Pre-Implementation Audit

> **审计日期**：2026-08-23  
> **代码基线**：`codex/v1.1-stabilization` @ `34534846e761dc47bcdeb2de35c2ec8f21831d1b`  
> **对照计划**：[`ELYSIA_V2_AGENT_UPGRADE_PLAN.md`](ELYSIA_V2_AGENT_UPGRADE_PLAN.md)  
> **语料基线**：[`LORE_CORPUS_V1_BASELINE.md`](LORE_CORPUS_V1_BASELINE.md)

本文档为 V2 改造启动前的实施前审计，**不包含**代码改造本身。

---

## 1. 当前系统架构

### 1.1 前端

| 项 | 实现 | 证据 |
|---|---|---|
| 框架 | Streamlit 单页多 Tab | [`app.py`](app.py), [`src/ui.py`](src/ui.py) |
| 页面 | 聊天、记忆、实验室、档案、陪伴模式侧边栏 | `src/ui.py` 各 `render_*` |
| 移动端 | Streamlit 响应式布局 + 自定义 CSS | `src/ui.py` 内联样式块 |
| Agent 状态 UI | **未实现** | 无 Chat/Work 切换、无 Tool Trace 面板 |

### 1.2 后端 / 应用层

无独立 HTTP 服务；Streamlit 进程内直接调用服务模块。入口 [`app.py`](app.py) 组装 `get_config()`、数据库、各 Service 与可选 `LoreRAG`。

### 1.3 LLM 调用

| 项 | 状态 | 证据 |
|---|---|---|
| 客户端 | OpenAI 兼容 SDK | [`src/llm_client.py`](src/llm_client.py) |
| 文本生成 | `chat()` / `chat_json()` 同步完整响应 | 无 `stream=True` |
| 流式输出 | **未实现**（LLM 文本流） | `llm_client.py` 仅 TTS `stream_to_file` |
| Function Calling / Tools | **未实现** | `chat()` 无 `tools` 参数 |
| 模型路由 | 单模型 + env 配置 | [`src/config.py`](src/config.py) `LLMConfig` |
| 降级 | API Key 缺失时 UI 提示；语音/TTS 有多级 fallback | `voice_service.py`, `app.py` |

### 1.4 Agent 循环

**未实现**。当前为单轮（或带历史上下文的）`PromptBuilder → LLMClient.chat` 直线流程，无 Plan → Tool → Observation 循环。无 `src/agent/` 目录。

### 1.5 Prompt

| 项 | 证据 |
|---|---|
| 组装 | [`src/prompt_builder.py`](src/prompt_builder.py) |
| 内容 | 角色卡、用户画像、陪伴模式、亲密度、长期记忆、最近对话、`lore_context` 占位 |
| 分层 Prompt Layers（V2 §10） | **未实现** — 仍为单模板字符串 |
| Lore 注入 | `app.py` 在 `LORE_RAG_ENABLED` 时调用 `LoreRAG.retrieve` 填入 `lore_context` |

### 1.6 Memory

| 项 | 证据 |
|---|---|
| 服务 | [`src/memory_service.py`](src/memory_service.py) |
| 候选 → 确认流 | pending / confirmed；用户可拒绝删除 |
| 存储 | SQLite 主路径 + JSON fallback | [`src/database.py`](src/database.py) |
| L0/L1/L2 分层（V2 §9） | **未实现** — 单一长期记忆模型 |
| Lore 隔离 | Lore 检索结果仅进 Prompt，不写 Memory | `app.py` lore 路径无 memory write |

### 1.7 Lore RAG

| 项 | 证据 |
|---|---|
| 模块 | [`src/lore/`](src/lore/) — `service`, `retrieval`, `corpus`, `evaluation` |
|  corpora 隔离 | official / bh3text / story_navigation | `src/lore/corpus.py` |
| 检索 | BM25 + hashed vector + optional semantic + RRF | `src/lore/retrieval.py` |
| 默认关闭 | `LORE_RAG_ENABLED=false` | `src/config.py` |
| 降级 | 超时/异常 → 空 augmentation + degraded_reason | `src/lore/service.py` |
| 引用 | citations + source_tier | `LoreAugmentation` models |
| 聊天接入 | `app.py` `get_lore_rag().retrieve` | 原型门：未核验转录默认不参与 |
| V2 Tool `lore_search` | **未实现** — 无 Tool Registry |

### 1.8 数据管线

| 项 | 证据 |
|---|---|
| 官方 lore 爬取 | [`data_pipeline/crawler.py`](data_pipeline/crawler.py), `cli.py` |
| BH3Text | [`data_pipeline/bh3text.py`](data_pipeline/bh3text.py) |
| BH3Helper 导航 | [`data_pipeline/bh3helper.py`](data_pipeline/bh3helper.py) |
| 质量/库存 | `source_inventory`, `lore_integrity_audit`, `vector_readiness` | `data_pipeline/` |
| Corpus V1 后策略 | **停止全量爬取** — 见 LORE_CORPUS_V1_BASELINE §15 |

### 1.9 工具系统

**未实现** Tool Registry / Executor / Permission Gate。仅有 Lore CLI（`python -m src.lore.cli`）与 data_pipeline CLI 作为运维命令，非 Agent 工具。

### 1.10 安全机制

| 机制 | 证据 |
|---|---|
| 来源 URL 白名单 | `src/lore/corpus.py` `is_safe_source_url` |
| 提示注入过滤 | `src/lore/service.py` `INJECTION_PATTERNS` |
| 密钥 | env / `.env`；`.gitignore` 排除 secrets |
| 权限分级（V2 §2.3） | **未实现** |
| BH3Text 非官方 | Tier B，不得提升 |

### 1.11 部署方式

| 平台 | 状态 | 证据 |
|---|---|---|
| 本地 | `streamlit run app.py` | README §9 |
| Streamlit Cloud / HF Spaces | 文档化限制（无本地语音/GPT-SoVITS） | README §13 |
| Lore 索引/语料 | 运行时 Git ignored，云部署默认无完整语料 | `.gitignore`, ADR |

### 1.12 评测与分析

- 角色一致性：[`src/evaluator.py`](src/evaluator.py)
- 玩家体验：[`src/analytics_service.py`](src/analytics_service.py)
- Lore 离线评测：[`src/lore/evaluation.py`](src/lore/evaluation.py)（40 例）
- Agent 评测（V2 §12） | **未实现**

---

## 2. 升级计划差距矩阵

对照 [`ELYSIA_V2_AGENT_UPGRADE_PLAN.md`](ELYSIA_V2_AGENT_UPGRADE_PLAN.md) 主要条目。

| V2 计划项 | 状态 | 证据 / 说明 |
|---|---|---|
| §2.1 Chat / Work 模式分离 | 未实现 | 无 Mode Router；全部走聊天流 |
| §2.2 人格层与执行层分离 | 部分实现 | Prompt 与业务分离，但无独立 Persona Renderer 层 |
| §2.3 四级权限 Risk | 未实现 | 无 `permission.py` |
| §4 ElysiaHarness (`src/agent/harness.py`) | 未实现 | 无 `src/agent/` |
| §4 state / events / trace | 未实现 | 无 agent 运行态持久化 |
| §5 Tool Registry + ToolResult | 未实现 | — |
| §6 六工具：lore_search | 部分实现 | `LoreRAG` 存在但未注册为 Agent Tool |
| §6 memory_search | 部分实现 | Memory 可读列表，无 relevance retrieval API |
| §6 web_search | 未实现 | — |
| §6 read_text_file / write_note / generate_report | 未实现 | — |
| §7 Approval / Permission Gate | 未实现 | Memory 确认是产品层 UI，非 Agent Gate |
| §8 Lore RAG 分层检索 | **已实现**（原型） | `src/lore/`；默认关闭 |
| §8 数据来源 Tier 纪律 | 已实现 | source_inventory, corpus loader |
| §9 L0/L1/L2 Memory | 未实现 | 单一 MemoryService |
| §10 Prompt Layer 重构 | 未实现 | 单模板 |
| §11 Agent Trace / 可观测性 | 未实现 | — |
| §12 Agent Evaluation | 未实现 | 仅有角色 Evaluator + Lore eval |
| §13 MCP | 未实现 | 计划 P2 |
| §14 主动 Agent | 未实现 | 计划 P2 |
| §15 明确不做项 | 需用户决策 | Live2D、套壳 Cyrene 等 — 计划已列 |
| §16 Phase 实施顺序 | 未开始 | 见本文 §4 |
| `llm_client` tools 参数 | 未实现 | V2 §18 |
| DB 表 agent_runs / lore_chunks 等 | 未实现 | V2 §18 建议 |
| UI：Approval Card / Trace | 未实现 | V2 §18 `ui.py` |

**与当前实现冲突**

| 冲突点 | 说明 |
|---|---|
| V2 默认 Work 模式多步循环 vs 当前单轮聊天 | 需 Feature Flag 隔离，不能默认替换聊天 |
| V2 建议 DB 新表 vs 现有 SQLite 迁移纪律 | 须向后兼容迁移，见 AGENTS.md §8 |
| 云部署体积 vs 本地 semantic / 大语料 | semantic 与完整 `data/` 不适合默认云镜像 |

**需用户决策**

1. `main` 与 `codex/v1.1-stabilization` 合并与 push 时机  
2. 是否开启 `LORE_RAG_ENABLED` 灰度  
3. 是否安装 semantic 模型并采纳神经向量路径  
4. Work 模式首批工具范围（是否包含 `web_search`、本地文件写）  
5. LLM 流式输出是否为 V2 硬性需求（当前未实现）

---

## 3. 必须保留的现有能力

| 能力 | 状态 | 验证方式 |
|---|---|---|
| 多轮聊天 | 已实现 | 手动启动 `streamlit run app.py`；`tests/test_memory_regression_v11.py` |
| 爱莉希雅人设 | 已实现 | `characters/`, `prompt_builder.py`；`tests/test_evaluator` 等 |
| Memory 确认流 | 已实现 | `memory_service` + UI；memory regression tests |
| 流式输出 | **未实现**（LLM） | 见 §1.3；保留非流式路径为默认 |
| 模型路由与降级 | 部分 | 单模型；语音多级 fallback `tests/test_voice*` |
| 安全过滤（Lore 注入） | 已实现 | `tests/test_lore_rag.py` 注入用例 |
| Lore 关闭时原聊天路径 | 已实现 | `test_lore_rag_is_disabled_by_default_contract` |
| UI / 移动端布局 | 已实现 | Streamlit + `ui.py` CSS |
| 部署配置文档 | 已实现 | README §13, `.env.example` |
| 语音 STT/TTS | 已实现 | 可选；失败不阻断文字 |
| 亲密度 / 陪伴模式 | 已实现 | `companionship_service`, `companion_mode` |
| SQLite 迁移 | 已实现 | `database.py` migrations |

**V2 改造红线**：上述已实现能力不得在 Phase 1 中删除或静默破坏；新能力默认 Feature Flag 关闭。

---

## 4. V2 阶段建议（可独立测试与回滚）

### Phase 1 — 配置与架构边界整理

| 项 | 内容 |
|---|---|
| **目标** | Chat/Work 概念落地为配置与空模块边界，不改变用户可见聊天行为 |
| **修改文件** | `src/config.py`, 新建 `src/agent/__init__.py`, `src/agent/state.py`（骨架）, `docs/` 或 README 补充 flag 说明 |
| **输入依赖** | 无 |
| **验收标准** | 141 项测试全绿；新模块可 import；默认行为与冻结前一致 |
| **测试** | `pytest -q`；新增 `tests/test_agent_skeleton.py` |
| **Feature Flag** | `AGENT_MODE_ENABLED=false`, `AGENT_WORK_MODE_ENABLED=false` |
| **回滚** | 删除 `src/agent/` 骨架与 config 字段 |
| **人工确认** | 否 |

### Phase 2 — Agent Core（ElysiaHarness 最小循环）

| 项 | 内容 |
|---|---|
| **目标** | 实现无工具的单轮 Harness 包装（记录 state，仍一次 LLM 调用） |
| **修改文件** | `src/agent/harness.py`, `trace.py`, `app.py`（flag 分支） |
| **输入依赖** | Phase 1 |
| **验收标准** | Flag 开时走 Harness；关时走原 `app.py` 路径；测试 mock LLM |
| **测试** | `tests/test_agent_harness.py` |
| **Feature Flag** | `AGENT_HARNESS_ENABLED=false` |
| **回滚** | Flag false，移除 app 分支 |
| **人工确认** | 否 |

### Phase 3 — Tool Registry

| 项 | 内容 |
|---|---|
| **目标** | `tool_registry.py`, `tool_types.py`, `tool_executor.py` 注册与结构化 ToolResult |
| **修改文件** | `src/agent/*` |
| **输入依赖** | Phase 2 |
| **验收标准** | 注册表可列出工具；Executor 返回统一 ToolResult；无 UI 变更 |
| **测试** | 注册/执行单元测试 |
| **Feature Flag** | `AGENT_TOOLS_ENABLED=false` |
| **回滚** | Flag false |
| **人工确认** | 否 |

### Phase 4 — Lore 检索工具接入

| 项 | 内容 |
|---|---|
| **目标** | `lore_search` 工具封装现有 `LoreRAG`，不重复检索逻辑 |
| **修改文件** | `src/agent/tools/lore_search.py`, registry |
| **输入依赖** | Phase 3, Lore Corpus V1 |
| **验收标准** | Work 模式可调用；Chat 模式可选只读；Tier/引用不变 |
| **测试** | 复用 `test_lore_rag` fixtures + agent tool 测试 |
| **Feature Flag** | `AGENT_TOOL_LORE_SEARCH=false` |
| **回滚** | 注销工具 |
| **人工确认** | 否（启用 `LORE_RAG_ENABLED` 需另议） |

### Phase 5 — Memory 与 Lore 隔离强化

| 项 | 内容 |
|---|---|
| **目标** | 明确边界：Lore 结果不进 Memory；Tool 层审计日志 |
| **修改文件** | `memory_service.py`（guard）, `agent/trace.py` |
| **输入依赖** | Phase 4 |
| **验收标准** | 测试证明 lore 检索不触发 memory write |
| **测试** | memory + lore 集成测试 |
| **Feature Flag** | — |
| **回滚** | 移除 guard（保持原行为） |
| **人工确认** | 否 |

### Phase 6 — 计划、执行与审批机制

| 项 | 内容 |
|---|---|
| **目标** | Permission Gate；`write_note` 等写操作 `ask` |
| **修改文件** | `src/agent/permission.py`, `ui.py` Approval Card |
| **输入依赖** | Phase 3 |
| **验收标准** | 写工具阻塞至用户批准；结构化审批记录 |
| **测试** | permission 单元 + UI 冒烟 |
| **Feature Flag** | `AGENT_PERMISSION_GATE=true`（仅 Work 模式） |
| **回滚** | 禁用 Work 模式 |
| **人工确认** | **是**（写操作默认 ask） |

### Phase 7 — 可观测性与评测

| 项 | 内容 |
|---|---|
| **目标** | `agent_runs` / `agent_steps` 表；Agent eval 数据集 |
| **修改文件** | `database.py`, migrations, `src/agent/trace.py`, `evals/` |
| **输入依赖** | Phase 2–6 |
| **验收标准** | 运行可查询 trace；评测脚本可跑 |
| **测试** | DB migration tests |
| **Feature Flag** | `AGENT_TRACE_PERSIST=true` |
| **回滚** | migration down / flag false |
| **人工确认** | 否 |

### Phase 8 — 前端 Agent 状态 UI

| 项 | 内容 |
|---|---|
| **目标** | Chat/Work 切换、Tool 状态、Trace 面板、Lore 来源展示 |
| **修改文件** | `src/ui.py`, `app.py` |
| **输入依赖** | Phase 6–7 |
| **验收标准** | 可视化与 flag 一致；移动端不崩 |
| **测试** | 手动 + 可选 streamlit testing |
| **Feature Flag** | `AGENT_UI_ENABLED=false` |
| **回滚** | 隐藏 UI 入口 |
| **人工确认** | 建议（UX 变更） |

### Phase 9 — 移动端与部署

| 项 | 内容 |
|---|---|
| **目标** | 云部署裁剪（无 semantic/大语料）；HF/Streamlit 配置更新 |
| **修改文件** | README, `requirements.txt`, 部署 yaml |
| **输入依赖** | 全流程 |
| **验收标准** | 云环境文本聊天可用；可选功能降级文档化 |
| **测试** | CI compileall + 核心 pytest 子集 |
| **Feature Flag** | 部署 env |
| **回滚** |  revert 部署配置 |
| **人工确认** | **是**（上线决策） |

---

## 5. 第一阶段实施建议（下一轮最小范围）

**推荐仅执行 Phase 1**，不启动 Harness 实装或 Tool 接入：

1. 新增 `src/agent/` 目录骨架（`state.py` 定义 `AgentMode` enum：`chat` / `work`；空 `Harness` 占位类）。
2. 在 `src/config.py` 增加 Agent 相关 env（全部默认 `false`）。
3. 在 `ELYSIA_V2_AGENT_UPGRADE_PLAN.md` 旁新增 `docs/architecture/AGENT_BOUNDARIES.md`（可选，简短）说明 Chat/Work 边界与 flag。
4. 运行完整 `pytest -q`（141 项）确保零回归。
5. **不修改** `app.py` 聊天主路径、**不开启** Lore、**不合并** `main`。

预估改动：约 5–8 个文件，<300 行，单一 PR/commit 可回滚。

---

## 6. 需用户决定的问题

1. 何时将 `codex/v1.1-stabilization` merge 到 `main` 并 push？  
2. 是否在有限范围开启 `LORE_RAG_ENABLED`？  
3. 是否安装 `requirements-semantic.txt` 并运行 semantic 评测？  
4. V2 Phase 1 是否按本节建议启动？  
5. LLM 流式输出是否纳入近期范围？  
6. Work 模式首批是否包含 `web_search` 与本地文件写？

---

## 7. 未执行事项（本次审计范围外）

- V2 Phase 1+ 代码改造  
- push / PR / 部署  
- 继续批量爬取世界观  
- 提升 BH3Text 来源等级或 confirmed 关系  
- 修改生产数据库或用户 Memory 内容  
- 调用付费 API 或下载版权媒体

---

## Completed（审计交付物）

- [`LORE_CORPUS_V1_BASELINE.md`](LORE_CORPUS_V1_BASELINE.md) — 语料冻结基线  
- 本文档 — V2 实施前审计  
- README Lore Corpus V1 状态摘要（见 README 增补）  
- 本地审核数据同步（Git ignored）：`vector_readiness.json`、检索审核表重建  
