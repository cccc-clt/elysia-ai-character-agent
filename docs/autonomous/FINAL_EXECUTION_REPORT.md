# Elysia V2 Autonomous Execution Report

> Historical first-round report. The current second-round result is recorded in `docs/autonomous/SECOND_STABILIZATION_REPORT.md`; first-round numbers below are retained as historical evidence.

## Human supervision update — 2026-08-23

- 用户终止逐项展示流程并接受当前10个场景材料：场景1保留原结果，场景2—10记录为 `match / user_bulk_accept / review_on_issue`。
- 该决定没有逐场景对照录像或游戏原文，视频时间点仍为空；BH3Text继续为 `Tier B-primary-transcript / unverified_transcript`。
- 8/8检索案例记录为 `user_bulk_accepted`；Top 5、gold URL、引用、来源和排序未改，40个逐结果相关性字段仍为 `not_checked`。
- `LRAG-REL-001`、`LRAG-REL-002`、`LRAG-REL-008` 的同系列页面排序风险继续保留。
- `vector_ready=false`、`LORE_RAG_ENABLED=false`、confirmed关系0；实体/形态/记忆体/装备和人物关系没有自动合并或确认。
- 同步后验证：`python -m pytest -q`为141 passed，`compileall`与`git diff --check`通过。

## Outcome

本次自治执行完成了文件所列 A–L 中所有无需用户本人判断、无需外部账号且不涉及正式部署的工作。

| Status | Outcome |
|---|---|
| Implemented | BH3Text分组配额补采、均衡核验包、来源台账/去重、隔离Lore检索、BM25/本地向量/RRF、引用、默认关闭接入、关系审核、40题评测、安全降级与文档 |
| Verified | 本地结构门、来源隔离、评测开发门、122项测试、compileall、diff check |
| Prototype only | BH3Text检索、hashed-vector索引与聊天接入；默认关闭且production disabled |
| Blocked for human review | 逐场视频/游戏原文比对、confirmed关系/实体、semantic质量、正式启用与远端部署决策 |
| Not performed | push、PR、部署、付费API批处理、视频下载、破坏性迁移、人工核验伪造 |

## Completed Tasks

- A：建立预检、进度台账、阻塞台账、人工返回清单和本地检查点。
- B：实现并实际运行BH3Text `coverage-gap`，新增38个唯一页面。
- C：生成10条机器可读/Markdown均衡核验记录；自治执行时状态保持 `not_checked`，2026-08-23按用户决定更新为接受。
- D：生成四类隔离语料source inventory、hash去重与开发原型门。
- E/F：实现 `LoreRAG.retrieve(query)` 深模块、BM25、hashed vector、RRF、来源路由、引用、安全过滤和降级。
- G：在当前聊天Prompt中以默认关闭feature flags接入Lore层，保存轻量trace并附短来源列表。
- H：扩展pending关系人工审核与冲突报告；严格规则实际仍为0条语义关系。
- I：建立并实际运行40题固定评测集（无LLM judge、无付费API）。
- J：完成URL、prompt injection、来源优先、缺失/损坏索引、超时、上下文限长、fixture和Memory隔离测试；记录性能。
- K：完成架构、ADR、评测、README与交接文档。
- L：创建本地可回滚commits；未push。

## Completed with Limitations

- Lore已接入当前聊天流程，但主升级计划中的通用Function Calling `ElysiaHarness`、Tool Registry与Approval UI仍是独立后续Phase；本次没有假装它们已经实现。
- 本地向量adapter是 `hashed-char-ngram-v1` 词法稀疏向量，不是神经语义embedding。
- BH3Text转录可供显式开发原型评测，但全部仍是非官方托管。用户已接受当前材料，但没有逐场景对照录像或游戏原文；正式 `vector_ready` 保持false。
- 官方层仍只有3个有效文档/16个chunks/3个usable主题，不把BH3Text的20个usable转录主题混称为官方覆盖。
- 0条pending/confirmed语义关系是严格证据规则的真实结果，不为展示数量放宽。

