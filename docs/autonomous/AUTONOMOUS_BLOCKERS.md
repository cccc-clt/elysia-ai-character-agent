# Elysia V2 Autonomous Blockers

## BLOCKER-001

- Task: BH3Text 10场景人工视频/游戏原文核验
- Status: `resolved_by_user_bulk_accept_with_limitations`
- Evidence: 10/10场景为 `match`；场景2—10备注含 `review_method=user_bulk_accept`，所有视频时间点仍为空
- Decision boundary: 用户接受当前材料并改为 `review_on_issue`，没有声称逐场对照视频或游戏原文；BH3Text仍为Tier B，`vector_ready`仍为false
- Work completed around the blocker: 固定章节分布、3～5轮短样本、来源URL、保守视频提示和用户决策均已记录
- Future action: 只有实际检索/回答发现问题，或另行决定开放向量门时，才按场景填写真实时间点与差异
- Resume command: `python -m data_pipeline.cli build-bh3text`

## BLOCKER-002

- Task: 8案例检索结果的人工相关性、引用完整性与错误归因
- Status: `resolved_by_user_bulk_accept_with_limitations`
- Evidence: 8/8总审核状态为 `user_bulk_accepted`；40个逐结果相关性字段仍为 `not_checked`
- Decision boundary: 用户接受当前Top 5与现阶段排序，但没有伪造逐条0—3分；自动指标与用户决定分开记录
- Work completed around the blocker: 8/8 gold URL进入Top 5、8/8引用字段完整；3个同系列分段页面排序风险继续保留
- Future action: 实际回答出现误召回、错误引用或系列页排序问题时，按案例复查
- Resume command: `python -m src.lore.cli build-review --include-unverified-transcripts`

## BLOCKER-003

- Task: 角色语义别名与维尔薇人格/称谓实体边界
- Status: `blocked_human`
- Evidence: `data/manifests/lore_integrity_audit.json` 的 `semantic_alias_candidates` 和 `speaker_variants`
- Why Codex cannot safely continue: 身份、装甲、剧情形态、人格或称谓是否属于同一实体是领域判断；自动合并可能伪造关系或污染召回
- Work completed around the blocker: 安全文字归一化、章节URL归属、精确URL/正文/ID去重已自动完成；语义alias自动合并数保持0
- Exact user action required: 审阅4类semantic alias建议及speaker variants，逐项决定merge/keep-separate
- Resume command: `python -m data_pipeline.cli build-source-inventory`

## BLOCKER-004

- Task: 默认真实中文semantic模型的40例质量评测
- Status: `blocked_local_dependency`
- Evidence: `evals/lore_semantic_evaluation.json` 为 `blocked_local_model_missing`，223 eligible chunks，metrics=null
- Why Codex cannot safely continue: 当前本地缓存没有 `BAAI/bge-small-zh-v1.5`；本轮不允许隐式下载或远端付费embedding调用
- Work completed around the blocker: 可替换adapter、dense索引、CLI、40例离线编排和缺模BM25降级均已实现并测试
- Exact user action required: 明确选择并本地安装允许的中文sentence-transformers模型；这不影响先完成其他人工审核
- Resume command: `python -m src.lore.cli evaluate-semantic`
