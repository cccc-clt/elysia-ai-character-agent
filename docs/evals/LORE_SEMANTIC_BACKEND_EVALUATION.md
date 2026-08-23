# Lore Semantic Backend Evaluation

> 本报告只允许离线本地模型；未调用付费API，也没有下载模型。

## Status

- evaluation_status: `blocked_local_model_missing`
- capability_status: `Prototype only`
- model: `BAAI/bge-small-zh-v1.5`
- local_files_only: `True`
- eligible_chunks: `223`
- semantic_index_created: `False`
- semantic quality metrics: `Not verified`

## Blocker

- local_semantic_model_unavailable:OSError
- 只有模型已由用户明确安装到本地后，才能重跑40例离线质量评测。
- 缺少模型时运行时继续回退BM25；这一降级路径由自动化测试覆盖。

## Human review gate

- vector_ready: `False`
- reviewed_scenes: `0`
- matches: `0`
- 语义检索指标即使通过，也不能替代10场景人工转录核验。

## Not performed

- 未下载模型。
- 未调用embedding API、LLM judge或任何付费API。
- 未生成或启用正式向量索引。
- 未改变 `LORE_RAG_ENABLED=false`。
