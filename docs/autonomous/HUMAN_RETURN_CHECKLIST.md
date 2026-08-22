# Human Return Checklist

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
- [ ] 决定是否打开 `LORE_RAG_ENABLED`。
- [ ] 决定是否push、创建PR或部署。

在上述人工项完成前，所有转录检索能力只能标记为开发原型，正式启用必须保持关闭。

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
