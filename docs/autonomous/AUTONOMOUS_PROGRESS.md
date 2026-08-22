# Elysia V2 Autonomous Progress

| Task ID | Task | Status | Evidence | Blocker | Commit |
|---|---|---|---|---|---|
| A | 建立执行台账与本地检查点 | completed | `docs/autonomous/PREFLIGHT_REPORT.md`；101 tests passed | 无 | `c94bbdf` |
| B | BH3Text章节均衡补采 | completed | 100 → 138 documents；主线31章 0 → 15 | 无 | `c94bbdf` |
| C | 均衡核验包与结构门 | completed_with_limitations | 10 samples，2/1/1/2/2/2；均为 `not_checked` | 人工视频核验 | `c94bbdf` |
| D | 来源分层、去重与追溯 | completed | `build-source-inventory`；社区计入official=0；重复ID=0 | 无 | `8533381` |
| E | 隔离Lore检索核心 | completed | `src/lore/`；官方/BH3Text/导航corpora隔离 | 无 | `8533381` |
| F | 混合检索、来源路由与引用 | completed | BM25 + hashed vector + RRF；短引用与URL校验 | 无 | `8533381` |
| G | 默认关闭的Agent接入 | completed_with_limitations | 当前聊天Prompt接入、引用和trace均受flags控制 | 完整Tool-calling Harness仍属主升级计划独立Phase | `8533381` |
| H | 候选关系与人工审核工作流 | completed_with_limitations | pending review + conflict report；实际语义关系0 | confirmed只能人工审核 | `8533381` |
| I | 40题评测与基线 | completed | hybrid R@5=0.950；citation/tier=100%；fixture/injection=0 | 无 | `8533381` |
| J | 安全、性能、降级与部署验证 | completed | 122 tests；index约3.88MB；p50/p95约607/643ms | 正式部署未授权 | `7a0451a` |
| K | 文档、作品集证据与最终报告 | completed | architecture、ADR、evaluation、handoff均已生成 | 无 | 当前文档提交 |
| L | 可回滚本地commits | completed | `c94bbdf`、`8533381`、`7a0451a`及当前文档提交；未push | Git自动repack权限提示，不影响提交完整性 | 当前文档提交 |
