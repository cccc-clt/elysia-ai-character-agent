# Elysia V2 Second Stabilization Report

## Outcome

本轮完成标准已经达到：人工核验材料完整、8案例检索审核可逐项追溯、metadata完整性已校准、真实中文semantic backend可替换，且模型/索引不可用时BM25与原聊天降级可靠。状态没有被强行全部改绿。

| Status | Outcome |
|---|---|
| Implemented | 10场景增强核验包、8案例审核工作台、章节/别名/去重完整性审计、sentence-transformers本地adapter、dense cosine index、离线semantic评测编排 |
| Verified | 138 BH3Text文档、201 chunks、5597 turns、2060证据边；10/10场景与8/8检索案例已记录用户接受；8/8 gold URL Top 5；当前hashed 40例评测门通过 |
| Prototype only | hashed与semantic向量路径、BH3Text检索、聊天Lore接入；全部保持production disabled |
| Blocked for human review | 逐场视频/游戏原文比对与时间点、4类语义实体边界、任何未来关系确认、semantic模型质量及正式启用决策 |
| Not performed | 新增抓取、模型下载、付费API、正式向量库、部署、push、PR、数据库迁移、人工状态伪造 |

## Baseline and branch audit

- Branch: `codex/v1.1-stabilization`，没有直接在main工作。
- 起始时确认4个本地提交：`c94bbdf`、`8533381`、`7a0451a`、`5d32e86`。
- 本轮增加5个功能检查点与本报告文档检查点，完成后相对remote共有10个本地提交；未push。
- 起始基线：122 tests passed；第二轮交接时139 tests passed；2026-08-23批量决策同步后141 tests passed。
- Git commit均成功。每次commit后的自动geometric repack仍出现本机 `.git` maintenance权限提示；提交对象与branch引用未丢失。

## Implemented

### 1. Ten-scene verification packet

Git ignored的以下运行材料已重新生成：

- `data/review/bh3text_transcript_verification.jsonl`；
- `data/review/bh3text_transcript_verification.md`。

10/10场景均包含：篇章、章节、相邻上下文、角色列表、BH3Text原始URL、来源等级、5轮短证据、5项待确认内容、视频/P提示和空时间点。2026-08-23，用户终止逐项流程并接受当前材料：场景1保留原监督接受记录，场景2—10标记 `match` 并记录 `review_method=user_bulk_accept`、`recheck_policy=review_on_issue`。

该决定没有声明逐场景播放录像或核对游戏原文，所有视频时间点仍为空，场景2—10的五项逐条比对框也保持未勾选。所有文档继续是 `Tier B-primary-transcript / unverified_transcript`，不会因此成为Tier A、官方原文或confirmed关系。

章节分布保持固定的 `2/1/1/2/2/2`：往世乐土第一/二/三阶段和主线29/30/31章。待审核场景为：

1. 千劫-关于自身·其四
2. 华-关于爱莉希雅·其一
3. 梅比乌斯-关于自身·其三
4. 爱莉希雅-关于至深之处·其一
5. 「我们」的开始-黄金庭院
6. 往昔的记忆-一段过往
7. 维尔薇篇-一些往事
8. 维尔薇篇-尘埃落定
9. 乐土永存-少女初成
10. 乐土永存-当日赠别

### 2. Eight-case retrieval review workbench

命令 `python -m src.lore.cli build-review --include-unverified-transcripts` 生成Git ignored的JSONL/Markdown审核表。每条记录包含query、预期答案、Top 5、来源等级、gold URL自动命中、引用字段完整性、人工相关性、人工错误原因和总审核状态。

- automatic gold URL in Top 5: `8/8`；
- automatic citation complete: `8/8`；
- user bulk accepted: `8/8`；
- individually scored Top 5 results: `0/40`；
- 需特别判断的同系列页面排序：`LRAG-REL-001` gold rank 2、`LRAG-REL-002` rank 3、`LRAG-REL-008` rank 3。

8个案例的总审核状态记录为 `user_bulk_accepted`，但自动gold/引用字段保持独立，40个 `reviewer_relevance` 仍为 `not_checked`。用户接受没有改动Top 5、gold URL、来源、引用或排序，也没有消除上述3个同系列页面排序风险。

