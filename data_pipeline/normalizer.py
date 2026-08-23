"""Normalize crawled pages, assign quality status, and extract entity candidates."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from data_pipeline.config import CORE_CHARACTERS, CORE_CONCEPTS, PipelinePaths, SCOPE_KEYWORDS
from data_pipeline.relevance import clean_content_for_url, classify_page, is_discovery_index_url
from data_pipeline.schemas import CandidateAuditRecord, CleanedDocument, LoreEntity, PageDocument
from data_pipeline.utils import content_hash, read_jsonl, write_jsonl


# This catalog limits extraction scope; it is not an independent lore source.
# Every emitted entity must occur in accepted official text and remains pending.
ENTITY_CATALOG: dict[str, tuple[str, str]] = {
    "爱莉希雅": ("elysia", "character"),
    "逐火十三英桀": ("thirteen_flame_chasers", "faction"),
    "逐火之蛾": ("moth_who_chases_the_flame", "faction"),
    "前文明": ("previous_era", "concept"),
    "往世乐土": ("elysian_realm", "location"),
    "融合战士": ("mantis", "concept"),
    "记忆体": ("memory_simulacrum", "concept"),
    "英桀": ("flame_chaser", "concept"),
    "人之律者": ("herrscher_of_human", "concept"),
    "始源之律者": ("herrscher_of_origin", "concept"),
    "侵蚀之律者": ("herrscher_of_corruption", "concept"),
    "永世乐土": ("everlasting_elysium", "event"),
    "约束惨剧": ("tragedy_of_binding", "event"),
    "终焉": ("finality", "concept"),
    "伊甸": ("eden", "character"),
    "凯文": ("kevin", "character"),
    "阿波尼亚": ("aponia", "character"),
    "维尔薇": ("vill_v", "character"),
    "千劫": ("kalpas", "character"),
    "苏": ("su", "character"),
    "樱": ("sakura", "character"),
    "梅比乌斯": ("mobius", "character"),
    "华": ("hua", "character"),
    "科斯魔": ("kosma", "character"),
    "梅博士": ("dr_mei", "character"),
    "格蕾修": ("griseo", "character"),
    "帕朵菲莉丝": ("pardofelis", "character"),
}


def _entity_pattern(name: str) -> re.Pattern[str]:
    if len(name) == 1:
        return re.compile(
            rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(name)}"
            rf"(?![\u4e00-\u9fffA-Za-z0-9])"
        )
    return re.compile(re.escape(name))


def _evidence_snippets(content: str, name: str, limit: int = 3) -> list[str]:
    snippets: list[str] = []
    pattern = _entity_pattern(name)
    for sentence in re.split(r"(?<=[。！？!?；;])|\n+", content):
        value = sentence.strip()
        if pattern.search(value) and 2 <= len(value) <= 300 and value not in snippets:
            snippets.append(value)
        if len(snippets) >= limit:
            break
    return snippets


def _build_entities(documents: list[CleanedDocument]) -> list[LoreEntity]:
    sources: dict[str, set[str]] = defaultdict(set)
    document_ids: dict[str, set[str]] = defaultdict(set)
    mentions: dict[str, int] = defaultdict(int)
    evidence: dict[str, list[str]] = defaultdict(list)
    for document in documents:
        haystack = f"{document.title}\n{document.content}"
        for name in ENTITY_CATALOG:
            count = len(_entity_pattern(name).findall(haystack))
            if count == 0:
                continue
            sources[name].add(document.canonical_url)
            document_ids[name].add(document.document_id)
            mentions[name] += count
            for snippet in _evidence_snippets(document.content, name):
                if snippet not in evidence[name] and len(evidence[name]) < 5:
                    evidence[name].append(snippet)

    entities: list[LoreEntity] = []
    core_entities = set(CORE_CHARACTERS) | set(CORE_CONCEPTS)
    for name in sorted(sources, key=lambda value: ENTITY_CATALOG[value][0]):
        entity_id, entity_type = ENTITY_CATALOG[name]
        entities.append(
            LoreEntity(
                entity_id=entity_id,
                name=name,
                entity_type=entity_type,  # type: ignore[arg-type]
                source_urls=sorted(sources[name]),
                mention_count=mentions[name],
                source_document_ids=sorted(document_ids[name]),
                evidence_snippets=evidence[name],
                is_core_entity=name in core_entities,
                confidence=0.6,
                review_status="pending",
            )
        )
    return entities


def _audit_map(paths: PipelinePaths) -> dict[str, CandidateAuditRecord]:
    output: dict[str, CandidateAuditRecord] = {}
    for row in read_jsonl(paths.candidate_audit_jsonl):
        try:
            audit = CandidateAuditRecord.model_validate(row)
        except ValueError:
            continue
        output[audit.url] = audit
        if audit.final_url:
            output[audit.final_url] = audit
    return output


def _matches_scope(document: PageDocument, scope: str) -> bool:
    haystack = f"{document.title}\n{document.content}".lower()
    return any(keyword.lower() in haystack for keyword in SCOPE_KEYWORDS[scope])


def _quality(
    raw: PageDocument,
    *,
    cleaned_content: str,
    chinese_char_count: int,
    navigation_noise_ratio: float,
    duplicate_content: bool,
    audit: CandidateAuditRecord | None,
    scope: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    category = classify_page(raw.title, cleaned_content, raw.canonical_url)
    if audit is not None and audit.decision == "exclude":
        reasons.append(f"candidate_audit_excluded:{audit.reason}")
    if is_discovery_index_url(raw.canonical_url):
        reasons.append("discovery_navigation_page")
    if not _matches_scope(raw, scope):
        reasons.append("out_of_scope")
    if chinese_char_count < 200:
        reasons.append("insufficient_chinese_content")
    if duplicate_content:
        reasons.append("duplicate_content")
    if category == "gameplay":
        reasons.append("gameplay_or_numeric_page")
    if reasons:
        return "rejected", reasons

    review_reasons: list[str] = []
    if category == "mixed":
        review_reasons.append("mixed_lore_and_gameplay")
    elif category == "unknown":
        review_reasons.append("uncertain_page_category")
    if navigation_noise_ratio > 0.25:
        review_reasons.append("high_navigation_noise")
    if review_reasons:
        return "needs_review", review_reasons
    return "accepted", ["passed_quality_rules"]


def normalize_documents(
    paths: PipelinePaths | None = None,
    *,
    scope: str = "elysia",
) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    if scope not in SCOPE_KEYWORDS:
        raise ValueError(f"Unsupported scope: {scope}")
    rows = read_jsonl(paths.raw_documents)
    audits = _audit_map(paths)
    documents: list[CleanedDocument] = []
    seen_hashes: set[str] = set()
    invalid = 0
    duplicates = 0

    for row in rows:
        try:
            raw = PageDocument.model_validate(row)
        except ValueError:
            invalid += 1
            continue
        cleaned = clean_content_for_url(raw.content, raw.canonical_url)
        digest = content_hash(cleaned.content)
        duplicate_content = digest in seen_hashes
        if duplicate_content:
            duplicates += 1
        else:
            seen_hashes.add(digest)
        status, reasons = _quality(
            raw,
            cleaned_content=cleaned.content,
            chinese_char_count=cleaned.chinese_char_count,
            navigation_noise_ratio=cleaned.navigation_noise_ratio,
            duplicate_content=duplicate_content,
            audit=audits.get(raw.canonical_url),
            scope=scope,
        )
        payload: dict[str, Any] = raw.model_dump()
        payload.update(
            content=cleaned.content,
            content_hash=digest,
            chinese_char_count=cleaned.chinese_char_count,
            navigation_noise_ratio=cleaned.navigation_noise_ratio,
            duplicate_paragraph_count=cleaned.duplicate_paragraph_count,
            quality_status=status,
            quality_reasons=reasons,
        )
        documents.append(CleanedDocument.model_validate(payload))

    write_jsonl(
        paths.cleaned_documents,
        [document.model_dump(mode="json") for document in documents],
    )
    accepted = [doc for doc in documents if doc.quality_status == "accepted"]
    entities = _build_entities(accepted)
    write_jsonl(paths.entities, [entity.model_dump(mode="json") for entity in entities])
    return {
        "raw_documents": len(rows),
        "cleaned_documents": len(documents),
        "accepted_documents": len(accepted),
        "needs_review_documents": sum(
            doc.quality_status == "needs_review" for doc in documents
        ),
        "rejected_documents": sum(
            doc.quality_status == "rejected" for doc in documents
        ),
        "invalid_documents": invalid,
        "content_duplicates": duplicates,
        "pending_entities": len(entities),
    }
