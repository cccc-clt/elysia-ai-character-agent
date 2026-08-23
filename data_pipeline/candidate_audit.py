"""Low-rate candidate metadata audit and deterministic relevance ranking."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from data_pipeline.config import (
    CrawlSettings,
    PipelinePaths,
    RelevanceScoringConfig,
)
from data_pipeline.crawler import OfficialLoreCrawler
from data_pipeline.relevance import clean_content_for_url, score_candidate
from data_pipeline.schemas import CandidateAuditRecord, PageDocument
from data_pipeline.utils import normalize_url, read_json, read_jsonl, utc_now, write_jsonl


def _source_type(url: str) -> str:
    domain = (urlsplit(url).hostname or "").lower()
    if domain == "baike.mihoyo.com":
        return "official_wiki"
    if domain == "comic.bh3.com":
        return "official_comic"
    return "official_site"


def _excerpt(text: str, limit: int = 260) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_markdown(path: Path, records: list[CandidateAuditRecord]) -> None:
    included = sum(record.decision == "include" for record in records)
    lines = [
        "# 爱莉希雅候选 URL 审计",
        "",
        f"- 候选总数：{len(records)}",
        f"- 纳入：{included}",
        f"- 排除：{len(records) - included}",
        "- 评分方式：本地确定性规则，不调用付费 LLM。",
        "",
        "| 优先级 | 得分 | 决策 | 状态 | 分类 | 标题 | 命中关键词 | 原因 | URL |",
        "|---:|---:|---|---|---|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            "| {priority} | {score} | {decision} | {status} | {category} | "
            "{title} | {keywords} | {reason} | {url} |".format(
                priority=record.crawl_priority,
                score=record.relevance_score,
                decision=record.decision,
                status=record.metadata_status,
                category=record.page_category,
                title=_markdown_cell(record.title),
                keywords=_markdown_cell("、".join(record.matched_keywords)),
                reason=_markdown_cell(record.reason),
                url=record.url,
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _score_record(
    *,
    url: str,
    title: str,
    content: str,
    metadata_status: str,
    http_status: int | None,
    final_url: str,
    diagnostic_note: str,
    scoring: RelevanceScoringConfig,
) -> CandidateAuditRecord:
    cleaned = clean_content_for_url(content, url)
    relevance = score_candidate(
        title=title,
        content=content,
        url=url,
        metadata_status=metadata_status,
        config=scoring,
    )
    effective_status = metadata_status
    reason = relevance.reason
    if (
        metadata_status == "success"
        and cleaned.chinese_char_count < scoring.minimum_chinese_chars
    ):
        effective_status = "insufficient_content"
        reason = (
            "有效中文正文不足（insufficient_content）；"
            f"页面分类为 {relevance.page_category}"
        )
    return CandidateAuditRecord(
        url=url,
        title=title or "无法获取标题",
        source_type=_source_type(url),  # type: ignore[arg-type]
        matched_keywords=list(relevance.matched_keywords),
        relevance_score=relevance.relevance_score,
        decision=relevance.decision,  # type: ignore[arg-type]
        reason=reason,
        crawl_priority=1,
        score_breakdown=list(relevance.score_breakdown),
        metadata_status=effective_status,  # type: ignore[arg-type]
        page_category=relevance.page_category,  # type: ignore[arg-type]
        chinese_char_count=cleaned.chinese_char_count,
        summary_excerpt=_excerpt(cleaned.content),
        http_status=http_status,
        final_url=final_url,
        diagnostic_note=diagnostic_note,
        audited_at=utc_now(),
    )


def audit_candidates(
    paths: PipelinePaths | None = None,
    *,
    crawl_settings: CrawlSettings | None = None,
    scoring: RelevanceScoringConfig | None = None,
    refresh: bool = False,
    crawler: OfficialLoreCrawler | None = None,
) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    crawl_settings = crawl_settings or CrawlSettings(max_pages=30)
    scoring = scoring or RelevanceScoringConfig()
    manifest = read_json(paths.manifest, {"discovered_urls": [], "records": []})
    candidates = list(
        dict.fromkeys(
            normalize_url(str(url))
            for url in manifest.get("discovered_urls", [])
            if normalize_url(str(url))
        )
    )
    raw_documents = [
        PageDocument.model_validate(row) for row in read_jsonl(paths.raw_documents)
    ]
    raw_by_url = {normalize_url(doc.canonical_url): doc for doc in raw_documents}
    raw_by_id = {doc.document_id: doc for doc in raw_documents}
    for record in manifest.get("records", []):
        document = raw_by_id.get(str(record.get("document_id", "")))
        if document:
            raw_by_url[normalize_url(str(record.get("url", "")))] = document

    cached: dict[str, CandidateAuditRecord] = {}
    if not refresh:
        for row in read_jsonl(paths.candidate_audit_jsonl):
            try:
                record = CandidateAuditRecord.model_validate(row)
            except ValueError:
                continue
            cached[normalize_url(record.url)] = record

    owns_crawler = crawler is None
    crawler = crawler or OfficialLoreCrawler(crawl_settings, paths)
    records: list[CandidateAuditRecord] = []
    network_inspections = 0
    try:
        for url in candidates:
            raw = raw_by_url.get(url)
            if raw is not None:
                records.append(
                    _score_record(
                        url=url,
                        title=raw.title,
                        content=raw.content,
                        metadata_status="success",
                        http_status=200,
                        final_url=raw.canonical_url,
                        diagnostic_note="使用已采集 raw 文档进行审计，未新增网络请求",
                        scoring=scoring,
                    )
                )
                continue
            if url in cached:
                records.append(cached[url])
                continue
            network_inspections += 1
            observation = crawler.inspect_public_url(url)
            metadata_status = str(observation.get("metadata_status", "failed"))
            content = str(observation.get("content", ""))
            reason = str(observation.get("reason", ""))
            records.append(
                _score_record(
                    url=url,
                    title=str(observation.get("title", "无法获取标题")),
                    content=content,
                    metadata_status=metadata_status,
                    http_status=observation.get("http_status"),
                    final_url=str(observation.get("final_url", "")),
                    diagnostic_note=reason,
                    scoring=scoring,
                )
            )
    finally:
        if owns_crawler:
            crawler.close()

    category_order = {"lore": 0, "mixed": 1, "unknown": 2, "gameplay": 3, "navigation": 4}
    records.sort(
        key=lambda record: (
            0 if record.decision == "include" else 1,
            -record.relevance_score,
            category_order.get(record.page_category, 9),
            record.title,
            record.url,
        )
    )
    ranked = [
        record.model_copy(update={"crawl_priority": index})
        for index, record in enumerate(records, 1)
    ]
    write_jsonl(
        paths.candidate_audit_jsonl,
        [record.model_dump(mode="json") for record in ranked],
    )
    _write_markdown(paths.candidate_audit_markdown, ranked)
    return {
        "candidates": len(ranked),
        "included": sum(record.decision == "include" for record in ranked),
        "excluded": sum(record.decision == "exclude" for record in ranked),
        "metadata_success": sum(
            record.metadata_status == "success" for record in ranked
        ),
        "metadata_insufficient": sum(
            record.metadata_status == "insufficient_content" for record in ranked
        ),
        "metadata_failed": sum(
            record.metadata_status == "failed" for record in ranked
        ),
        "robots_disallowed": sum(
            record.metadata_status == "robots_disallowed" for record in ranked
        ),
        "network_inspections": network_inspections,
    }
