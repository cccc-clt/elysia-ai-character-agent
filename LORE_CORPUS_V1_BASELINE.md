# Lore Corpus V1 Baseline

> **冻结声明**：本文档记录 Elysia AI Character Agent 在 V2 Agent 改造启动前冻结的世界观语料基线。Corpus V1 **不是**完整官方知识库，也不代表剧情文本已与官方游戏原文逐条对照。

---

## 1. 冻结日期

**2026-08-23**（UTC+8）

---

## 2. Git 基线

| 项 | 值 |
|---|---|
| 分支 | `codex/v1.1-stabilization` |
| HEAD | `34534846e761dc47bcdeb2de35c2ec8f21831d1b` |
| 说明 | 含两轮 Lore RAG 稳定化成果；`main`（`d4a13f5`）仅部分合并，完整代码与文档以本分支为 V2 开发基线 |

---

## 3. 语料规模（本地实测，2026-08-23）

| 指标 | 数量 | 主要路径 |
|---|---:|---|
| BH3Text 文档 | 138 | `data/raw/bh3text_pages.jsonl` |
| BH3Text 清洗对话文档 | 138 | `data/cleaned/bh3text_dialogues.jsonl` |
| 对话轮次 | 5597 | 同上 `turns` 字段合计 |
| BH3Text chunks | 201 | `data/chunks/bh3text_lore_chunks.jsonl` |
| 对话证据边 | 2060 | `data/relations/dialogue_evidence_edges.jsonl` |
| 10 场景核验包 | 10 | `data/review/bh3text_transcript_verification.jsonl` |
| 8 案例检索审核 | 8 | `data/review/lore_retrieval_match_review.jsonl` |
| 自动化测试 | 141 | `python -m pytest --collect-only -q` |

---

## 4. 来源等级与语料分布

摘自 `data/manifests/source_inventory.json`（`generated_at` 以文件为准）：

| Corpus | 文档 | Chunks | 来源等级 | 官方托管 |
|---|---:|---:|---|---|
| `official_lore` | 3 | 16 | Tier A | 是（`baike.mihoyo.com`） |
| `bh3text_dialogue` | 138 | 201 | Tier B-primary-transcript | 否（社区托管 `bh3text.com`） |
| `story_navigation` | 6 | 6 | Tier B-curated-index | 否（BH3Helper 导航元数据） |
| `video_evidence` | 4 | 0 | — | 否（元数据/审核，无 chunk） |

**Tier A 合计**：3 官方文档 / 16 chunks（爱莉希雅官方百科相关页）。

**Tier B 合计**：BH3Text 201 chunks + 剧情导航 6 chunks。BH3Text **不得**标记为官方来源或 Tier A。

---

## 5. 已覆盖范围（摘要）

### 角色（`lore_coverage_matrix.json` calibration `usable`）

伊甸、华、格蕾修、梅比乌斯、樱、爱莉希雅、终焉、维尔薇、逐火之蛾（组织/概念）

### 角色（`thin` — 有材料但偏薄）

人之律者、凯文、始源之律者、科斯魔、记忆体、逐火十三英桀、阿波尼亚

### 组织与概念

逐火十三英桀、逐火之蛾、往世乐土相关章节（通过 BH3Text 主线 29—31 与 ER 篇章材料）

### 章节与篇章（BH3Text 采样核验覆盖）

- 往世乐土：`在无限的阴影之中`、`致世界上的另一个我`、`愿时光永驻此刻，愿明日——`
- 主线第一部：第二十九章《来自乐土》、第三十章《英雄们的葬礼》、第三十一章《因你而在的故事》（含黄金庭院、档案室、维尔薇篇、乐土永存等场景）

### 官方设定页（Tier A）

粉色妖精小姐 / 真我·人之律者 / 始源之律者 等官方百科切片（3 文档 → 16 chunks）

---

## 6. 当前缺失或薄弱主题

`calibration_baseline_statuses` 标记为 **`missing`**：

侵蚀之律者、前文明、千劫、帕朵菲莉丝、往世乐土（作为独立主题）、梅博士、永世乐土、约束惨剧、苏、融合战士、雷电芽衣

标记为 **`thin`**（需问题驱动增量，非全量爬取）：

人之律者、凯文、始源之律者、科斯魔、记忆体、逐火十三英桀、阿波尼亚

实体合并边界仍 **pending / blocked_human**（不得自动合并）：

爱莉希雅 ↔ 真我·人之律者 / 粉色妖精小姐♪ / 妖精爱莉；维尔薇 ↔ 各人格称谓；单字歧义 `华/樱/苏`。

---

## 7. 人工审核方式（10 场景 + 8 案例）

| 材料 | 数量 | 审核方式 | 复查策略 |
|---|---:|---|---|
| BH3Text 场景核验 | 10 | 10/10 `match`；场景 1 为监督流程逐项接受；场景 2—10 为 `review_method=user_bulk_accept` | `recheck_policy=review_on_issue` |
| 检索匹配审核 | 8 | 8/8 `review_status=user_bulk_accepted`；`review_method=user_bulk_accept` | `review_on_issue` |

**未声称**：逐场景对照官方录像或游戏原文；未填写视频时间点（除建议 part 提示外均为空）。

**保留**：8 案例中 `LRAG-REL-001`、`LRAG-REL-002`、`LRAG-REL-008` 的同系列页面排序风险；Top 5 排序与自动分数未因批量接受而修改。

---

## 8. 检索后端状态

