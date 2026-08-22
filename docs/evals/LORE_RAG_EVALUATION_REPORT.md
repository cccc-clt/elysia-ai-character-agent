# Lore RAG Evaluation Report

> 本报告来自确定性本地检索评测；没有调用LLM judge或付费API。BH3Text结果仍是未人工核验的社区托管转录。

## Case distribution

- 身份与别名: 6
- 英桀与组织: 6
- 人物互动与关系: 8
- 往世乐土时间线: 6
- 主线29—31章: 6
- 观看顺序与资料导航: 3
- 资料缺失/应拒答: 3
- 提示注入与来源冲突: 2

## Retrieval metrics

| Run | R@1 | R@3 | R@5 | MRR | nDCG@5 | Citation | Tier | No-answer | p50 ms | p95 ms | Duplicate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_a_no_retrieval | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.0% | 0.0% | 100.0% | 0.0 | 0.0 | 0.000 |
| baseline_b_bm25 | 0.644 | 0.887 | 0.896 | 0.811 | 0.869 | 100.0% | 100.0% | 100.0% | 265.9 | 287.1 | 0.027 |
| candidate_c_hybrid | 0.671 | 0.914 | 0.950 | 0.834 | 0.876 | 100.0% | 100.0% | 100.0% | 607.2 | 643.2 | 0.011 |

## Prototype quality gate

- recall_at_5_gte_0_80: True
- citation_presence_100_percent: True
- source_tier_compliance_100_percent: True
- test_fixture_leakage_zero: True
- critical_prompt_injection_failures_zero: True
- passed: True

## Interpretation

- `baseline_a_no_retrieval` 仅用于显示无检索时的检索指标下界，不代表答案质量评测。
- `candidate_c_hybrid` 使用 BM25 + `hashed-char-ngram-v1` 稀疏向量 + RRF；该向量不是神经语义 embedding。
- 评测通过只允许开发原型继续，不能绕过 `vector_readiness.json` 的人工核验门，也不能自动开启生产。
- 每题详细命中保存在 Git ignored 的 `evals/lore_rag_results.jsonl`，不含剧情正文。

## Hybrid stage latency (p50 ms)

- bm25_ms: 254.913
- corpus_load_ms: 0.021
- fusion_ms: 0.17
- rerank_and_context_ms: 1.609
- vector_ms: 351.705
