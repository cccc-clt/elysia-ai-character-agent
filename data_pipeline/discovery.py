"""Tier-A public-link discovery without protected APIs or ID enumeration."""

from __future__ import annotations

import re
from collections import Counter, deque
from typing import Any
from urllib.parse import urlsplit

from data_pipeline.config import (
    CrawlSettings,
    NEWS_PROMO_MARKERS,
    PipelinePaths,
    SCOPE_KEYWORDS,
)
from data_pipeline.crawler import OfficialLoreCrawler
from data_pipeline.schemas import (
    OfficialCharacterProfile,
    OfficialComicMetadata,
    SourceDefinition,
)
from data_pipeline.source_registry import (
    discovery_sources,
    load_source_registry,
)
from data_pipeline.utils import (
    normalize_url,
    read_json,
    utc_now,
    write_json,
    write_jsonl,
)


CHARACTER_TARGETS = (
    "爱莉希雅",
    "真我·人之律者",
    "粉色妖精小姐",
    "阿波尼亚",
    "伊甸",
    "维尔薇",
    "梅比乌斯",
    "格蕾修",
    "帕朵菲莉丝",
    "华",
    "符华",
    "樱",
    "凯文",
)

COMIC_TARGETS = ("逐火之蛾", "前文明", "樱", "凯文", "梅博士", "融合战士")

WIKI_NAVIGATION_LABELS = (
    "搜索",
    "角色档案",
    "游戏PV",
    "剧情档案",
    "往世乐土",
    "追忆",
    "事件",
    "下一页",
)


def _matches_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        if len(keyword) == 1:
            if re.search(
                rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(keyword)}"
                rf"(?![\u4e00-\u9fffA-Za-z0-9])",
                text,
            ):
                return True
        elif keyword.lower() in text.lower():
            return True
    return False


def _scope_match(text: str, scope: str) -> bool:
    keywords = tuple(dict.fromkeys([
        *SCOPE_KEYWORDS[scope],
        "真我·人之律者",
        "粉色妖精小姐",
        "符华",
        "雷电芽衣",
    ]))
    return _matches_keyword(text, keywords)


def _negative_label(text: str) -> bool:
    return any(marker in text for marker in NEWS_PROMO_MARKERS)


def _candidate_link(source_id: str, url: str, label: str, scope: str) -> bool:
    path = urlsplit(url).path.rstrip("/")
    if not label or _negative_label(label) or not _scope_match(label, scope):
        return False
    if source_id == "official-characters":
        return path.startswith("/valkyries/")
    if source_id == "official-news":
        return path.startswith(("/content/", "/information/", "/news/"))
    if source_id == "official-wiki":
        return "/bh3/wiki/content/" in path
    return False


def _navigation_link(source_id: str, url: str, label: str) -> bool:
    path = urlsplit(url).path.rstrip("/")
    if source_id == "official-news":
        return path == "/news" or (
            path.startswith("/news/")
            and any(value in label for value in ("下一页", "更多", "新闻"))
        )
    if source_id == "official-wiki":
        return "/bh3/wiki/channel/" in path and any(
            value in label for value in WIKI_NAVIGATION_LABELS
        )
    return False


def _character_profiles(
    content: str,
    source_url: str,
) -> list[OfficialCharacterProfile]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    profiles: list[OfficialCharacterProfile] = []
    for target in CHARACTER_TARGETS:
        indexes = [index for index, line in enumerate(lines) if line == target]
        for index in indexes[:1]:
            nearby = [
                line
                for line in lines[index + 1 : index + 12]
                if not any(
                    marker in line
                    for marker in (
                        "武器类型",
                        "属性类型",
                        "伤害类型",
                        "技能",
                        "补给",
                        "装备",
                    )
                )
            ]
            introduction = " ".join(nearby).strip()
            if len(re.findall(r"[\u4e00-\u9fff]", introduction)) < 20:
                continue
            profiles.append(
                OfficialCharacterProfile(
                    character_name=target,
                    aliases=[],
                    introduction=introduction[:600],
                    identity_description=introduction[:300],
                    source_url=source_url,
                    retrieved_at=utc_now(),
                )
            )
    return profiles