| 组件 | 状态 | 证据 |
|---|---|---|
| BM25 | 已实现，默认参与 hybrid | `src/lore/retrieval.py` |
| Hashed vector (`hashed-char-ngram-v1`) | 已实现，默认向量后端 | `src/lore/embeddings.py`, `data/lore_index/hashed_vectors.json`（Git ignored） |
| Hybrid RRF | 已实现 | `src/lore/retrieval.py` |
| Semantic adapter (`sentence-transformers`) | 可选；`requirements-semantic.txt` 隔离；模型缺失时降级 BM25 | `src/lore/embeddings.py`, `tests/test_lore_semantic_backend.py` |
| 聊天接入 | 模块存在；**默认关闭** | `app.py` + `LORE_RAG_ENABLED=false` |

`vector_readiness.json`：`vector_ready=false`（存在 `user_bulk_accept` 场景时 `individual_transcript_comparison_complete=false`）。

---

## 9. 当前评测指标（40 例离线检索，hashed hybrid）

摘自 [`docs/evals/LORE_RAG_EVALUATION_REPORT.md`](docs/evals/LORE_RAG_EVALUATION_REPORT.md)：

| Run | R@1 | R@3 | R@5 | MRR | nDCG@5 | Citation | Tier 合规 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline_b_bm25 | 0.725 | 0.982 | 0.991 | 0.892 | 0.917 | 100% | 100% |
| candidate_c_hybrid | 0.779 | 0.982 | 0.991 | 0.910 | 0.928 | 100% | 100% |

原型质量门：`passed=true`（R@5≥0.80、引用 100%、fixture 泄漏 0、关键注入失败 0）。

语义离线评测：`blocked_local_model_missing`（未安装本地 BGE 时不填写语义指标）。

---

## 10. Confirmed 关系数量

**0**（`data/relations/relations_confirmed.jsonl` 为空；coverage matrix `confirmed_relations: 0`）。

---

## 11. 已知风险

1. **Tier B 转录**：BH3Text 为社区托管，非官方原文；批量接受不等于官方验证。
2. **向量门未开**：`vector_ready=false`；不得将 hashed/semantic 评测通过等同于生产向量索引资格。
3. **同系列排序**：3 个检索案例 gold 页面不在 Rank 1（见 §7）。
4. **语义路径未验证**：本地 semantic 模型未安装时仅 hashed+BM25；不得声称神经语义已上线。
5. **实体/关系边界**：歧义实体与 pending 关系未人工确认，检索不得推断 confirmed 人物关系。
6. **语料 Git 忽略**：运行时 raw/cleaned/chunks/索引/审核 JSONL 不进入版本库；环境重建需保留本地 `data/` 或按管线文档再生。
7. **分支漂移**：`main` 落后本分支；V2 应以 `codex/v1.1-stabilization` 为代码基线直至用户决定合并策略。

---

## 12. `review_on_issue` 复查机制

- 用户已批量接受当前 10 场景与 8 检索案例，**不再逐项审核**。
- 实际聊天或检索使用中若出现：错误引用、错误排序召回、转录明显偏差、来源等级误标，则：
  1. 记录 case_id / scene `verification_id` / 用户输入；
  2. 针对性重跑 `build-review` 或单场景核验包；
  3. **不得**因单次问题自动提升 Tier、确认关系或打开 `vector_ready`。
- 审核材料路径：`data/review/`（Git ignored）；任务状态见 [`docs/autonomous/HUMAN_RETURN_CHECKLIST.md`](docs/autonomous/HUMAN_RETURN_CHECKLIST.md)。

---

## 13. `LORE_RAG_ENABLED` 默认状态

**`false`**（[`src/config.py`](src/config.py) `_env_bool("LORE_RAG_ENABLED", "false")`；[`.env.example`](.env.example) 同步）。

关闭时聊天走原有 Prompt + Memory 路径，不注入 Lore 上下文（见 `tests/test_lore_rag.py::test_lore_rag_is_disabled_by_default_contract`）。

---

## 14. Corpus V1 不是完整官方知识库

本冻结包是 **fan-made、non-commercial** 技术演示用的**局部**世界观语料：

- 不包含全部主线/活动/漫画/官方档案；
- 不包含官方美术、配音或受版权保护的大段正文入库；
- BH3Text 与 BH3Helper 为社区索引/转录，**非** miHoYo / HoYoverse 官方发布；
- 不得将 Corpus V1 对外表述为「官方知识库」或「已核验官方剧情」。

---

## 15. 后续语料策略

从 Corpus V1 冻结日起：

- **停止**全量世界观爬取与无目标扩库；
- **仅允许**问题驱动增量：针对 §6 缺失主题、bad case 或检索失败案例，经用户授权后定向补采/补审；
- 任何增量须保留来源等级、审核状态与 `review_on_issue` 兼容记录；
- V2 Agent 改造见 [`ELYSIA_V2_PRE_IMPLEMENTATION_AUDIT.md`](ELYSIA_V2_PRE_IMPLEMENTATION_AUDIT.md)。

---

## 相关文档

- 架构：[`docs/architecture/LORE_RAG_ARCHITECTURE.md`](docs/architecture/LORE_RAG_ARCHITECTURE.md)
- ADR：[`docs/decisions/ADR_LORE_RETRIEVAL_BACKEND.md`](docs/decisions/ADR_LORE_RETRIEVAL_BACKEND.md)
- 第二轮稳定化：[`docs/autonomous/SECOND_STABILIZATION_REPORT.md`](docs/autonomous/SECOND_STABILIZATION_REPORT.md)
- V2 计划：[`ELYSIA_V2_AGENT_UPGRADE_PLAN.md`](ELYSIA_V2_AGENT_UPGRADE_PLAN.md)