## Human-blocked Tasks

- 若实际检索或回答发现问题，按场景或案例复查录像、游戏原文、章节、上下文、引用和排序。
- 若要开放独立剧情向量索引，仍需逐场转录比对证据；`user_bulk_accept` 不满足该门。
- 审核实体别名合并、26个官方候选外链、BH3Helper档案边界和任何未来pending关系。
- 决定是否允许未逐场核验的转录正式参与回答、是否运行真实semantic模型、是否开启 `LORE_RAG_ENABLED`。
- 决定push、PR与部署；当前均未执行。

## Files Changed

- `data_pipeline/`：官方/BH3Text/BH3Helper/视频管线、分组补采、覆盖、来源台账、去重和人工审核。
- `src/lore/`：隔离corpus、检索adapters、RRF、引用、安全、CLI和评测。
- `app.py`、`src/config.py`、`src/prompt_builder.py`、`.env.example`：默认关闭且可降级的Lore接入。
- `evals/lore_rag_cases.jsonl`：40题固定评测集；详细运行结果保持Git ignored。
- `tests/`：采集、配额、核验门、来源层级、关系审核、检索、安全、降级与评测测试。
- `docs/architecture/`、`docs/decisions/`、`docs/evals/`、`docs/autonomous/`、README：架构、决策、证据和交接。

## Data Coverage Before and After

### BH3Text collection

| Chapter/group | Before | Added | After |
|---|---:|---:|---:|
| 在无限的阴影之中 | 65 | 0 | 65 |
| 致世界上的另一个我 | 23 | 0 | 23 |
| 愿时光永驻此刻，愿明日—— | 10 | 5 | 15 |
| 第二十九章 来自乐土 | 1 | 9 | 10 |
| 第三十章 英雄们的葬礼 | 1 | 9 | 10 |
| 第三十一章 因你而在的故事 | 0 | 15 | 15 |
| Total documents | 100 | 38 | 138 |

- 对话/旁白轮次：1,809 → 5,597。
- BH3Text chunks：107 → 201。
- 文本证据边：495 → 2,060。
- pending语义关系：0 → 0。
- 主线31章有效页面：15。
- 采集访问：robots 200/allowed，站点根页与说明页200；未遇到403、412、429、验证码或采集错误。

### Source layers after rebuild

| Layer | Documents | Chunks | Usable topics | Official count contribution |
|---|---:|---:|---:|---:|
| Official Tier A | 3 | 16 | 3 | 3 |
| BH3Text Tier B transcript | 138 | 201 | 20 | 0 |
| Combined view | - | - | 22 | still 3 official documents |
| BH3Helper navigation | 6 | 6 | navigation only | 0 |
| Bilibili metadata | 4 | 0 | potential only | 0 |

来源台账还验证：重复document/chunk ID为0、跨corpus完全相同chunk为0、BH3Text重复正文hash组为0、fixture命中0、所有chunks有安全来源URL。6条BH3Helper→BH3Text映射只保存元数据，BH3Helper对话检索副本为0。

## Retrieval Architecture

外部interface只有 `LoreRAG.retrieve(query)`。内部按查询路由：

```text
official fact -> official_lore first, BH3Text supplemental
dialogue/plot -> bh3text_dialogue first, official cross-reference
viewing order -> story_navigation only
greeting/user memory -> no Lore retrieval
```

BM25和hashed-vector是同一retrieval seam下的两个adapters，经RRF、标题/章节和来源角色重排后生成最多Top-5；结果经过HTTPS URL校验、伪指令行过滤、短excerpt和总上下文限长，再进入独立Prompt层。MemoryService未读取或写入Lore corpus。

## Vector Backend Decision

选择本地 `hashed-char-ngram-v1` prototype adapter：2048维稀疏向量、cosine、显式build-index、无账号/模型下载、索引Git ignored。

