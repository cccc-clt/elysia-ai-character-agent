# Human Return Checklist

## Current gate snapshot

- transcript scenes: `10 generated / 10 user-accepted / 10 match / 0 critical_mismatch`；场景1保留逐项监督接受结果，场景2—10记录为 `user_bulk_accept`；
- transcript comparison evidence: `0 video timestamps`；用户没有声明逐场景对照官方录像或游戏原文；
- each scene packet: chapter、上下文、角色、原始BH3Text URL、5轮短证据、5项待确认内容均已生成；
- retrieval review: `8 generated / 8 user_bulk_accepted / 8 gold URL in Top 5 / 8 citation-complete / 0 individually scored results`；
- vector readiness: `false`；数量和用户决策记录已满足，但逐场景转录比对门明确未满足；
- semantic evaluation: `blocked_local_model_missing`；223 eligible chunks，指标为null，未创建semantic index；
- source guard: BH3Text official document count `0`，confirmed relations `0`。

- [x] 记录用户对10个BH3Text场景材料的接受决定；其中9项为 `user_bulk_accept`。
- [x] 10个场景标记为 `match`，但这不表示逐条视频时间点核验。
- [x] 确认 `critical_mismatch = 0`。
- [ ] 审核实体别名合并建议。
- [ ] 审核所有 pending 语义关系；0条也是允许结果。
- [ ] 检查26个官方候选外链的发布主体。
- [ ] 检查BH3Helper角色/英桀档案的来源边界。
- [ ] 决定是否允许正式启用未核验社区转录。
- [ ] 审阅向量后端ADR和部署持久化限制。
- [ ] 审阅RAG评测报告及失败样本。
- [x] 用户整体接受8案例当前Top 5与现阶段排序；逐结果相关性仍保持 `not_checked`。
- [x] 保留3个同系列分段页面排序风险：`LRAG-REL-001`、`LRAG-REL-002`、`LRAG-REL-008`。
- [ ] 明确安装允许的本地中文embedding模型后，重跑离线语义评测；当前不得填写语义质量结论。
- [ ] 决定是否打开 `LORE_RAG_ENABLED`。
- [ ] 决定是否push、创建PR或部署。

批量接受采用 `review_method=user_bulk_accept`、`recheck_policy=review_on_issue`。它结束逐项展示流程，但不等于逐场对照录像、来源升级、实体/关系确认或正式启用授权；所有转录检索能力仍只能标记为开发原型。

完整核验材料由 `python -m data_pipeline.cli build-bh3text` 生成到：

- `data/review/bh3text_transcript_verification.jsonl`：机器可读记录；
- `data/review/bh3text_transcript_verification.md`：逐场人工核验包。

每个场景均包含篇章、章节、场景上下文、角色、BH3Text原始URL、3～5轮短证据和5项待确认内容。场景2—10的备注明确写入用户批量接受与按问题复查策略；未填写视频时间点的确认框不会被伪装成逐项录像核验。两份文件继续保持Git ignored；本清单只提交任务状态和定位信息。

8案例检索审核材料由 `python -m src.lore.cli build-review --include-unverified-transcripts` 生成到 `data/review/lore_retrieval_match_review.jsonl` 和 `.md`。Top 5身份与顺序不变时生成器会保留已有用户决定；结果发生变化时会把总体接受状态重置为待审核。自动gold/引用字段与 `user_bulk_accepted` 分开记录，Top 5逐结果 `reviewer_relevance` 继续为 `not_checked`，没有伪造0—3分。

当前自动对照的8/8案例均在Top 5命中gold URL并具有完整URL/来源等级。用户接受当前结果，但 `LRAG-REL-001`、`LRAG-REL-002`、`LRAG-REL-008` 的gold页面仍分别排第2、3、3；该风险没有因为批量接受而消失，实际使用出现误召回或引用错误时按案例复查。

角色/实体完整性审计位于Git ignored的 `data/manifests/lore_integrity_audit.json` 和 `.md`。章节归属已按已发现URL规则校准，当前138文档剩余mismatch为0，document/chunk/规范化URL/规范化正文重复组均为0。下列语义边界必须保留给人工判断，程序没有自动合并：

- 爱莉希雅 ↔ 真我·人之律者；
- 爱莉希雅 ↔ 粉色妖精小姐♪；
- 爱莉希雅 ↔ 妖精爱莉；
- 维尔薇 ↔ “极恶/专家/大魔术师”等人格或称谓。

单字实体 `华/樱/苏` 继续作为歧义metadata供审核；检索只在明确角色上下文生成实体token，不能把“才华”等普通词当作角色华。

本地semantic评测命令是 `python -m src.lore.cli evaluate-semantic`。当前机器没有默认BGE模型，结果记录在 `evals/lore_semantic_evaluation.json` 和 `docs/evals/LORE_SEMANTIC_BACKEND_EVALUATION.md`。在模型明确安装前不要修改 `semantic_metrics: null`；用户批量接受也不构成真实semantic质量结论或逐场景转录比对门。

## Current 10-scene verification queue

| Scene | Chapter | Suggested video/part | Current status | Review method |
|---|---|---|---|---|
| 千劫-关于自身·其四 | 在无限的阴影之中 | BV1MZ4y167RP / P7 | match | supervised user accept；无时间点 |
| 华-关于爱莉希雅·其一 | 在无限的阴影之中 | BV1MZ4y167RP / P10 | match | user_bulk_accept；无时间点 |
| 梅比乌斯-关于自身·其三 | 致世界上的另一个我 | BV1MZ4y167RP / P6 | match | user_bulk_accept；无时间点 |
| 爱莉希雅-关于至深之处·其一 | 愿时光永驻此刻，愿明日—— | BV1MZ4y167RP / P2 | match | user_bulk_accept；无时间点 |
| 「我们」的开始-黄金庭院 | 第二十九章 来自乐土 | BV1B44y1g7j7 / 待选P | match | user_bulk_accept；无时间点 |
| 往昔的记忆-一段过往 | 第二十九章 来自乐土 | BV1B44y1g7j7 / 待选P | match | user_bulk_accept；无时间点 |
| 维尔薇篇-一些往事 | 第三十章 英雄们的葬礼 | 待人工指定视频/P | match | user_bulk_accept；无时间点 |
| 维尔薇篇-尘埃落定 | 第三十章 英雄们的葬礼 | 待人工指定视频/P | match | user_bulk_accept；无时间点 |
| 乐土永存-少女初成 | 第三十一章 因你而在的故事 | 待人工指定视频/P | match | user_bulk_accept；无时间点 |
| 乐土永存-当日赠别 | 第三十一章 因你而在的故事 | 待人工指定视频/P | match | user_bulk_accept；无时间点 |

程序只根据章节标题和已审计视频元数据给出保守提示；没有章节明确匹配的视频保持空白，不能仅凭角色名强行映射。
