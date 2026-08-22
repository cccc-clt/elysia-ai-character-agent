# Elysia V2 Autonomous Blockers

## BLOCKER-001

- Task: BH3Text 10场景人工视频/游戏原文核验
- Status: `blocked_human`
- Evidence: `data/review/bh3text_transcript_verification.jsonl` 中10条记录均为 `not_checked`
- Why Codex cannot safely continue: 程序没有播放视频或访问游戏原文，不能判断说话者和台词是否一致，也不能伪造 `match`
- Work completed around the blocker: 已生成固定章节分布、3～5轮短样本、来源URL与保守视频提示；结构和质量门可继续自动验证
- Exact user action required: 逐项查看对应视频/游戏原文，填写时间点并标记 `match`、`minor_mismatch` 或 `critical_mismatch`
- Resume command: `python -m data_pipeline.cli build-bh3text`

## BLOCKER-002

- Task: 8案例检索结果的人工相关性、引用完整性与错误归因
- Status: `blocked_human`
- Evidence: `data/review/lore_retrieval_match_review.jsonl` 中8条记录均为 `not_checked`
- Why Codex cannot safely continue: gold URL命中只证明确定性对照，不能代替人对Top 5语义相关性和预期答案的判断
- Work completed around the blocker: 8/8 gold URL进入Top 5、8/8引用字段完整；3个同系列分段页面排序提示已标出
- Exact user action required: 审阅Top 5并填写 `reviewer_relevance`、引用人工状态、错误原因和最终审核状态
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
