"""Metadata-only integrity checks for aliases, chapters, and source deduplication."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from data_pipeline.config import CORE_CHARACTERS
from data_pipeline.schemas import BH3TextChunk, BH3TextDocument
from data_pipeline.utils import content_hash, normalize_url, utc_now, write_json


CHAPTER_PATH_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"/dialog/er/1/"), "往世乐土", "在无限的阴影之中"),
    (re.compile(r"/dialog/er/2/"), "往世乐土", "致世界上的另一个我"),
    (re.compile(r"/dialog/er/3/"), "往世乐土", "愿时光永驻此刻，愿明日——"),
    (re.compile(r"/dialog/mainline/1/29/"), "主线第一部", "第二十九章 来自乐土"),
    (re.compile(r"/dialog/mainline/1/30/"), "主线第一部", "第三十章 英雄们的葬礼"),
    (re.compile(r"/dialog/mainline/1/31/"), "主线第一部", "第三十一章 因你而在的故事"),
)

TOPIC_CANONICAL_FORMS = {
    "黄金庭园": "黄金庭院",
    "约束的惨剧": "约束惨剧",
}

SEMANTIC_ALIAS_CANDIDATES = (
    {
        "base_name": "爱莉希雅",
        "candidate_name": "真我·人之律者",
        "status": "blocked_human",
        "reason": "身份、装甲或角色别名关系需要人工判断",
    },
    {
        "base_name": "爱莉希雅",
        "candidate_name": "粉色妖精小姐♪",
        "status": "blocked_human",
        "reason": "装甲名称与角色实体是否合并需要人工判断",
    },
    {
        "base_name": "爱莉希雅",
        "candidate_name": "妖精爱莉",
        "status": "blocked_human",
        "reason": "剧情形态或独立实体边界需要人工判断",
    },
    {
        "base_name": "维尔薇",
        "candidate_name": "极恶/专家/大魔术师等维尔薇称谓",
        "status": "blocked_human",
        "reason": "人格称谓与角色实体边界需要人工判断",
    },
)


def expected_chapter_for_url(source_url: str) -> tuple[str, str] | None:
    canonical = normalize_url(source_url)
    for pattern, arc, chapter in CHAPTER_PATH_RULES:
        if pattern.search(canonical):
            return arc, chapter
    return None


def normalize_bh3text_metadata(
    documents: Iterable[BH3TextDocument],
) -> tuple[list[BH3TextDocument], dict[str, int]]:
    """Apply only deterministic metadata fixes; never merge semantic aliases."""

    repairs = Counter()
    output: list[BH3TextDocument] = []
    for document in documents:
        updates: dict[str, Any] = {}
        expected = expected_chapter_for_url(document.source_url)
        if expected and (document.arc, document.chapter) != expected:
            updates["arc"], updates["chapter"] = expected
            repairs["chapter_attribution"] += 1
        topics = sorted(
            {
                TOPIC_CANONICAL_FORMS.get(topic, topic)
                for topic in document.topic_names
            }
        )
        if topics != sorted(set(document.topic_names)):
            updates["topic_names"] = topics
            repairs["topic_surface_normalization"] += 1
        characters = sorted(set(document.character_names))
        if "雷电芽衣" in characters and "芽衣" in characters:
            characters.remove("芽衣")
            repairs["nested_character_name"] += 1
        if characters != document.character_names:
            updates["character_names"] = characters
        output.append(document.model_copy(update=updates) if updates else document)
    return output, dict(sorted(repairs.items()))


def _duplicates(values: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for value, identifier in values:
        if value and identifier:
            groups[value].add(identifier)
    return [
        {"value": value, "identifiers": sorted(identifiers)}
        for value, identifiers in sorted(groups.items())
        if len(identifiers) > 1
    ]


def build_lore_integrity_audit(
    documents: list[BH3TextDocument],
    chunks: list[BH3TextChunk],
    *,
    repairs: dict[str, int],
    json_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    chapter_mismatches = []
    speaker_variants: Counter[str] = Counter()
    ambiguous_single_character_metadata: Counter[str] = Counter()
    for document in documents:
        expected = expected_chapter_for_url(document.source_url)
        if expected and (document.arc, document.chapter) != expected:
            chapter_mismatches.append(
                {
                    "document_id": document.document_id,
                    "source_url": document.source_url,
                    "actual_arc": document.arc,
                    "actual_chapter": document.chapter,
                    "expected_arc": expected[0],
                    "expected_chapter": expected[1],
                }
            )
        speakers = {turn.speaker for turn in document.dialogue_turns if turn.speaker}
        for speaker in speakers:
            for root in CORE_CHARACTERS:
                if speaker != root and root in speaker:
                    speaker_variants[f"{root} <- {speaker}"] += 1
        for name in ("华", "苏", "樱"):
            if (
                name in document.character_names
                and name not in document.title
                and name not in speakers
            ):
                ambiguous_single_character_metadata[name] += 1

    normalized_url_duplicates = _duplicates(
        (normalize_url(row.source_url), row.document_id) for row in documents
    )
    normalized_content_duplicates = _duplicates(
        (
            content_hash(re.sub(r"\s+", "", "\n".join(turn.text for turn in row.dialogue_turns))),
            row.document_id,
        )
        for row in documents
    )
    duplicate_document_ids = _duplicates(
        (row.document_id, row.source_url) for row in documents
    )
    duplicate_chunk_ids = _duplicates(
        (row.chunk_id, f"{row.document_id}:{row.turn_start}-{row.turn_end}")
        for row in chunks
    )
    payload = {
        "generated_at": utc_now(),
        "automatic_repairs": repairs,
        "chapter_attribution": {
            "checked_documents": len(documents),
            "remaining_mismatches": chapter_mismatches,
        },
        "aliases": {
            "safe_surface_normalizations": TOPIC_CANONICAL_FORMS,
            "semantic_alias_candidates": list(SEMANTIC_ALIAS_CANDIDATES),
            "speaker_variants": [
                {"variant": value, "document_count": count, "status": "blocked_human"}
                for value, count in sorted(speaker_variants.items())
            ],
            "ambiguous_single_character_metadata": dict(
                sorted(ambiguous_single_character_metadata.items())
            ),
            "semantic_aliases_auto_merged": 0,
        },
        "deduplication": {
            "normalized_source_url_duplicates": normalized_url_duplicates,
            "normalized_dialogue_text_duplicates": normalized_content_duplicates,
            "duplicate_document_ids": duplicate_document_ids,
            "duplicate_chunk_ids": duplicate_chunk_ids,
        },
        "source_tier_guard": {
            "bh3text_official_documents": 0,
            "confirmed_relations_generated": 0,
        },
    }
    write_json(json_path, payload)
    lines = [
        "# Lore Entity, Chapter and Deduplication Integrity Audit",
        "",
        "> 本报告只含metadata与计数。语义别名和人格称谓均未自动合并。",
        "",
        "## Automatic repairs",
        "",
    ]
    lines.extend(
        f"- {key}: {value}" for key, value in payload["automatic_repairs"].items()
    )
    if not payload["automatic_repairs"]:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Chapter attribution",
            "",
            f"- checked_documents: {len(documents)}",
            f"- remaining_mismatches: {len(chapter_mismatches)}",
            "",
            "## Alias and same-name review",
            "",
            f"- semantic_aliases_auto_merged: 0",
            f"- speaker_variants_pending: {len(speaker_variants)}",
            "- ambiguous_single_character_metadata: "
            + ", ".join(
                f"{key}={value}"
                for key, value in sorted(ambiguous_single_character_metadata.items())
            ),
            "",
            "## Deduplication",
            "",
        ]
    )
    lines.extend(
        f"- {key}: {len(value)}"
        for key, value in payload["deduplication"].items()
    )
    lines.extend(
        [
            "",
            "BH3Text仍为Tier B-primary-transcript；本审计不会生成confirmed关系。",
        ]
    )
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return payload
