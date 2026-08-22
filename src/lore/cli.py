"""Explicit local commands for prototype lore indexing and diagnostics."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

from src.config import get_config
from src.lore.corpus import LoreCorpus
from src.lore.models import CorpusName
from src.lore.retrieval import HashedVectorIndex
from src.lore.service import LoreRAG


def _prototype_config(*, include_unverified: bool):
    config = get_config().lore_rag
    return replace(
        config,
        enabled=True,
        prototype_mode=True,
        allow_unverified_transcripts=include_unverified,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.lore.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-index")
    build.add_argument("--include-unverified-transcripts", action="store_true")
    search = subparsers.add_parser("search")
    search.add_argument("query")
    search.add_argument("--include-unverified-transcripts", action="store_true")
    subparsers.add_parser("status")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = _prototype_config(
        include_unverified=getattr(args, "include_unverified_transcripts", False)
    )
    if args.command == "build-index":
        corpora: tuple[CorpusName, ...] = (
            "official_lore",
            "story_navigation",
            *((("bh3text_dialogue",)) if config.allow_unverified_transcripts else ()),
        )
        chunks, warnings = LoreCorpus(config).load(corpora)
        started = time.perf_counter()
        index = HashedVectorIndex.build(chunks)
        build_time_ms = (time.perf_counter() - started) * 1000
        metadata = index.write(
            config.index_path,
            prototype_only=True,
            build_time_ms=build_time_ms,
        )
        payload = {
            **metadata,
            "index_size_bytes": config.index_path.stat().st_size,
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
    else:
        payload = {
            "index_exists": config.index_path.exists(),
            "index_path": str(config.index_path.relative_to(config.index_path.parents[2])),
            "prototype_only": True,
            "production_enabled": False,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
