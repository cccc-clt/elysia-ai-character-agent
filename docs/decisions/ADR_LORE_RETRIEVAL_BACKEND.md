# ADR: Lore Retrieval Backend

- Status: Accepted for local prototype
- Date: 2026-08-22
- Production decision: Deferred for human review

## Context

预检确认仓库没有Qdrant、FAISS、Chroma、pgvector、PostgreSQL或embedding依赖。运行目标同时包含本地演示、Streamlit Cloud与Hugging Face Spaces；后两者的持久磁盘和模型冷启动没有得到保证。完整corpus与索引又必须保持Git ignored，不能依赖仓库公开发布版权正文。

## Options considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| PostgreSQL + pgvector | 生产持久化和过滤能力强 | 仓库无PostgreSQL、需要服务/凭据/迁移 | 不在无人值守阶段引入 |
| Qdrant local + FastEmbed | 常见本地向量接口，可替换模型 | 新二进制/模型下载、冷启动和中文模型体积未知 | 保留为未来人工决策 |
| FAISS/Chroma | 生态成熟 | 新原生依赖或额外持久化层；当前规模收益有限 | 暂不采用 |
| BM25 only | 无新依赖、可解释、稳定 | 缺少第二路召回 | 作为永远可用基线/降级 |
| BM25 + hashed char n-gram vector + RRF | 无账号、无下载、可运行双adapter与混合召回 | 仍是词法向量，不是语义embedding | 选作开发原型 |

## Decision

采用：

```text
BM25 char 2/3-gram
+ 2048-dimension hashed char n-gram sparse vector
+ cosine similarity
+ Reciprocal Rank Fusion
+ route/title/source-tier rerank
```

索引只能通过显式命令构建：

```bash
python -m src.lore.cli build-index --include-unverified-transcripts
```

模块导入和应用启动不会下载模型或自动构建索引。索引写入 `data/lore_index/`，由 `.gitignore` 排除；文件记录模型名、维度、距离函数、corpus signature、chunk hash、vector count与prototype状态。

## Measured prototype result

当前本地数据：223 chunks（16 official + 201 BH3Text + 6 navigation）。

- index model: `hashed-char-ngram-v1`
- dimensions: 2048
- distance: cosine
- build time: about 0.86s
- index size: about 3.88MB
- hybrid retrieval p50/p95: about 607/643ms over the 40-case run
- hybrid Recall@5: 0.950

这些数值只适用于2026-08-22的本地数据和机器，不代表生产SLA或通用中文语义质量。

## Safety and fallback

- 索引缺失、JSON损坏、chunk hash不匹配时自动回退BM25；
- 默认 `LORE_RAG_ENABLED=false`；
- 未核验转录默认不可检索；
- 原始corpus、索引和详细评测结果不提交Git；
- 本ADR不批准正式启用、远端向量服务或部署。

## Consequences and future decision

原型在零新凭据和小体积下提供了真实的两个adapters，适合验证路由、引用与评测。代价是无法捕捉词面差异很大的语义相似问题。用户回来后应结合失败样本、部署持久化和允许的模型体积，决定是否迁移到Qdrant/FastEmbed或托管向量库；迁移只需替换检索 seam 下的vector adapter，不应改变应用调用 interface。

## Rollback

关闭 `LORE_RAG_ENABLED` 即恢复原聊天行为。删除本地 `data/lore_index/` 只会触发BM25降级，不影响数据库、Memory或聊天记录。
