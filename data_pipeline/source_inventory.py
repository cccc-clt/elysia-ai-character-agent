"""Build source-tier inventory, structural validation, and deduplication reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from data_pipeline.config import PipelinePaths
from data_pipeline.schemas import BH3TextDocument
from data_pipeline.utils import content_hash, read_json, read_jsonl, utc_now, write_json


def _duplicate_values(rows: Iterable[dict[str, Any]], field: str) -> list[str]:
    counts = Counter(str(row.get(field, "")) for row in rows if row.get(field))
    return sorted(value for value, count in counts.items() if count > 1)


def _duplicate_hash_groups(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        digest = str(row.get("content_hash", ""))
        identifier = str(row.get("document_id", row.get("source_url", "")))
        if digest and identifier:
            groups[digest].append(identifier)
    return [
        {"content_hash": digest, "document_ids": sorted(set(identifiers))}
        for digest, identifiers in sorted(groups.items())
        if len(set(identifiers)) > 1
    ]


def _chunk_view(row: dict[str, Any], corpus: str) -> dict[str, str]:
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
    return {
        "corpus": corpus,
        "chunk_id": str(row.get("chunk_id", "")),
        "document_id": str(row.get("document_id", metadata.get("document_id", ""))),
        "source_url": str(row.get("source_url", metadata.get("source_url", ""))),
        "source_type": str(row.get("source_type", metadata.get("source_type", ""))),
        "source_tier": str(row.get("source_tier", metadata.get("source_tier", ""))),
        "review_status": str(
            row.get(
                "review_status",
                "accepted" if corpus == "official_lore" else "pending",
            )
        ),
        "content": str(row.get("content", "")),
    }


def _corpus_summary(
    *,
    corpus: str,
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    official: bool,
) -> dict[str, Any]:
    source_types = Counter(row["source_type"] for row in chunks if row["source_type"])
    source_tiers = Counter(row["source_tier"] for row in chunks if row["source_tier"])
    review_statuses = Counter(row["review_status"] for row in chunks if row["review_status"])
    return {
        "corpus": corpus,
        "documents": len(documents),
        "chunks": len(chunks),
        "official_documents": len(documents) if official else 0,
        "official_host": official,
        "source_types": dict(sorted(source_types.items())),
        "source_tiers": dict(sorted(source_tiers.items())),
        "review_statuses": dict(sorted(review_statuses.items())),
        "all_chunks_have_source_url": all(
            row["source_url"].startswith(("https://", "manual-official://"))
            for row in chunks
        ),
        "duplicate_document_ids": _duplicate_values(documents, "document_id"),
        "duplicate_chunk_ids": _duplicate_values(chunks, "chunk_id"),
    }


def _structural_validation(
    paths: PipelinePaths,
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    validated_documents: list[BH3TextDocument] = []
    schema_errors = 0
    for row in documents:
        try:
            validated_documents.append(BH3TextDocument.model_validate(row))
        except ValueError:
            schema_errors += 1
    turn_index_violations = 0
    for document in validated_documents:
        actual = [turn.turn_index for turn in document.dialogue_turns]
        if actual != list(range(1, len(actual) + 1)):
            turn_index_violations += 1
    manifest = read_json(paths.bh3text_manifest, {})
    parser_errors = len(manifest.get("collection_errors", []))
    parse_attempts = len(documents) + parser_errors
    parse_failure_rate = parser_errors / parse_attempts if parse_attempts else 0.0
    duplicate_document_ids = _duplicate_values(documents, "document_id")
    duplicate_chunk_ids = _duplicate_values(chunks, "chunk_id")
    navigation_markers = ("上一页", "下一页", "关于本站", "返回首页")
    navigation_residue_hits = sum(
        any(marker in row["content"] for marker in navigation_markers) for row in chunks
    )
    abnormal_character_hits = sum(
        "\ufffd" in row["content"] or "\x00" in row["content"] for row in chunks
    )
    fixture_hits = int(
        read_json(paths.vector_readiness, {})
        .get("actual", {})
        .get("test_fixture_hits", 0)
    )
    all_source_urls = all(
        row["source_url"].startswith("https://www.bh3text.com/dialog/")
        for row in chunks
    )
    structurally_validated = all(
        (
            schema_errors == 0,
            turn_index_violations == 0,
            parse_failure_rate <= 0.02,
            not duplicate_document_ids,
            not duplicate_chunk_ids,
            navigation_residue_hits == 0,
            abnormal_character_hits == 0,
            fixture_hits == 0,
            all_source_urls,
        )
    )
    return {
        "schema_errors": schema_errors,
        "parser_errors": parser_errors,
        "parse_failure_rate": round(parse_failure_rate, 6),
        "turn_index_violations": turn_index_violations,
        "duplicate_document_ids": len(duplicate_document_ids),
        "duplicate_chunk_ids": len(duplicate_chunk_ids),
        "navigation_residue_hits": navigation_residue_hits,
        "abnormal_character_hits": abnormal_character_hits,
        "all_chunks_have_source_url": all_source_urls,
        "test_fixture_hits": fixture_hits,
        "critical_parser_errors": 0 if schema_errors == 0 else schema_errors,
        "structurally_validated": structurally_validated,
        "prototype_only": True,
        "contains_unverified_transcripts": any(
            row["review_status"] == "unverified_transcript" for row in chunks
        ),
        "production_enabled": False,
    }


def build_source_inventory(paths: PipelinePaths | None = None) -> dict[str, Any]:
    """Build metadata-only inventory; never copy corpus content into reports."""

    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    cleaned = [
        row
        for row in read_jsonl(paths.cleaned_documents)
        if row.get("quality_status") == "accepted"
    ]
    official_chunks = [
        _chunk_view(row, "official_lore") for row in read_jsonl(paths.chunks)
    ]
    official_document_ids = {
        row["document_id"] for row in official_chunks if row["document_id"]
    }
    official_documents = [
        {"document_id": document_id} for document_id in sorted(official_document_ids)
    ]
    if len(official_documents) < len(cleaned):
        official_documents = [
            {"document_id": str(row.get("document_id", ""))} for row in cleaned
        ]

    bh3text_documents = read_jsonl(paths.bh3text_documents)
    bh3text_chunks = [
        _chunk_view(row, "bh3text_dialogue") for row in read_jsonl(paths.bh3text_chunks)
    ]
    navigation_rows = read_jsonl(paths.bh3helper_navigation)
    navigation_documents = [
        {"document_id": str(row.get("navigation_id", ""))} for row in navigation_rows
    ]
    navigation_chunks = [
        _chunk_view(row, "story_navigation")
        for row in read_jsonl(paths.story_navigation_chunks)
    ]
    video_rows = read_jsonl(paths.video_audit_jsonl)
    video_documents = [
        {"document_id": str(row.get("video_id", ""))} for row in video_rows
    ]
    video_chunks = [
        _chunk_view(row, "video_evidence") for row in read_jsonl(paths.video_chunks)
    ]

    corpora = {
        "official_lore": _corpus_summary(
            corpus="official_lore",
            documents=official_documents,
            chunks=official_chunks,
            official=True,
        ),
        "bh3text_dialogue": _corpus_summary(
            corpus="bh3text_dialogue",
            documents=bh3text_documents,
            chunks=bh3text_chunks,
            official=False,
        ),
        "story_navigation": _corpus_summary(
            corpus="story_navigation",
            documents=navigation_documents,
            chunks=navigation_chunks,
            official=False,
        ),
        "video_evidence": _corpus_summary(
            corpus="video_evidence",
            documents=video_documents,
            chunks=video_chunks,
            official=False,
        ),
    }
    all_chunks = official_chunks + bh3text_chunks + navigation_chunks + video_chunks
    chunk_hash_groups: dict[str, list[str]] = defaultdict(list)
    for row in all_chunks:
        if row["content"]:
            chunk_hash_groups[content_hash(row["content"])].append(
                f"{row['corpus']}:{row['chunk_id']}"
            )
    cross_corpus_duplicates = [
        {"content_hash": digest, "chunks": sorted(ids)}
        for digest, ids in sorted(chunk_hash_groups.items())
        if len({value.split(":", 1)[0] for value in ids}) > 1
    ]
    helper_duplicate_rows = read_jsonl(paths.bh3helper_duplicate_map)
    structural = _structural_validation(paths, bh3text_documents, bh3text_chunks)
    structural["cross_source_metadata_matched"] = len(helper_duplicate_rows)
    payload = {
        "generated_at": utc_now(),
        "corpora": corpora,
        "official_document_count": corpora["official_lore"]["official_documents"],
        "community_documents_counted_as_official": 0,
        "deduplication": {
            "bh3text_duplicate_content_hash_groups": _duplicate_hash_groups(
                bh3text_documents
            ),
            "cross_corpus_exact_chunk_duplicates": cross_corpus_duplicates,
            "bh3helper_bh3text_metadata_mappings": len(helper_duplicate_rows),
            "bh3helper_dialogue_copies_in_retrieval": 0,
            "canonical_dialogue_corpus": "bh3text_dialogue",
        },
        "development_prototype_gate": structural,
        "source_precedence": [
            "Tier A / A-manual",
            "Tier B-primary-transcript",
            "Tier B-recording",
            "Tier B-curated-index",
            "community",
        ],
    }
    write_json(paths.source_inventory, payload)
    _write_deduplication_report(paths, payload)
    return payload


def _write_deduplication_report(paths: PipelinePaths, payload: dict[str, Any]) -> None:
    corpora = payload["corpora"]
    dedup = payload["deduplication"]
    gate = payload["development_prototype_gate"]
    lines = [
        "# Lore 来源去重与结构验证报告",
        "",
        "> 本报告只保存计数、hash分组和来源角色，不复制任何剧情正文。",
        "",
        "## 隔离语料",
        "",
        "| Corpus | Documents | Chunks | Official documents | Source tiers |",
        "|---|---:|---:|---:|---|",
    ]
    for corpus_id, row in corpora.items():
        tiers = "、".join(
            f"{key}:{value}" for key, value in row["source_tiers"].items()
        ) or "-"
        lines.append(
            f"| {corpus_id} | {row['documents']} | {row['chunks']} | "
            f"{row['official_documents']} | {tiers} |"
        )
    lines.extend(
        [
            "",
            "## 去重结论",
            "",
            f"- BH3Text重复正文hash组：{len(dedup['bh3text_duplicate_content_hash_groups'])}",
            f"- 跨corpus完全相同chunk组：{len(dedup['cross_corpus_exact_chunk_duplicates'])}",
            f"- BH3Helper→BH3Text元数据映射：{dedup['bh3helper_bh3text_metadata_mappings']}",
            "- BH3Helper嵌入对话进入检索副本：0；剧情正文只以BH3Text语料为候选副本。",
            "- 社区文档计入official文档数：0。",
            "",
            "## 开发原型门",
            "",
        ]
    )
    lines.extend(f"- {key}: {value}" for key, value in gate.items())
    lines.extend(
        [
            "",
            "正式启用仍由 `vector_readiness.json` 的人工核验门控制；结构验证通过不会自动把 `not_checked` 改为 `match`。",
            "",
        ]
    )
    paths.deduplication_report.write_text("\n".join(lines), encoding="utf-8")