- indexed chunks：223（16 official + 201 BH3Text + 6 navigation）
- actual build time：约855ms
- actual index size：约3.88MB
- production enabled：false

Qdrant/FastEmbed、pgvector、FAISS和Chroma均未引入；理由与未来迁移seam见 `docs/decisions/ADR_LORE_RETRIEVAL_BACKEND.md`。

## Evaluation Results

固定40题类别为6/6/8/6/6/3/3/2。

| Run | Recall@5 | MRR | nDCG@5 | Citation | Tier compliance | No-answer | p50/p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| No retrieval | 0.000 | 0.000 | 0.000 | 0% | 0% | 100% | 0/0ms |
| BM25 | 0.896 | 0.811 | 0.869 | 100% | 100% | 100% | 266/287ms |
| Hybrid | 0.950 | 0.834 | 0.876 | 100% | 100% | 100% | 607/643ms |

Hybrid分阶段p50：corpus load 0.021ms、BM25 254.913ms、vector 351.705ms、fusion 0.170ms、rerank/context 1.609ms。开发原型门通过，但该结果只衡量检索与来源合规，不是答案级正确率，也不替代人工核验。

## Safety and Source-tier Results

- feature flags默认：enabled false、unverified transcripts false、citations true。
- prompt-injection关键失败：0；检索资料显式标记为不可信数据。
- citation URL validity：100%；拒绝 `javascript:`、`file:` 和本地路径。
- source-tier compliance：100%；官方事实路由优先Tier A，社区资料不会标成官方。
- fixture leakage：0；详细结果、corpus和索引均Git ignored。
- 索引缺失/过期/损坏：BM25 fallback；corpus缺失或超时：原聊天fallback。
- 单chunk excerpt与单轮上下文有硬上限；不输出整章/整场剧情。
- 未读取 `.env` 秘密值，未新增数据库表或迁移。

## Tests Run

- Preflight `python -m pytest -q`：101 passed。
- Final `python -m pytest -q`：122 passed。
- `python -m compileall app.py src data_pipeline`：passed。
- `git diff --check`：passed（只有Windows LF/CRLF提示，不是diff错误）。
- `git fsck --no-dangling`：passed。
- `python -m src.lore.evaluation`：40题三组本地评测完成，开发原型门通过。

## Local Commits

- `c94bbdf feat: add tiered lore collection transcript and story navigation pipelines`
- `8533381 feat: add isolated hybrid lore retrieval core`
- `7a0451a perf: record lore retrieval stage timings`
- 文档、性能证据与最终交接：包含本报告的本地HEAD提交；未push。

第二次提交后Git自动geometric repack因本地 `.git` 维护权限提示失败，但提交本身成功，`git log`与`git fsck`均确认对象和引用完整。

## Not Performed

- 未push、未创建PR、未merge/rebase、未部署。
- 未修改生产域名、Secrets或远端环境。
- 未运行任何付费LLM/embedding/judge批处理。
- 未下载B站视频、音频、漫画或官方素材。
- 程序没有自动把 `not_checked` 改成 `match`；2026-08-23的状态变化来自用户明确批量决定，并在备注中标明没有逐场视频对照。
- 未把pending实体/关系自动改成confirmed。
- 未接入正式向量数据库，未开放任意shell工具。
- 未修改数据库schema、用户Memory数据或聊天历史。

## Exact Steps for the User to Resume

1. 实际使用出现章节、角色、上下文、引用或排序问题时，在两份Git ignored审核表中定位对应场景/案例并针对性复查。
2. 若复查录像或游戏原文，填写真实时间点和差异类型；不得沿用批量接受备注冒充逐场核验。
3. 审核实体/关系、26个官方候选外链和BH3Helper档案来源边界；歧义项继续pending。
4. 只有另行授权本地模型验证后，才运行真实中文semantic评测；不得伪造指标。
5. 由用户另行决定是否打开 `LORE_RAG_ENABLED`、push、PR或部署。