def _comic_records(links: list[dict[str, str]]) -> list[OfficialComicMetadata]:
    records: list[OfficialComicMetadata] = []
    for link in links:
        label = str(link.get("label", "")).strip()
        url = normalize_url(str(link.get("url", "")))
        if not url or not label or not _matches_keyword(label, COMIC_TARGETS):
            continue
        records.append(
            OfficialComicMetadata(
                title=label,
                chapter="",
                summary="",
                source_url=url,
                content_available=False,
                manual_review_required=True,
            )
        )
    unique = {record.source_url: record for record in records}
    return list(unique.values())


def discover_official_sources(
    paths: PipelinePaths | None = None,
    *,
    scope: str = "elysia",
    source_ids: list[str],
    max_candidates: int = 150,
    crawl_settings: CrawlSettings | None = None,
    crawler: OfficialLoreCrawler | None = None,
) -> dict[str, Any]:
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    definitions = load_source_registry(paths=paths)
    selected = discovery_sources(definitions, source_ids)
    settings = crawl_settings or CrawlSettings(scope=scope, max_pages=50)
    owns_crawler = crawler is None
    crawler = crawler or OfficialLoreCrawler(settings, paths)
    manifest = read_json(
        paths.manifest,
        {"scope": scope, "discovered_urls": [], "records": []},
    )
    existing = list(dict.fromkeys(
        normalize_url(str(url))
        for url in manifest.get("discovered_urls", [])
        if normalize_url(str(url))
    ))
    candidates = list(existing)
    source_by_url = dict(manifest.get("discovery_sources", {}))
    per_source = Counter()
    inspected_pages = 0
    failures: list[dict[str, str]] = []
    comic_records: list[OfficialComicMetadata] = []
    profiles: list[OfficialCharacterProfile] = []

    try:
        for source in selected:
            queue: deque[str] = deque(normalize_url(url) for url in source.discovery_urls)
            seen_indexes: set[str] = set()
            while queue and len(seen_indexes) < 10 and len(candidates) < max_candidates:
                page_url = queue.popleft()
                if not page_url or page_url in seen_indexes:
                    continue
                seen_indexes.add(page_url)
                observation = crawler.inspect_public_url(page_url)
                inspected_pages += 1
                if observation.get("metadata_status") not in {
                    "success",
                    "insufficient_content",
                }:
                    failures.append(
                        {
                            "source_id": source.source_id,
                            "url": page_url,
                            "reason": str(observation.get("reason", "failed")),
                        }
                    )
                    continue
                links = [
                    {"url": str(item.get("url", "")), "label": str(item.get("label", ""))}
                    for item in observation.get("links", [])
                    if isinstance(item, dict)
                ]
                if source.source_id == "official-comics":
                    comic_records.extend(_comic_records(links))
                    continue
                if source.source_id == "official-characters":
                    profiles.extend(
                        _character_profiles(str(observation.get("content", "")), page_url)
                    )
                for link in links:
                    url = normalize_url(link["url"])
                    label = link["label"].strip()
                    if _candidate_link(source.source_id, url, label, scope):
                        if url not in candidates and len(candidates) < max_candidates:
                            candidates.append(url)
                            per_source[source.source_id] += 1
                        source_by_url[url] = source.source_id
                    elif _navigation_link(source.source_id, url, label):
                        if url not in seen_indexes and url not in queue:
                            queue.append(url)
    finally:
        if owns_crawler:
            crawler.close()

    manifest["discovered_urls"] = candidates
    manifest["discovery_sources"] = source_by_url
    manifest["updated_at"] = utc_now()
    write_json(paths.manifest, manifest)
    unique_comics = {row.source_url: row for row in comic_records}
    write_jsonl(
        paths.comic_metadata,
        [row.model_dump(mode="json") for row in unique_comics.values()],
    )
    unique_profiles = {
        (row.character_name, row.source_url): row for row in profiles
    }
    write_jsonl(
        paths.character_profiles,
        [row.model_dump(mode="json") for row in unique_profiles.values()],
    )
    report = {
        "scope": scope,
        "requested_sources": [source.source_id for source in selected],
        "existing_candidates": len(existing),
        "new_candidates": len(candidates) - len(existing),
        "total_candidates": len(candidates),
        "max_candidates": max_candidates,
        "inspected_index_pages": inspected_pages,
        "new_candidates_by_source": dict(sorted(per_source.items())),
        "comic_metadata_records": len(unique_comics),
        "character_profile_records": len(unique_profiles),
        "failures": failures,
        "generated_at": utc_now(),
    }
    write_json(paths.discovery_report, report)
    return report
