"""Reproducible offline quality gate for the optional semantic backend."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, LoreRAGConfig, get_config
from src.lore.corpus import LoreCorpus
from src.lore.embeddings import (
    EmbeddingBackend,
    EmbeddingBackendUnavailable,
    SentenceTransformerEmbeddingBackend,
)
from src.lore.evaluation import run_evaluation
from src.lore.models import CorpusName
from src.lore.retrieval import SemanticVectorIndex


DEFAULT_SEMANTIC_SUMMARY = PROJECT_ROOT / "evals" / "lore_semantic_evaluation.json"
DEFAULT_SEMANTIC_RESULTS = PROJECT_ROOT / "evals" / "lore_semantic_results.jsonl"
DEFAULT_SEMANTIC_REPORT = (
    PROJECT_ROOT / "docs" / "evals" / "LORE_SEMANTIC_BACKEND_EVALUATION.md"
)
DEFAULT_VECTOR_READINESS = PROJECT_ROOT / "data" / "manifests" / "vector_readiness.json"


def _safe_model_name(model_name: str) -> str:
    return "<local-model-path>" if Path(model_name).is_absolute() else model_name


def _human_gate(path: Path = DEFAULT_VECTOR_READINESS) -> dict[str, Any]:
    if not path.exists():
        return {"vector_ready": False, "reason": "vector_readiness_manifest_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"vector_ready": False, "reason": "vector_readiness_manifest_invalid"}
    return {
        "vector_ready": bool(payload.get("vector_ready", False)),
        "reviewed_scenes": int(payload.get("actual", {}).get("reviewed_scenes", 0)),
        "matches": int(payload.get("actual", {}).get("matches", 0)),
        "critical_mismatches": int(
            payload.get("actual", {}).get("critical_mismatches", 0)
        ),
        "reason": str(payload.get("reason", "")),
    }


def _write_blocked_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Lore Semantic Backend Evaluation",
        "",
        "> 本报告只允许离线本地模型；未调用付费API，也没有下载模型。",
        "",
        "## Status",
        "",
        f"- evaluation_status: `{payload['evaluation_status']}`",
        "- capability_status: `Prototype only`",
        f"- model: `{payload['embedding_model']}`",
        f"- local_files_only: `{payload['local_files_only']}`",
        f"- eligible_chunks: `{payload['eligible_chunks']}`",
        f"- semantic_index_created: `{payload['semantic_index_created']}`",
        "- semantic quality metrics: `Not verified`",
        "",
        "## Blocker",
        "",
        f"- {payload['blocked_reason']}",
        "- 只有模型已由用户明确安装到本地后，才能重跑40例离线质量评测。",
        "- 缺少模型时运行时继续回退BM25；这一降级路径由自动化测试覆盖。",
        "",
        "## Human review gate",
        "",
        f"- vector_ready: `{payload['human_review_gate']['vector_ready']}`",
        f"- reviewed_scenes: `{payload['human_review_gate'].get('reviewed_scenes', 0)}`",
        f"- matches: `{payload['human_review_gate'].get('matches', 0)}`",
        "- 语义检索指标即使通过，也不能替代10场景人工转录核验。",
        "",
        "## Not performed",
        "",
        "- 未下载模型。",
        "- 未调用embedding API、LLM judge或任何付费API。",
        "- 未生成或启用正式向量索引。",
        "- 未改变 `LORE_RAG_ENABLED=false`。",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_offline_semantic_evaluation(
    *,
    config: LoreRAGConfig | None = None,
    corpus: LoreCorpus | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    summary_path: Path = DEFAULT_SEMANTIC_SUMMARY,
    results_path: Path = DEFAULT_SEMANTIC_RESULTS,
    report_path: Path = DEFAULT_SEMANTIC_REPORT,
    vector_readiness_path: Path = DEFAULT_VECTOR_READINESS,
) -> dict[str, Any]:
    """Build and evaluate a semantic index without network or paid services."""

    base = config or get_config().lore_rag
    prototype = replace(
        base,
        enabled=True,
        prototype_mode=True,
        allow_unverified_transcripts=True,
        require_citations=True,
        vector_backend="sentence-transformers",
        embedding_local_files_only=True,
    )
    active_corpus = corpus or LoreCorpus(prototype)
    corpora: tuple[CorpusName, ...] = (
        "official_lore",
        "story_navigation",
        "bh3text_dialogue",
    )
    chunks, warnings = active_corpus.load(corpora)
    backend = embedding_backend or SentenceTransformerEmbeddingBackend(
        prototype.embedding_model,
        device=prototype.embedding_device,
        local_files_only=True,
    )
    try:
        semantic_index = SemanticVectorIndex.build(chunks, backend)
    except EmbeddingBackendUnavailable as exc:
        payload = {
            "evaluation_status": "blocked_local_model_missing",
            "capability_status": "Prototype only",
            "embedding_backend": backend.name,
            "embedding_model": _safe_model_name(backend.model_name),
            "local_files_only": True,
            "eligible_chunks": len(chunks),
            "semantic_index_created": False,
            "semantic_metrics": None,
            "blocked_reason": str(exc),
            "warnings": warnings,
            "human_review_gate": _human_gate(vector_readiness_path),
            "production_enabled": False,
            "paid_api_calls": 0,
        }
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_blocked_report(report_path, payload)
        return payload

    semantic_index.write(prototype.semantic_index_path, prototype_only=True)
    evaluation = run_evaluation(
        results_path=results_path,
        report_path=report_path,
        config=prototype,
        corpus=active_corpus,
        embedding_backend=backend,
    )
    payload = {
        "evaluation_status": "completed",
        "capability_status": "Prototype only",
        "embedding_backend": backend.name,
        "embedding_model": _safe_model_name(backend.model_name),
        "local_files_only": True,
        "eligible_chunks": len(chunks),
        "semantic_index_created": True,
        "semantic_metrics": evaluation["metrics"]["candidate_c_hybrid"],
        "prototype_quality_gate": evaluation["prototype_quality_gate"],
        "prototype_quality_gate_passed": evaluation[
            "prototype_quality_gate_passed"
        ],
        "warnings": warnings,
        "human_review_gate": _human_gate(vector_readiness_path),
        "production_enabled": False,
        "paid_api_calls": 0,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload
