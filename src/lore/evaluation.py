"""Deterministic retrieval evaluation without model or paid API calls."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from src.config import PROJECT_ROOT, LoreRAGConfig, get_config
from src.lore.corpus import LoreCorpus, is_safe_source_url
from src.lore.embeddings import EmbeddingBackend
from src.lore.models import LoreAugmentation
from src.lore.service import INJECTION_PATTERNS, LoreRAG


DEFAULT_CASES = PROJECT_ROOT / "evals" / "lore_rag_cases.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "evals" / "lore_rag_results.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "evals" / "LORE_RAG_EVALUATION_REPORT.md"


@dataclass(frozen=True)
class LoreEvalCase:
    case_id: str
    question: str
    category: str
    expected_corpus: tuple[str, ...]
    expected_entities: tuple[str, ...]
    expected_source_tier: str
    gold_source_urls: tuple[str, ...]
    should_abstain: bool
    expected_answer: str = ""

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "LoreEvalCase":
        return cls(
            case_id=str(row["case_id"]),
            question=str(row["question"]),
            category=str(row["category"]),
            expected_corpus=tuple(str(value) for value in row["expected_corpus"]),
            expected_entities=tuple(str(value) for value in row["expected_entities"]),
            expected_source_tier=str(row["expected_source_tier"]),
            gold_source_urls=tuple(str(value) for value in row["gold_source_urls"]),
            should_abstain=bool(row["should_abstain"]),
            expected_answer=str(row.get("expected_answer", "")),
        )


def load_cases(path: Path = DEFAULT_CASES) -> list[LoreEvalCase]:
    return [
        LoreEvalCase.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_case_distribution(cases: Iterable[LoreEvalCase]) -> dict[str, int]:
    counts: dict[str, int] = {}
    identifiers: set[str] = set()
    for case in cases:
        if case.case_id in identifiers:
            raise ValueError(f"duplicate eval case id: {case.case_id}")
        identifiers.add(case.case_id)
        counts[case.category] = counts.get(case.category, 0) + 1
    expected = {
        "身份与别名": 6,
        "英桀与组织": 6,
        "人物互动与关系": 8,
        "往世乐土时间线": 6,
        "主线29—31章": 6,
        "观看顺序与资料导航": 3,
        "资料缺失/应拒答": 3,
        "提示注入与来源冲突": 2,
    }
    if counts != expected:
        raise ValueError(f"unexpected lore eval distribution: {counts}")
    return counts


def _empty_result(case: LoreEvalCase) -> LoreAugmentation:
    return LoreAugmentation(
        query=case.question,
        route="none",
        backend="no_retrieval",
        context="",
        enabled=False,
    )


def _percent(numerator: float, denominator: float) -> float:
    return round(100.0 * numerator / denominator, 3) if denominator else 0.0


def _dcg(relevance: list[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevance))


def _run_one(
    run_name: str,
    cases: list[LoreEvalCase],
    service: LoreRAG | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    recall_sums = {1: 0.0, 3: 0.0, 5: 0.0}
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    citation_presence = 0
    valid_citation_cases = 0
    tier_compliant = 0
    no_answer_correct = 0
    fixture_hits = 0
    injection_failures = 0
    duplicate_results = 0
    total_results = 0
    latencies: list[float] = []
    stage_latencies: dict[str, list[float]] = {}
    answerable = [case for case in cases if not case.should_abstain]
    abstentions = [case for case in cases if case.should_abstain]
    for case in cases:
        result = service.retrieve(case.question) if service else _empty_result(case)
        urls = [row.source_url for row in result.results]
        tiers = [row.source_tier for row in result.results]
        gold = set(case.gold_source_urls)
        if not case.should_abstain:
            for cutoff in recall_sums:
                hits = len(gold.intersection(urls[:cutoff]))
                recall_sums[cutoff] += hits / max(1, len(gold))
            first_hit = next(
                (index for index, url in enumerate(urls, 1) if url in gold),
                0,
            )
            reciprocal_ranks.append(1.0 / first_hit if first_hit else 0.0)
            relevance = [int(url in gold) for url in urls[:5]]
            ideal = [1] * min(5, len(gold))
            ndcgs.append(_dcg(relevance) / _dcg(ideal) if ideal else 0.0)
            citation_presence += int(bool(result.citations))
            valid_citation_cases += int(
                bool(result.citations)
                and all(is_safe_source_url(row.source_url) for row in result.citations)
            )
            tier_compliant += int(
                bool(tiers)
                and bool(case.expected_source_tier)
                and tiers[0] == case.expected_source_tier
            )
        else:
            no_answer_correct += int(not result.results)
        fixture_hits += sum(
            any(marker in f"{row.chunk_id}\n{row.title}\n{row.source_url}".lower() for marker in ("fixture", "synthetic", "example.invalid"))
            for row in result.results
        )
        injection_failures += int(
            any(
                pattern.search(row.content)
                for row in result.results
                for pattern in INJECTION_PATTERNS
            )
        )
        duplicate_results += max(0, len(urls) - len(set(urls)))
        total_results += len(urls)
        latencies.append(result.elapsed_ms)
        for stage, value in result.timings.items():
            stage_latencies.setdefault(stage, []).append(value)
        rows.append(
            {
                "run": run_name,
                "case_id": case.case_id,
                "category": case.category,
                "route": result.route,
                "backend": result.backend,
                "elapsed_ms": result.elapsed_ms,
                "degraded_reason": result.degraded_reason,
                "timings": result.timings,
                "should_abstain": case.should_abstain,
                "gold_hits_at_5": sorted(gold.intersection(urls[:5])),
                "retrieved": [
                    {
                        "rank": index,
                        "chunk_id": row.chunk_id,
                        "title": row.title,
                        "source_url": row.source_url,
                        "source_tier": row.source_tier,
                        "corpus": row.corpus,
                        "review_status": row.review_status,
                    }
                    for index, row in enumerate(result.results, 1)
                ],
            }
        )
    sorted_latency = sorted(latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latency)) - 1)
    metrics = {
        "cases": len(cases),
        "recall_at_1": round(recall_sums[1] / max(1, len(answerable)), 6),
        "recall_at_3": round(recall_sums[3] / max(1, len(answerable)), 6),
        "recall_at_5": round(recall_sums[5] / max(1, len(answerable)), 6),
        "mrr": round(statistics.mean(reciprocal_ranks), 6) if reciprocal_ranks else 0.0,
        "ndcg_at_5": round(statistics.mean(ndcgs), 6) if ndcgs else 0.0,
        "citation_presence_percent": _percent(citation_presence, len(answerable)),
        "citation_url_validity_percent": _percent(valid_citation_cases, len(answerable)),
        "source_tier_compliance_percent": _percent(tier_compliant, len(answerable)),
        "no_answer_precision_percent": _percent(no_answer_correct, len(abstentions)),
        "test_fixture_leakage": fixture_hits,
        "critical_prompt_injection_failures": injection_failures,
        "duplicate_retrieval_rate": round(
            duplicate_results / max(1, total_results), 6
        ),
        "latency_p50_ms": round(statistics.median(sorted_latency), 3) if sorted_latency else 0.0,
        "latency_p95_ms": round(sorted_latency[p95_index], 3) if sorted_latency else 0.0,
        "cold_start_ms": round(latencies[0], 3) if latencies else 0.0,
        "stage_latency_p50_ms": {
            stage: round(statistics.median(values), 3)
            for stage, values in sorted(stage_latencies.items())
        },
    }
    return rows, metrics


def run_evaluation(
    *,
    cases_path: Path = DEFAULT_CASES,
    results_path: Path = DEFAULT_RESULTS,
    report_path: Path = DEFAULT_REPORT,
    config: LoreRAGConfig | None = None,
    corpus: LoreCorpus | None = None,
    embedding_backend: EmbeddingBackend | None = None,
) -> dict[str, Any]:
    cases = load_cases(cases_path)
    distribution = validate_case_distribution(cases)
    base = config or get_config().lore_rag
    prototype = replace(
        base,
        enabled=True,
        prototype_mode=True,
        allow_unverified_transcripts=True,
        require_citations=True,
        top_k=5,
    )
    runs = {
        "baseline_a_no_retrieval": None,
        "baseline_b_bm25": LoreRAG(
            replace(prototype, backend="bm25"),
            corpus=corpus,
        ),
        "candidate_c_hybrid": LoreRAG(
            replace(prototype, backend="hybrid"),
            corpus=corpus,
            embedding_backend=embedding_backend,
        ),
    }
    all_rows: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, Any]] = {}
    for run_name, service in runs.items():
        rows, run_metrics = _run_one(run_name, cases, service)
        all_rows.extend(rows)
        metrics[run_name] = run_metrics
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in all_rows) + "\n",
        encoding="utf-8",
    )
    candidate = metrics["candidate_c_hybrid"]
    gate = {
        "recall_at_5_gte_0_80": candidate["recall_at_5"] >= 0.80,
        "citation_presence_100_percent": candidate["citation_presence_percent"] == 100.0,
        "source_tier_compliance_100_percent": candidate["source_tier_compliance_percent"] == 100.0,
        "test_fixture_leakage_zero": candidate["test_fixture_leakage"] == 0,
        "critical_prompt_injection_failures_zero": candidate["critical_prompt_injection_failures"] == 0,
    }
    payload = {
        "evaluation_status": "completed",
        "vector_backend": prototype.vector_backend,
        "embedding_model": (
            prototype.embedding_model
            if prototype.vector_backend == "sentence-transformers"
            else "hashed-char-ngram-v1"
        ),
        "case_distribution": distribution,
        "metrics": metrics,
        "prototype_quality_gate": gate,
        "prototype_quality_gate_passed": all(gate.values()),
    }
    _write_report(report_path, payload)
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Lore RAG Evaluation Report",
        "",
        "> 本报告来自确定性本地检索评测；没有调用LLM judge或付费API。BH3Text结果仍是未人工核验的社区托管转录。",
        "",
        "## Case distribution",
        "",
    ]
    lines.extend(
        f"- {category}: {count}"
        for category, count in payload["case_distribution"].items()
    )
    lines.extend(
        [
            "",
            "## Retrieval metrics",
            "",
            "| Run | R@1 | R@3 | R@5 | MRR | nDCG@5 | Citation | Tier | No-answer | p50 ms | p95 ms | Duplicate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, row in payload["metrics"].items():
        lines.append(
            f"| {name} | {row['recall_at_1']:.3f} | {row['recall_at_3']:.3f} | "
            f"{row['recall_at_5']:.3f} | {row['mrr']:.3f} | {row['ndcg_at_5']:.3f} | "
            f"{row['citation_presence_percent']:.1f}% | {row['source_tier_compliance_percent']:.1f}% | "
            f"{row['no_answer_precision_percent']:.1f}% | {row['latency_p50_ms']:.1f} | "
            f"{row['latency_p95_ms']:.1f} | {row['duplicate_retrieval_rate']:.3f} |"
        )
    lines.extend(["", "## Prototype quality gate", ""])
    lines.extend(
        f"- {key}: {value}"
        for key, value in payload["prototype_quality_gate"].items()
    )
    lines.extend(
        [
            f"- passed: {payload['prototype_quality_gate_passed']}",
            "",
            "## Interpretation",
            "",
            "- `baseline_a_no_retrieval` 仅用于显示无检索时的检索指标下界，不代表答案质量评测。",
            (
                f"- `candidate_c_hybrid` 使用 BM25 + `{payload['embedding_model']}` "
                "dense semantic embedding + RRF。"
                if payload["vector_backend"] == "sentence-transformers"
                else "- `candidate_c_hybrid` 使用 BM25 + `hashed-char-ngram-v1` "
                "稀疏向量 + RRF；该向量不是神经语义 embedding。"
            ),
            "- 评测通过只允许开发原型继续，不能绕过 `vector_readiness.json` 的人工核验门，也不能自动开启生产。",
            "- 每题详细命中保存在 Git ignored 的 `evals/lore_rag_results.jsonl`，不含剧情正文。",
            "",
            "## Hybrid stage latency (p50 ms)",
            "",
        ]
    )
    lines.extend(
        f"- {stage}: {value}"
        for stage, value in payload["metrics"]["candidate_c_hybrid"][
            "stage_latency_p50_ms"
        ].items()
    )
    lines.extend(
        [
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(run_evaluation(), ensure_ascii=False, indent=2))
