# ADR: Lore Retrieval Backend

- Status: Accepted for local prototype
- Date: 2026-08-22
- Production decision: Deferred for human review
- Second stabilization amendment: optional local semantic adapter implemented; hashed remains default

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
| BM25 + sentence-transformers中文dense vector + RRF | 真实可替换语义召回；不依赖远端向量服务 | 可选大依赖、模型需显式本地安装、部署冷启动未验证 | 实现为本地可选原型；不设为默认 |

## Decision

采用：

```text
BM25 char 2/3-gram
+ 2048-dimension hashed char n-gram sparse vector
+ cosine similarity
+ Reciprocal Rank Fusion
+ route/title/source-tier rerank
```

第二轮稳定化保留上述默认路径，并在同一vector seam下增加：

```text
EmbeddingBackend protocol
+ SentenceTransformerEmbeddingBackend (lazy, local-files-only by default)
+ dense cosine index
+ unchanged BM25/RRF/citation fallback
```

索引只能通过显式命令构建：

```bash
python -m src.lore.cli build-index --include-unverified-transcripts
python -m src.lore.cli build-index --include-unverified-transcripts --vector-backend sentence-transformers
```

第二条命令要求模型已明确安装在本地；默认 `LORE_RAG_EMBEDDING_LOCAL_FILES_ONLY=true`，不会隐式下载。模块导入和应用启动不会下载模型或自动构建索引。两类索引都写入 `data/lore_index/`，由 `.gitignore` 排除；文件记录模型名、维度、距离函数、corpus signature、chunk hash、vector count与prototype状态。

## Measured prototype result

当前本地数据：223 chunks（16 official + 201 BH3Text + 6 navigation）。

- index model: `hashed-char-ngram-v1`
- dimensions: 2048
- distance: cosine
- build time: about 0.86s
- index size: about 3.88MB
- hybrid retrieval p50/p95: about 465/584ms over the final 40-case run（受本机负载影响）
- hybrid Recall@5: 0.991
- hybrid MRR / nDCG@5: 0.910 / 0.928

这些数值只适用于2026-08-22的本地数据和机器，不代表生产SLA或通用中文语义质量。可选中文模型 `BAAI/bge-small-zh-v1.5` 当前不在本地缓存；离线命令识别了223个eligible chunks后写出 `blocked_local_model_missing`，semantic metrics保持null，未创建semantic index。因此真实中文语义质量仍为 `Not verified`。

## Safety and fallback

- 索引缺失、JSON损坏、chunk hash不匹配时自动回退BM25；
- semantic模型缺失或embedding失败时以 `semantic_model_unavailable` 降级BM25；
- 默认 `LORE_RAG_ENABLED=false`；
- 未核验转录默认不可检索；
- 原始corpus、索引和详细评测结果不提交Git；
- 本ADR不批准正式启用、远端向量服务或部署。

## Consequences and future decision

默认原型在零新凭据和小体积下提供了可运行的hashed双路召回；可选adapter已证明接口、索引与降级编排可替换，但尚未证明真实中文质量。用户回来后应先完成10场景与8案例人工审核，再明确安装允许的本地模型并运行 `python -m src.lore.cli evaluate-semantic`；只有获得真实指标后，才讨论Qdrant/FastEmbed或托管向量库。迁移只需替换检索 seam 下的vector adapter，不应改变应用调用 interface。

## Rollback

关闭 `LORE_RAG_ENABLED` 即恢复原聊天行为。删除本地 `data/lore_index/` 只会触发BM25降级，不影响数据库、Memory或聊天记录。
