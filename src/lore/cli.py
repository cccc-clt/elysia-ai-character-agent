"""Explicit local commands for prototype lore indexing and diagnostics."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from src.config import PROJECT_ROOT, get_config
from src.lore.corpus import LoreCorpus
from src.lore.embeddings import (
    EmbeddingBackendUnavailable,
    SentenceTransformerEmbeddingBackend,
)
from src.lore.models import CorpusName
from src.lore.retrieval import HashedVectorIndex, SemanticVectorIndex
from src.lore.service import LoreRAG
from src.lore.review import build_retrieval_match_review
from src.lore.semantic_evaluation import run_offline_semantic_evaluation


def _prototype_config(
    *,
    include_unverified: bool,
    vector_backend: str | None = None,
    embedding_model: str | None = None,
):
    config = get_config().lore_rag
    return replace(
        config,
        enabled=True,
        prototype_mode=True,
        allow_unverified_transcripts=include_unverified,
        vector_backend=vector_backend or config.vector_backend,
        embedding_model=embedding_model or config.embedding_model,
    )


def _add_vector_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vector-backend",
        choices=("hashed", "sentence-transformers"),
        help="override LORE_RAG_VECTOR_BACKEND for this local prototype command",
    )
    parser.add_argument(
        "--embedding-model",
        help="local sentence-transformers model name or path",
    )


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return "<external-local-path>"


def _display_model(model_name: str) -> str:
    return "<local-model-path>" if Path(model_name).is_absolute() else model_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.lore.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-index")
    build.add_argument("--include-unverified-transcripts", action="store_true")
    _add_vector_options(build)
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--include-unverified-transcripts", action="store_true")
    _add_vector_options(search)
    review = subparsers.add_parser(
        "build-review",
        help="build the 8-case retrieval match review workbench",
    )
    review.add_argument("--include-unverified-transcripts", action="store_true")
    semantic_eval = subparsers.add_parser(
        "evaluate-semantic",
        help="run the 40-case local-only semantic retrieval evaluation",
    )
    semantic_eval.add_argument(
        "--embedding-model",
        help="local sentence-transformers model name or path",
    )
    subparsers.add_parser("status")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    exit_code = 0
    config = _prototype_config(
        include_unverified=getattr(args, "include_unverified_transcripts", False),
        vector_backend=getattr(args, "vector_backend", None),
        embedding_model=getattr(args, "embedding_model", None),
    )
    if args.command == "build-index":
        corpora: tuple[CorpusName, ...] = (
            "official_lore",
            "story_navigation",
            *((("bh3text_dialogue",)) if config.allow_unverified_transcripts else ()),
        )
        chunks, warnings = LoreCorpus(config).load(corpora)
        started = time.perf_counter()
        index_path = config.index_path
        if config.vector_backend == "sentence-transformers":
            embedding_backend = SentenceTransformerEmbeddingBackend(
                config.embedding_model,
                device=config.embedding_device,
                local_files_only=config.embedding_local_files_only,
            )
            try:
                index = SemanticVectorIndex.build(chunks, embedding_backend)
            except EmbeddingBackendUnavailable as exc:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "semantic_model_unavailable",
                            "detail": str(exc),
                            "model_name": _display_model(config.embedding_model),
                            "local_files_only": config.embedding_local_files_only,
                            "production_enabled": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 2
            index_path = config.semantic_index_path
        else:
            index = HashedVectorIndex.build(chunks)
        build_time_ms = (time.perf_counter() - started) * 1000
        metadata = index.write(
            index_path,
            prototype_only=True,
            build_time_ms=build_time_ms,
        )
        payload = {
            **metadata,
            "index_size_bytes": index_path.stat().st_size,
            "warnings": warnings,
        }
    elif args.command == "search":
        result = LoreRAG(config).retrieve(args.query)
        payload = {
            "route": result.route,
            "backend": result.backend,
            "elapsed_ms": result.elapsed_ms,
            "degraded_reason": result.degraded_reason,
            "results": [
                {
                    "chunk_id": row.chunk_id,
                    "title": row.title,
                    "score": row.score,
                    "source_url": row.source_url,
                    "source_tier": row.source_tier,
                    "review_status": row.review_status,
                }
                for row in result.results
            ],
        }
    elif args.command == "build-review":
        payload = build_retrieval_match_review(LoreRAG(config))
    elif args.command == "evaluate-semantic":
        payload = run_offline_semantic_evaluation(config=config)
        if payload["evaluation_status"] != "completed":
            exit_code = 2
    else:
        payload = {
            "hashed_index_exists": config.index_path.exists(),
            "hashed_index_path": _display_path(config.index_path),
            "semantic_index_exists": config.semantic_index_path.exists(),
            "semantic_index_path": _display_path(config.semantic_index_path),
            "configured_vector_backend": config.vector_backend,
            "embedding_model": _display_model(config.embedding_model),
            "embedding_local_files_only": config.embedding_local_files_only,
            "prototype_only": True,
            "production_enabled": False,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
