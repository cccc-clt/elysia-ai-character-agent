# Human Return Checklist

## Current gate snapshot

- transcript scenes: `10 generated / 0 reviewed / 0 match / 0 critical_mismatch`;
- each scene packet: chapter、上下文、角色、原始BH3Text URL、5轮短证据、5项待确认内容均已生成；
- retrieval review: `8 generated / 8 gold URL in Top 5 / 8 citation-complete / 0 human-reviewed`;
- vector readiness: `false`；数量门已满足，但人工核验门未满足；
- semantic evaluation: `blocked_local_model_missing`；223 eligible chunks，指标为null，未创建semantic index；
- source guard: BH3Text official document count `0`，confirmed relations `0`。

- [ ] 人工核验10个BH3Text场景，并填写视频时间点。
- [ ] 至少8个场景标记为 `match`。
- [ ] 确认 `critical_mismatch = 0`。
- [ ] 审核实体别名合并建议。
- [ ] 审核所有 pending 语义关系；0条也是允许结果。
- [ ] 检查26个官方候选外链的发布主体。
- [ ] 检查BH3Helper角色/英桀档案的来源边界。
- [ ] 决定是否允许正式启用未核验社区转录。
- [ ] 审阅向量后端ADR和部署持久化限制。
- [ ] 审阅RAG评测报告及失败样本。
- [ ] 审阅8案例检索匹配表，填写人工相关性、引用完整性与错误原因。
- [ ] 重点判断3个同系列分段页面排序案例：`LRAG-REL-001`、`LRAG-REL-002`、`LRAG-REL-008`。
- [ ] 明确安装允许的本地中文embedding模型后，重跑离线语义评测；当前不得填写语义质量结论。
- [ ] 决定是否打开 `LORE_RAG_ENABLED`。
- [ ] 决定是否push、创建PR或部署。

在上述人工项完成前，所有转录检索能力只能标记为开发原型，正式启用必须保持关闭。

完整核验材料由 `python -m data_pipeline.cli build-bh3text` 生成到：

- `data/review/bh3text_transcript_verification.jsonl`：机器可读记录；
- `data/review/bh3text_transcript_verification.md`：逐场人工核验包。

每个场景均包含篇章、章节、场景上下文、角色、BH3Text原始URL、3～5轮短证据和5项待确认内容。两份文件包含未核验剧情片段，因此继续保持Git ignored；本清单只提交任务状态和定位信息。

8案例检索审核材料由 `python -m src.lore.cli build-review --include-unverified-transcripts` 生成到 `data/review/lore_retrieval_match_review.jsonl` 和 `.md`。表中自动字段只表示gold URL、来源等级和引用链接的确定性对照；人工相关性、人工错误原因和总审核状态不会由程序填写。

当前自动对照的8/8案例均在Top 5命中gold URL并具有完整URL/来源等级。`LRAG-REL-001`、`LRAG-REL-002`、`LRAG-REL-008` 的gold页面分别排第2、3、3；这只是同系列分段页面排序提示，不会由程序填写“相关”或“错误原因”。

角色/实体完整性审计位于Git ignored的 `data/manifests/lore_integrity_audit.json` 和 `.md`。章节归属已按已发现URL规则校准，当前138文档剩余mismatch为0，document/chunk/规范化URL/规范化正文重复组均为0。下列语义边界必须保留给人工判断，程序没有自动合并：

- 爱莉希雅 ↔ 真我·人之律者；
- 爱莉希雅 ↔ 粉色妖精小姐♪；
- 爱莉希雅 ↔ 妖精爱莉；
- 维尔薇 ↔ “极恶/专家/大魔术师”等人格或称谓。

单字实体 `华/樱/苏` 继续作为歧义metadata供审核；检索只在明确角色上下文生成实体token，不能把“才华”等普通词当作角色华。

本地semantic评测命令是 `python -m src.lore.cli evaluate-semantic`。当前机器没有默认BGE模型，结果记录在 `evals/lore_semantic_evaluation.json` 和 `docs/evals/LORE_SEMANTIC_BACKEND_EVALUATION.md`。在模型明确安装前不要修改 `semantic_metrics: null`；模型可用后即使40例通过，仍不能替代本页10场景人工门。

## Current 10-scene verification queue

| Scene | Chapter | Suggested video/part | Current status |
|---|---|---|---|
| 千劫-关于自身·其四 | 在无限的阴影之中 | BV1MZ4y167RP / P7 | not_checked |
| 华-关于爱莉希雅·其一 | 在无限的阴影之中 | BV1MZ4y167RP / P10 | not_checked |
| 梅比乌斯-关于自身·其三 | 致世界上的另一个我 | BV1MZ4y167RP / P6 | not_checked |
| 爱莉希雅-关于至深之处·其一 | 愿时光永驻此刻，愿明日—— | BV1MZ4y167RP / P2 | not_checked |
| 「我们」的开始-黄金庭院 | 第二十九章 来自乐土 | BV1B44y1g7j7 / 待选P | not_checked |
| 往昔的记忆-一段过往 | 第二十九章 来自乐土 | BV1B44y1g7j7 / 待选P | not_checked |
| 维尔薇篇-一些往事 | 第三十章 英雄们的葬礼 | 待人工指定视频/P | not_checked |
| 维尔薇篇-尘埃落定 | 第三十章 英雄们的葬礼 | 待人工指定视频/P | not_checked |
| 乐土永存-少女初成 | 第三十一章 因你而在的故事 | 待人工指定视频/P | not_checked |
| 乐土永存-当日赠别 | 第三十一章 因你而在的故事 | 待人工指定视频/P | not_checked |

程序只根据章节标题和已审计视频元数据给出保守提示；没有章节明确匹配的视频保持空白，不能仅凭角色名强行映射。
