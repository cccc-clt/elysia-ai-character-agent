# Elysia V2 Autonomous Progress

| Task ID | Task | Status | Evidence | Blocker | Commit |
|---|---|---|---|---|---|
| A | 建立执行台账与本地检查点 | completed | `docs/autonomous/PREFLIGHT_REPORT.md`；101 tests passed | 无 | `c94bbdf` |
| B | BH3Text章节均衡补采 | completed | 100 → 138 documents；主线31章 0 → 15 | 无 | `c94bbdf` |
| C | 均衡核验包与结构门 | completed_with_limitations | 10 samples，2/1/1/2/2/2；初始均为 `not_checked`，2026-08-23记录用户接受 | 逐场视频比对未完成 | `c94bbdf` |
| D | 来源分层、去重与追溯 | completed | `build-source-inventory`；社区计入official=0；重复ID=0 | 无 | `8533381` |
| E | 隔离Lore检索核心 | completed | `src/lore/`；官方/BH3Text/导航corpora隔离 | 无 | `8533381` |
| F | 混合检索、来源路由与引用 | completed | BM25 + hashed vector + RRF；短引用与URL校验 | 无 | `8533381` |
| G | 默认关闭的Agent接入 | completed_with_limitations | 当前聊天Prompt接入、引用和trace均受flags控制 | 完整Tool-calling Harness仍属主升级计划独立Phase | `8533381` |
| H | 候选关系与人工审核工作流 | completed_with_limitations | pending review + conflict report；实际语义关系0 | confirmed只能人工审核 | `8533381` |
| I | 40题评测与基线 | completed | current hybrid R@5=0.991；citation/tier=100%；fixture/injection=0 | 无 | `8533381`、`1e89595` |
| J | 安全、性能、降级与部署验证 | completed | current 141 tests；index约3.88MB；final p50/p95约465/584ms | 正式部署未授权 | `7a0451a`、`5a75b2b` |
| K | 文档、作品集证据与最终报告 | completed | architecture、ADR、evaluation、handoff均已生成 | 无 | 当前文档提交 |
| L | 可回滚本地commits | completed | `c94bbdf`、`8533381`、`7a0451a`及当前文档提交；未push | Git自动repack权限提示，不影响提交完整性 | 当前文档提交 |
| M | 10场景人工核验材料增强 | completed_with_user_acceptance | 10/10 match；场景2—10为user_bulk_accept，未填写视频时间点 | 问题出现时逐场复查；vector门仍false | `45f38c5` |
| N | 8案例检索审核工作台 | completed_with_user_acceptance | 8/8 user_bulk_accepted；逐结果相关性仍not_checked；3个排序风险保留 | 问题出现时按案例复查 | `5d95d62` |
| O | 别名/同名实体/章节/去重校准 | completed_with_limitations | 138章节mismatch=0；四类重复=0；安全表面归一化已实施 | 4组语义别名/人格边界需人工判断 | `1e89595` |
| P | 可替换本地中文semantic adapter | completed | sentence-transformers惰性本地adapter、dense cosine index、hashed/BM25/RRF降级保持 | 无 | `2c0f25d` |
| Q | 语义测试与离线评测 | completed_with_limitations | 缺模/索引/模型不匹配降级测试；223 eligible chunks；semantic metrics=null | 默认BGE模型未安装在本地 | `5a75b2b` |
| R | 第二轮稳定化交接 | completed | README、architecture、ADR、checklist、evaluation和第二轮报告；批量决策已同步 | 实体/关系、逐场比对、semantic与启用仍需另行决策 | 当前文档提交 |
