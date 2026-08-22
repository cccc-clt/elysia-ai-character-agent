"""Command-line entry point for the official lore data pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from data_pipeline.candidate_audit import audit_candidates
from data_pipeline.bh3text import build_bh3text, crawl_bh3text, discover_bh3text
from data_pipeline.bh3helper import (
    bh3helper_status,
    build_story_navigation,
    discover_bh3helper,
    map_duplicate_sources,
)
from data_pipeline.chunker import build_rag
from data_pipeline.config import CrawlSettings, PipelinePaths
from data_pipeline.coverage import build_coverage
from data_pipeline.crawler import OfficialLoreCrawler
from data_pipeline.discovery import discover_official_sources
from data_pipeline.manual_official import import_manual_records, review_manual_records
from data_pipeline.normalizer import normalize_documents
from data_pipeline.quality_report import generate_quality_report
from data_pipeline.relation_extractor import extract_relations
from data_pipeline.source_inventory import build_source_inventory
from data_pipeline.utils import read_json, read_jsonl
from data_pipeline.video_sources import (
    build_video_review,
    inspect_videos,
    process_all_video_subtitles,
    process_video_subtitles,
)


def _print(payload: dict[str, Any]) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def pipeline_status(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    manifest = read_json(paths.manifest, {"discovered_urls": [], "records": []})
    records = manifest.get("records", [])
    cleaned_rows = read_jsonl(paths.cleaned_documents)
    audit_rows = read_jsonl(paths.candidate_audit_jsonl)
    vector_readiness = read_json(paths.vector_readiness, {})
    result = {
        "discovered": len(set(manifest.get("discovered_urls", []))),
        "success": 0,
        "skipped": 0,
        "robots_disallowed": 0,
        "failed": 0,
        "duplicate": 0,
        "raw_documents": len(read_jsonl(paths.raw_documents)),
        "candidate_urls": len(audit_rows),
        "candidate_included": sum(row.get("decision") == "include" for row in audit_rows),
        "candidate_excluded": sum(row.get("decision") == "exclude" for row in audit_rows),
        "cleaned_documents": len(cleaned_rows),
        "accepted_documents": sum(row.get("quality_status") == "accepted" for row in cleaned_rows),
        "needs_review_documents": sum(row.get("quality_status") == "needs_review" for row in cleaned_rows),
        "rejected_documents": sum(row.get("quality_status") == "rejected" for row in cleaned_rows),
        "chunks": len(read_jsonl(paths.chunks)),
        "pending_entities": len(read_jsonl(paths.entities)),
        "pending_relations": len(read_jsonl(paths.relations_pending)),
        "confirmed_relations": len(read_jsonl(paths.relations_confirmed)),
        "manual_pending_records": len(read_jsonl(paths.manual_pending_index)),
        "comic_metadata_records": len(read_jsonl(paths.comic_metadata)),
        "character_profile_records": len(read_jsonl(paths.character_profiles)),
        "video_metadata_records": len(list(paths.video_metadata_dir.glob("BV*.json"))),
        "pending_video_chunks": len(read_jsonl(paths.video_chunks)),
        "video_audit_records": len(read_jsonl(paths.video_audit_jsonl)),
        "bh3text_candidate_scenes": len(
            read_jsonl(paths.bh3text_candidate_audit_jsonl)
        ),
        "bh3text_documents": len(read_jsonl(paths.bh3text_documents)),
        "bh3text_chunks": len(read_jsonl(paths.bh3text_chunks)),
        "bh3text_evidence_edges": len(read_jsonl(paths.dialogue_evidence_edges)),
        "bh3text_pending_relations": len(
            read_jsonl(paths.bh3text_relations_pending)
        ),
        "bh3text_verification_scenes": len(
            read_jsonl(paths.bh3text_transcript_verification_jsonl)
        ),
        "bh3text_reviewed_scenes": int(
            vector_readiness.get("actual", {}).get("reviewed_scenes", 0)
        ),
        "bh3text_vector_ready": int(bool(vector_readiness.get("vector_ready", False))),
        **{f"bh3helper_{key}": value for key, value in bh3helper_status(paths).items()},
    }
    for record in records:
        status = str(record.get("status", ""))
        if status in result:
            result[status] += 1
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m data_pipeline.cli",
        description="Collect and structure allowlisted public official Honkai Impact 3rd lore pages.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="crawl public official pages")
    crawl.add_argument("--scope", default="elysia")
    crawl.add_argument("--max-pages", type=int, default=30)
    crawl.add_argument("--delay", type=float, default=3.0)
    crawl.add_argument("--concurrency", type=int, default=1)
    crawl.add_argument("--timeout", type=float, default=20.0)
    crawl.add_argument("--retries", type=int, default=2)
    crawl.add_argument("--seeds", type=Path)
    crawl.add_argument("--dry-run", action="store_true")
    crawl.add_argument(
        "--accepted-candidates-only",
        action="store_true",
        help="require candidate audit and crawl only decision=include URLs",
    )
    crawl.add_argument(
        "--no-render",
        action="store_true",
        help="disable Playwright fallback for JavaScript-only pages",
    )

    audit = subparsers.add_parser(
        "audit-candidates",
        help="inspect, score, and rank discovered candidate URLs before crawling",
    )
    audit.add_argument("--scope", default="elysia")
    audit.add_argument("--delay", type=float, default=3.0)
    audit.add_argument("--timeout", type=float, default=20.0)
    audit.add_argument("--retries", type=int, default=2)
    audit.add_argument("--refresh", action="store_true")
    audit.add_argument(
        "--no-render",
        action="store_true",
        help="disable Playwright fallback for JavaScript-only pages",
    )

    discover = subparsers.add_parser(
        "discover", help="discover relevant links from registered public Tier A sources"
    )
    discover.add_argument("--scope", default="elysia")
    discover.add_argument(
        "--sources",
        required=True,
        help="comma-separated registry source ids",
    )
    discover.add_argument("--max-candidates", type=int, default=150)
    discover.add_argument("--delay", type=float, default=3.0)
    discover.add_argument("--timeout", type=float, default=20.0)
    discover.add_argument("--retries", type=int, default=2)
    discover.add_argument("--no-render", action="store_true")

    discover_bh3text_parser = subparsers.add_parser(
        "discover-bh3text",
        help="discover and audit targeted BH3Text dialogue links without storing text",
    )
    discover_bh3text_parser.add_argument("--scope", default="elysia")
    discover_bh3text_parser.add_argument("--max-candidates", type=int, default=300)
    discover_bh3text_parser.add_argument("--delay", type=float, default=3.0)
    discover_bh3text_parser.add_argument("--timeout", type=float, default=20.0)

    crawl_bh3text_parser = subparsers.add_parser(
        "crawl-bh3text",
        help="crawl audited BH3Text details into an isolated supplemental corpus",
    )
    crawl_bh3text_parser.add_argument("--scope", default="elysia")
    crawl_bh3text_parser.add_argument("--max-pages", type=int, default=100)
    crawl_bh3text_parser.add_argument(
        "--mode", choices=("standard", "coverage-gap"), default="standard"
    )
    crawl_bh3text_parser.add_argument("--max-new-pages", type=int, default=40)
    crawl_bh3text_parser.add_argument("--delay", type=float, default=3.0)
    crawl_bh3text_parser.add_argument("--concurrency", type=int, default=1)
    crawl_bh3text_parser.add_argument("--timeout", type=float, default=20.0)
    crawl_bh3text_parser.add_argument(
        "--accepted-candidates-only",
        action="store_true",
        help="crawl only audit rows with decision=include",
    )
    subparsers.add_parser(
        "build-bh3text",
        help="rebuild BH3Text chunks, evidence edges, verification samples and readiness",
    )

    discover_bh3helper_parser = subparsers.add_parser(
        "discover-bh3helper",
        help="discover public BH3Helper navigation metadata without story text",
    )
    discover_bh3helper_parser.add_argument("--scope", default="elysia")
    discover_bh3helper_parser.add_argument("--max-pages", type=int, default=30)
    discover_bh3helper_parser.add_argument("--delay", type=float, default=3.0)
    discover_bh3helper_parser.add_argument("--concurrency", type=int, default=1)
    discover_bh3helper_parser.add_argument("--timeout", type=float, default=20.0)
    subparsers.add_parser(
        "build-story-navigation",
        help="build the isolated metadata-only story navigation index",
    )
    subparsers.add_parser(
        "map-duplicate-sources",
        help="map BH3Helper embedded dialogue to BH3Text without copying text",
    )

    manual_import = subparsers.add_parser(
        "import-manual", help="validate pending manually captured official records"
    )
    manual_import.add_argument("--input", type=Path, required=True)
    subparsers.add_parser(
        "review-manual", help="generate manual review checklist without accepting records"
    )

    normalize = subparsers.add_parser("normalize", help="normalize raw page JSONL")
    normalize.add_argument("--scope", default="elysia")
    relations = subparsers.add_parser(
        "extract-relations", help="write evidence-backed candidates to pending JSONL"
    )
    relations.add_argument("--use-llm", action="store_true")
    relations.add_argument("--model")
    subparsers.add_parser("build-rag", help="build JSONL and Markdown chunks")
    subparsers.add_parser("quality-report", help="regenerate the quality report")
    subparsers.add_parser("build-coverage", help="build topic coverage and review files")
    subparsers.add_parser(
        "build-source-inventory",
        help="build source-tier inventory and metadata-only deduplication report",
    )
    inspect_video = subparsers.add_parser(
        "inspect-videos",
        help="inspect public Bilibili page metadata once without login/cookies",
    )
    inspect_video.add_argument("--delay", type=float, default=3.0)
    inspect_video.add_argument("--timeout", type=float, default=20.0)
    inspect_video.add_argument("--seed-file", type=Path)
    process_video = subparsers.add_parser(
        "process-video-subtitles",
        help="process a public subtitle track or local subtitle/manual record",
    )
    process_video.add_argument("--video-id")
    process_video.add_argument("--input", type=Path)
    process_video.add_argument("--timeout", type=float, default=20.0)
    process_video.add_argument("--delay", type=float, default=3.0)
    subparsers.add_parser(
        "build-video-review",
        help="build pending-only subtitle/fact review workbenches",
    )
    subparsers.add_parser("status", help="show collection and output counts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = PipelinePaths()
    try:
        if args.command == "crawl":
            if args.accepted_candidates_only and not paths.candidate_audit_jsonl.exists():
                raise ValueError(
                    "--accepted-candidates-only requires elysia_candidate_audit.jsonl"
                )
            settings = CrawlSettings(
                scope=args.scope,
                max_pages=args.max_pages,
                delay_seconds=args.delay,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout,
                max_retries=args.retries,
                render_dynamic=not args.no_render,
            )
            crawler = OfficialLoreCrawler(settings, paths)
            payload = (
                crawler.dry_run(args.seeds)
                if args.dry_run
                else crawler.crawl(args.seeds)
            )
        elif args.command == "discover":
            settings = CrawlSettings(
                scope=args.scope,
                max_pages=50,
                delay_seconds=args.delay,
                concurrency=1,
                timeout_seconds=args.timeout,
                max_retries=args.retries,
                render_dynamic=not args.no_render,
            )
            payload = discover_official_sources(
                paths,
                scope=args.scope,
                source_ids=[
                    item.strip() for item in args.sources.split(",") if item.strip()
                ],
                max_candidates=args.max_candidates,
                crawl_settings=settings,
            )
        elif args.command == "audit-candidates":
            settings = CrawlSettings(
                scope=args.scope,
                max_pages=30,
                delay_seconds=args.delay,
                concurrency=1,
                timeout_seconds=args.timeout,
                max_retries=args.retries,
                render_dynamic=not args.no_render,
            )
            payload = audit_candidates(
                paths,
                crawl_settings=settings,
                refresh=args.refresh,
            )
        elif args.command == "discover-bh3text":
            payload = discover_bh3text(
                paths,
                scope=args.scope,
                max_candidates=args.max_candidates,
                delay_seconds=args.delay,
                timeout_seconds=args.timeout,
            )
        elif args.command == "crawl-bh3text":
            payload = crawl_bh3text(
                paths,
                scope=args.scope,
                max_pages=args.max_pages,
                mode=args.mode,
                max_new_pages=args.max_new_pages,
                delay_seconds=args.delay,
                concurrency=args.concurrency,
                accepted_candidates_only=(
                    args.accepted_candidates_only or args.mode == "coverage-gap"
                ),
                timeout_seconds=args.timeout,
            )
        elif args.command == "build-bh3text":
            payload = build_bh3text(paths)
        elif args.command == "discover-bh3helper":
            payload = discover_bh3helper(
                paths,
                scope=args.scope,
                max_pages=args.max_pages,
                delay_seconds=args.delay,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout,
            )
        elif args.command == "build-story-navigation":
            payload = build_story_navigation(paths)
        elif args.command == "map-duplicate-sources":
            payload = map_duplicate_sources(paths)
        elif args.command == "normalize":
            payload = normalize_documents(paths, scope=args.scope)
        elif args.command == "import-manual":
            payload = import_manual_records(args.input, paths)
        elif args.command == "review-manual":
            payload = review_manual_records(paths)
        elif args.command == "extract-relations":
            payload = extract_relations(
                paths, use_llm=args.use_llm, model=args.model
            )
        elif args.command == "build-rag":
            payload = build_rag(paths)
            payload.update(
                {
                    f"quality_{key}": value
                    for key, value in generate_quality_report(paths).items()
                }
            )
        elif args.command == "quality-report":
            payload = generate_quality_report(paths)
        elif args.command == "build-coverage":
            payload = build_coverage(paths)
        elif args.command == "build-source-inventory":
            payload = build_source_inventory(paths)
        elif args.command == "inspect-videos":
            video_paths = (
                replace(paths, video_seed_file=args.seed_file)
                if args.seed_file is not None
                else paths
            )
            payload = inspect_videos(
                video_paths,
                delay_seconds=args.delay,
                timeout_seconds=args.timeout,
            )
        elif args.command == "process-video-subtitles":
            if args.input is not None and not args.video_id:
                raise ValueError("--input requires --video-id")
            payload = (
                process_video_subtitles(
                    args.video_id,
                    paths,
                    input_path=args.input,
                    timeout_seconds=args.timeout,
                )
                if args.video_id
                else process_all_video_subtitles(
                    paths,
                    delay_seconds=args.delay,
                    timeout_seconds=args.timeout,
                )
            )
        elif args.command == "build-video-review":
            payload = build_video_review(paths)
        else:
            payload = pipeline_status(paths)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    _print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
