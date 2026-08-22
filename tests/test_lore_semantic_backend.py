from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import pytest

from src.config import LoreRAGConfig
from src.lore.cli import build_parser
from src.lore.embeddings import (
    EmbeddingBackendUnavailable,
    SentenceTransformerEmbeddingBackend,
)
from src.lore.models import LoreChunk
from src.lore.retrieval import SemanticVectorIndex, SemanticVectorRetriever
from src.lore.semantic_evaluation import _safe_model_name, run_offline_semantic_evaluation
from src.lore.service import LoreRAG


class DeterministicEmbeddingBackend:
    name = "sentence-transformers"
    model_name = "test/chinese-semantic-model"

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if "凯文" in text:
                vectors.append([1.0, 0.0, 0.0])
            elif "爱莉希雅" in text:
                vectors.append([0.9, 0.1, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


class MissingEmbeddingBackend(DeterministicEmbeddingBackend):
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingBackendUnavailable("local_semantic_model_unavailable")


class StaticCorpus:
    def __init__(self, chunks: list[LoreChunk]) -> None:
        self.chunks = chunks

    def load(self, corpora):
        allowed = set(corpora)
        return [row for row in self.chunks if row.corpus in allowed], []


def _config(tmp_path: Path, *, backend: str = "hybrid") -> LoreRAGConfig:
    return LoreRAGConfig(
        enabled=True,
        prototype_mode=True,
        allow_unverified_transcripts=True,
        require_citations=True,
        top_k=5,
        max_context_chars=3000,
        backend=backend,
        index_path=tmp_path / "hashed.json",
        timeout_seconds=1.0,
        vector_backend="sentence-transformers",
        semantic_index_path=tmp_path / "semantic.json",
        embedding_model=DeterministicEmbeddingBackend.model_name,
        embedding_device="cpu",
        embedding_local_files_only=True,
    )


def _chunks() -> list[LoreChunk]:
    return [
        LoreChunk(
            chunk_id="official-elysia",
            document_id="official-doc",
            corpus="official_lore",
            content="爱莉希雅是逐火十三英桀的第二位。",
            title="爱莉希雅官方档案",
            source_url="https://baike.mihoyo.com/bh3/wiki/content/1/detail",
            source_type="official_wiki",
            source_tier="A",
            review_status="official",
            character_names=("爱莉希雅",),
        ),
        LoreChunk(
            chunk_id="transcript-elysia-kevin",
            document_id="transcript-doc",
            corpus="bh3text_dialogue",
            content="芽衣：你如何评价凯文？\n爱莉希雅：他总把责任背在自己身上。",
            title="爱莉希雅-关于凯文",
            source_url="https://www.bh3text.com/dialog/er/elysia-kevin",
            source_type="community_game_text_archive",
            source_tier="Tier B-primary-transcript",
            review_status="unverified_transcript",
            chapter="在无限的阴影之中",
            scene="爱莉希雅-关于凯文",
            character_names=("爱莉希雅", "凯文", "芽衣"),
        ),
    ]


def test_sentence_transformer_adapter_is_lazy_local_only_and_normalizes() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeModel:
        def encode(self, texts, **kwargs):
            assert kwargs == {
                "normalize_embeddings": True,
                "convert_to_numpy": True,
                "show_progress_bar": False,
            }
            return [[3.0, 4.0] for _ in texts]

    def factory(model_name: str, **kwargs):
        calls.append((model_name, kwargs))
        return FakeModel()

    backend = SentenceTransformerEmbeddingBackend(
        "local/chinese-model",
        device="cpu",
        local_files_only=True,
        model_factory=factory,
    )
    assert calls == []
    vectors = backend.encode(["爱莉希雅", "往世乐土"])
    assert calls == [
        (
            "local/chinese-model",
            {"device": "cpu", "local_files_only": True},
        )
    ]
    assert vectors[0] == pytest.approx([0.6, 0.8])
    assert vectors[1] == pytest.approx([0.6, 0.8])
    assert all(math.isclose(sum(value * value for value in row), 1.0) for row in vectors)


def test_semantic_cli_accepts_an_explicit_local_model_path() -> None:
    args = build_parser().parse_args(
        [
            "build-index",
            "--vector-backend",
            "sentence-transformers",
            "--embedding-model",
            "local/chinese-model",
        ]
    )
    assert args.vector_backend == "sentence-transformers"
    assert args.embedding_model == "local/chinese-model"

    eval_args = build_parser().parse_args(
        ["evaluate-semantic", "--embedding-model", "local/chinese-model"]
    )
    assert eval_args.command == "evaluate-semantic"
    assert eval_args.embedding_model == "local/chinese-model"
    assert _safe_model_name(str(Path("C:/private/models/bge").resolve())) == (
        "<local-model-path>"
    )


def test_sentence_transformer_adapter_reports_missing_local_model() -> None:
    def factory(model_name: str, **kwargs):
        raise OSError("model is not cached")

    backend = SentenceTransformerEmbeddingBackend(
        "missing/chinese-model",
        local_files_only=True,
        model_factory=factory,
    )
    with pytest.raises(
        EmbeddingBackendUnavailable,
        match="local_semantic_model_unavailable:OSError",
    ):
        backend.encode(["爱莉希雅"])


def test_semantic_index_round_trip_and_rank(tmp_path: Path) -> None:
    backend = DeterministicEmbeddingBackend()
    chunks = _chunks()
    path = tmp_path / "semantic" / "vectors.json"
    metadata = SemanticVectorIndex.build(chunks, backend).write(
        path,
        prototype_only=True,
    )
    loaded = SemanticVectorIndex.load(path)
    ranking = SemanticVectorRetriever(loaded, backend).rank(
        "爱莉希雅如何评价凯文",
        chunks,
        top_k=5,
    )
    assert metadata["index_type"] == "dense_semantic"
    assert metadata["production_enabled"] is False
    assert loaded.model_name == backend.model_name
    assert ranking[0].chunk.chunk_id == "transcript-elysia-kevin"


def test_semantic_hybrid_preserves_rrf_and_citations(tmp_path: Path) -> None:
    config = _config(tmp_path)
    backend = DeterministicEmbeddingBackend()
    chunks = _chunks()
    SemanticVectorIndex.build(chunks, backend).write(
        config.semantic_index_path,
        prototype_only=True,
    )
    result = LoreRAG(
        config,
        corpus=StaticCorpus(chunks),  # type: ignore[arg-type]
        embedding_backend=backend,
    ).retrieve("爱莉希雅如何评价凯文的剧情对话")
    assert result.backend == "hybrid"
    assert result.degraded_reason == ""
    assert result.results[0].title == "爱莉希雅-关于凯文"
    assert result.results[0].source_tier == "Tier B-primary-transcript"
    assert {"bm25_ms", "vector_ms", "fusion_ms"} <= set(result.timings)


def test_missing_semantic_model_falls_back_to_bm25(tmp_path: Path) -> None:
    config = _config(tmp_path)
    chunks = _chunks()
    SemanticVectorIndex.build(chunks, DeterministicEmbeddingBackend()).write(
        config.semantic_index_path,
        prototype_only=True,
    )
    result = LoreRAG(
        config,
        corpus=StaticCorpus(chunks),  # type: ignore[arg-type]
        embedding_backend=MissingEmbeddingBackend(),
    ).retrieve("爱莉希雅如何评价凯文的剧情对话")
    assert result.used is True
    assert result.backend == "bm25_fallback"
    assert result.degraded_reason == "semantic_model_unavailable"
    assert result.results[0].source_url.startswith("https://")


def test_missing_semantic_index_uses_existing_vector_fallback_reason(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    result = LoreRAG(
        config,
        corpus=StaticCorpus(_chunks()),  # type: ignore[arg-type]
        embedding_backend=DeterministicEmbeddingBackend(),
    ).retrieve("爱莉希雅是谁")
    assert result.backend == "bm25_fallback"
    assert result.degraded_reason == "vector_index_missing_stale_or_invalid"


def test_semantic_index_model_mismatch_falls_back_without_loading_model(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    chunks = _chunks()
    SemanticVectorIndex.build(chunks, DeterministicEmbeddingBackend()).write(
        config.semantic_index_path,
        prototype_only=True,
    )

    class OtherModelBackend(DeterministicEmbeddingBackend):
        model_name = "test/another-model"

        def encode(self, texts: Sequence[str]) -> list[list[float]]:
            raise AssertionError("model mismatch must be rejected before query encoding")

    result = LoreRAG(
        replace(config, embedding_model=OtherModelBackend.model_name),
        corpus=StaticCorpus(chunks),  # type: ignore[arg-type]
        embedding_backend=OtherModelBackend(),
    ).retrieve("爱莉希雅是谁")
    assert result.backend == "bm25_fallback"
    assert result.degraded_reason == "vector_index_missing_stale_or_invalid"


def test_offline_semantic_evaluation_records_missing_model_without_metrics(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    summary_path = tmp_path / "summary.json"
    report_path = tmp_path / "report.md"
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(
        '{"vector_ready": false, "actual": {"reviewed_scenes": 0, '
        '"matches": 0, "critical_mismatches": 0}}',
        encoding="utf-8",
    )
    payload = run_offline_semantic_evaluation(
        config=config,
        corpus=StaticCorpus(_chunks()),  # type: ignore[arg-type]
        embedding_backend=MissingEmbeddingBackend(),
        summary_path=summary_path,
        results_path=tmp_path / "results.jsonl",
        report_path=report_path,
        vector_readiness_path=readiness_path,
    )
    assert payload["evaluation_status"] == "blocked_local_model_missing"
    assert payload["semantic_metrics"] is None
    assert payload["semantic_index_created"] is False
    assert payload["paid_api_calls"] == 0
    assert payload["human_review_gate"]["vector_ready"] is False
    assert not config.semantic_index_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "Not verified" in report
    assert "未下载模型" in report


def test_offline_semantic_evaluation_runs_fixed_cases_with_injected_backend(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    payload = run_offline_semantic_evaluation(
        config=config,
        corpus=StaticCorpus(_chunks()),  # type: ignore[arg-type]
        embedding_backend=DeterministicEmbeddingBackend(),
        summary_path=tmp_path / "summary.json",
        results_path=tmp_path / "results.jsonl",
        report_path=tmp_path / "report.md",
        vector_readiness_path=tmp_path / "missing-readiness.json",
    )
    assert payload["evaluation_status"] == "completed"
    assert payload["semantic_index_created"] is True
    assert payload["semantic_metrics"]["cases"] == 40
    assert payload["human_review_gate"]["vector_ready"] is False
    assert payload["production_enabled"] is False
    assert config.semantic_index_path.exists()
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "dense semantic embedding" in report
    assert "evaluation_status: `completed`" in report
    assert "human transcript verification: `Blocked for human review`" in report