### 3. Entity, chapter, and dedup integrity

新增 `data_pipeline/lore_integrity.py`，并将审计接入source inventory。当前幂等重建结果：

- 章节URL归属检查：138文档，remaining mismatch `0`；
- duplicate document IDs `0`；duplicate chunk IDs `0`；
- normalized source URL duplicate groups `0`；
- normalized dialogue text duplicate groups `0`；
- BH3Text counted as official `0`；confirmed relations generated `0`。

可安全修复的表面名称和章节metadata由规则完成；单字实体 `华/樱/苏` 仅在明确角色上下文生成检索token，避免把“才华”等普通词误判。下列语义边界没有自动合并：爱莉希雅与真我·人之律者、粉色妖精小姐♪、妖精爱莉，以及维尔薇的多个人格/称谓。

### 4. Swappable local semantic backend

外部interface仍是 `LoreRAG.retrieve(query)`。新增的内部seam包括：

- `EmbeddingBackend` protocol；
- `SentenceTransformerEmbeddingBackend`：惰性加载、默认CPU、默认 `local_files_only=true`；
- `SemanticVectorIndex`：normalized dense cosine、模型/backend/维度/corpus signature/chunk metadata hash；
- `SemanticVectorRetriever`；
- `LORE_RAG_VECTOR_BACKEND=hashed|sentence-transformers`；
- 模型缺失时 `semantic_model_unavailable -> bm25_fallback`；索引缺失/损坏/过期/模型不匹配时保留原BM25降级；hybrid仍使用RRF。

语义依赖隔离在 `requirements-semantic.txt`。默认requirements、默认hashed行为和 `LORE_RAG_ENABLED=false` 不变。

### 5. Offline semantic evaluation

`python -m src.lore.cli evaluate-semantic` 强制本地文件模式，对当前223 eligible chunks尝试建立semantic index并复用固定40题评测。当前真实执行结果：

- status: `blocked_local_model_missing`；
- model: `BAAI/bge-small-zh-v1.5`；
- local_files_only: `true`；
- semantic index created: `false`；
- semantic metrics: `null`；
- paid API calls: `0`。

因此只验证了adapter/编排/降级，不宣称真实中文语义质量。机器可读结论在 `evals/lore_semantic_evaluation.json`，说明在 `docs/evals/LORE_SEMANTIC_BACKEND_EVALUATION.md`。

## Verified

### Current data and source guards

| Item | Actual |
|---|---:|
| BH3Text documents | 138 |
| BH3Text dialogue/narration turns | 5597 |
| BH3Text chunks | 201 |
| Evidence edges | 2060 |
| Pending semantic relations | 0 |
| Confirmed semantic relations | 0 |
| Official documents | 3 |
| Official chunks | 16 |
| BH3Text official contribution | 0 |
| Navigation chunks | 6 |
| Test fixture hits | 0 |

所有201个BH3Text chunks仍是 `Tier B-primary-transcript / unverified_transcript`。BH3Helper正文没有进入BH3Text chunks，B站元数据仍只用于潜在线索。

### Current deterministic retrieval evaluation

重新执行当前hashed 40题评测后的结果：

| Run | R@1 | R@5 | MRR | nDCG@5 | Citation | Tier | Duplicate |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.725 | 0.991 | 0.892 | 0.917 | 100% | 100% | 0 |
| Hashed hybrid + RRF | 0.779 | 0.991 | 0.910 | 0.928 | 100% | 100% | 0 |

No-answer precision为100%，fixture leakage和critical prompt-injection failure均为0。以上是本地确定性检索指标，不是答案级人工正确率，也不是semantic embedding指标。

### Tests run

- `python -m pytest -q` → `141 passed`（2026-08-23批量决策同步后）；
- `python -m compileall app.py src data_pipeline` → passed；
- `git diff --check` → passed（仅Windows行尾提示）；
- `python -m src.lore.evaluation` → current hashed 40-case gate passed；
- `python -m src.lore.cli evaluate-semantic` → expected non-zero blocked state，报告生成成功；
- 第二轮交接时 `build-bh3text`、`build-coverage`、`build-source-inventory`、`status` 均已完成；2026-08-23批量决策同步后重新执行 `build-bh3text`，`vector_ready` 仍为false。

## Prototype only

- Chat Lore接入仍由feature flag控制，默认关闭。
- 未核验BH3Text只有同时启用prototype与explicit allow flag才进入开发检索。
- hashed索引和未来semantic索引均位于Git ignored运行目录，并标记production disabled。
- 40例自动门只允许继续原型开发，不会修改人工 `vector_readiness`。

## Blocked for human review

1. 只有实际检索或回答暴露问题时，才按场景或检索案例复查；当前未逐场填写视频时间点。
2. 判断4类角色/形态/人格语义alias是否合并；当前继续pending。
3. 审核任何未来pending关系；本次confirmed关系仍为0。
4. 若要重新判断剧情向量索引资格，仍需完成逐场转录比对门；用户批量接受材料不能替代该门。
5. semantic模型安装与真实质量评测、`LORE_RAG_ENABLED`、push、PR及部署仍须用户另行授权。

## Not performed

- 未扩大BH3Text/BH3Helper/B站或任何其他来源抓取规模。
- 未下载B站视频、模型、官方素材或完整剧情到Git。
- 未调用付费embedding、LLM judge或批处理API。
- 未接入Qdrant、pgvector、FAISS、Chroma或正式向量服务。
- 未修改数据库schema、Memory、用户数据、Prompt人格规则、语音或UI。
- 未把BH3Text提升为Tier A，未把证据边转为语义关系，未自动确认任何关系。
- 未伪造逐场视频时间点、逐结果0—3相关性评分或官方交叉核验记录。
- 未部署、push或创建PR。

## Security and privacy review

- 新配置只有模型名/backend/device/local-only和Git ignored索引路径，不含凭据。
- CLI显示外部本地模型路径时使用占位符，避免记录用户绝对路径。
- corpus、dense vectors、详细结果与含剧情证据的人工审核包继续Git ignored。
- 没有读取或提交 `.env`、cookie、token、用户Memory、聊天历史、音频或数据库。

## Risks

- 默认BGE模型未实际运行，真实中文语义质量、内存、冷启动和部署资源仍未知。
- 8案例gold URL是页面级评测设计；用户整体接受当前Top 5不等于40个结果均获得逐项相关性评分。
- `match` 中的9项来自用户批量接受材料，不代表已逐场景对照官方录像或游戏原文；相关门因此保持false。
- 单字角色名和维尔薇人格称谓若被错误人工合并，可能污染实体召回与未来关系图。
- 本地Git geometric repack权限提示未修复；目前不影响commit引用，但属于机器级维护问题。

## Rollback

每阶段均有独立本地commit，可按逆序使用非破坏性的 `git revert <commit>`：

- `5a75b2b`：离线semantic评测与缺模报告；
- `2c0f25d`：本地semantic adapter；
- `1e89595`：metadata完整性与检索校准；
- `5d95d62`：8案例审核工作台；
- `45f38c5`：10场景增强核验包。

关闭 `LORE_RAG_ENABLED` 或保持默认false即可绕过整个Lore接入。删除Git ignored的本地semantic index只会触发BM25降级，不影响SQLite、Memory或聊天数据。

## Suggested commit

`docs: finalize second lore rag stabilization handoff`

## Portfolio evidence

- 保存10场景核验包字段结构截图，遮蔽长台词，只展示URL、来源等级和审核门；目标 `docs/portfolio/04_test_data/`。
- 保存8案例Top 5审核表与3个排序提示；目标 `docs/portfolio/05_bad_cases/`。
- 保存semantic adapter/RRF/BM25降级架构图与缺模报告；目标 `docs/portfolio/02_flow_and_prototype/`、`06_iteration_records/`。
- 状态必须标注 `Prototype only`、`User bulk accepted / not individually compared` 和 `Not verified against official footage`，不得展示为已部署或官方核验通过。
