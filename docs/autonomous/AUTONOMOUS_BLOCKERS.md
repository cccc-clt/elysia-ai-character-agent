# Elysia V2 Autonomous Blockers

## BLOCKER-001

- Task: BH3Text 10场景人工视频/游戏原文核验
- Status: `blocked_human`
- Evidence: `data/review/bh3text_transcript_verification.jsonl` 中10条记录均为 `not_checked`
- Why Codex cannot safely continue: 程序没有播放视频或访问游戏原文，不能判断说话者和台词是否一致，也不能伪造 `match`
- Work completed around the blocker: 已生成固定章节分布、3～5轮短样本、来源URL与保守视频提示；结构和质量门可继续自动验证
- Exact user action required: 逐项查看对应视频/游戏原文，填写时间点并标记 `match`、`minor_mismatch` 或 `critical_mismatch`
- Resume command: `python -m data_pipeline.cli build-bh3text`

