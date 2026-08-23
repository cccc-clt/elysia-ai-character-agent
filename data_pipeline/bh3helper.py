"""BH3Helper discovery and story-navigation orchestration.

The helper is a community-curated index, not an official or transcript source.
Only short navigation metadata is persisted.  Embedded dialogue containers are
discarded before parsing so this module cannot become a second story-text copy.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag

from data_pipeline.config import CORE_CHARACTERS, DEFAULT_USER_AGENT, PipelinePaths
from data_pipeline.renderer import PlaywrightRenderer, RenderUnavailableError
from data_pipeline.schemas import (
    BH3HelperAnnotation,
    BH3HelperArchiveCandidate,
    BH3HelperDuplicateMap,
    BH3HelperOfficialLink,
    SourceLinkGraphEdge,
    StoryNavigationChunk,
    StoryNavigationRecord,
)
from data_pipeline.utils import (
    compact_text,
    content_hash,
    normalize_url,
    read_json,
    read_jsonl,
    stable_id,
    utc_now,
    write_json,
    write_jsonl,
)


BH3HELPER_ROOT = "https://bh3helper.xrysnow.xyz/"
BH3HELPER_ROBOTS = "https://bh3helper.xrysnow.xyz/robots.txt"
SOURCE_TYPE = "community_story_guide"
SOURCE_TIER = "Tier B-curated-index"
ACCESS_BLOCK_STATUSES = {403, 412, 429}
CAPTCHA_MARKERS = ("验证码", "captcha", "人机验证", "访问过于频繁")

TARGET_TITLES = {
    "在无限的阴影之中",
    "致世界上的另一个我",
    "愿时光永驻此刻，愿明日——",
    "第二十九章 来自乐土",
    "第三十章 英雄们的葬礼",
    "第三十一章 因你而在的故事",
}
CHARACTER_NAMES = tuple(
    dict.fromkeys((*CORE_CHARACTERS, "雷电芽衣", "芽衣", "梅博士"))
)
TOPIC_NAMES = (
    "往世乐土",
    "永世乐土",
    "逐火十三英桀",
    "十三英桀",
    "逐火之蛾",
    "前文明",
    "融合战士",
    "英桀档案",
    "角色档案",
    "追忆",
    "侵蚀之律者",
    "约束的惨剧",
    "约束惨剧",
    "人之律者",
    "始源之律者",
    "第十三律者",
    "英桀",
)
SCOPE_KEYWORDS = tuple(dict.fromkeys((*TARGET_TITLES, *CHARACTER_NAMES, *TOPIC_NAMES)))
EXCLUDED_SCOPE_MARKERS = (
    "第二部",
    "间章",
    "活动攻略",
    "战斗攻略",
    "配队",
    "深渊",
    "乐土攻略",
)
OFFICIAL_DOMAIN_SUFFIXES = (
    "bh3.com",
    "mihoyo.com",
    "miyoushe.com",
    "bilibili.com",
)
ARCHIVE_MARKERS: dict[str, str] = {
    "角色档案": "character_archive",
    "英桀档案": "flame_chaser_archive",
    "追忆": "recollection",
    "收藏品": "collectible",
    "NPC": "npc_text",
    "美术档案": "art_archive",
    "活动档案": "event_archive",
}
ARCHIVE_CHARACTER_ALIASES: dict[str, str] = {
    "粉色妖精小姐": "爱莉希雅",
    "无限·噬界之蛇": "梅比乌斯",
    "空梦·掠集之兽": "帕朵菲莉丝",
    "戒律·深罪之槛": "阿波尼亚",
    "黄金·璀耀之歌": "伊甸",
    "繁星·绘世之卷": "格蕾修",
    "螺旋·愚戏之匣": "维尔薇",
}
ROLE_RELATIONS = {
    "MEMBER_OF",
    "ALLY_OF",
    "ENEMY_OF",
    "KNOWS",
    "CREATED_BY",
    "RELATED_TO",
    "FRIEND_OF",
}


class BH3HelperAccessError(RuntimeError):
    """Raised when the public site tells the collector to stop."""


def _captcha_present(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in CAPTCHA_MARKERS)


def _canonical_helper_url(url: str, base_url: str = BH3HELPER_ROOT) -> str:
    normalized = normalize_url(url, base_url)
    parts = urlsplit(normalized)
    if parts.scheme != "https" or parts.hostname != "bh3helper.xrysnow.xyz":
        return ""
    return normalized


def _get(
    client: httpx.Client,
    url: str,
    *,
    delay_seconds: float,
    sleeper: Callable[[float], None],
) -> httpx.Response:
    if delay_seconds:
        sleeper(delay_seconds)
    response = client.get(url)
    if response.status_code in ACCESS_BLOCK_STATUSES:
        raise BH3HelperAccessError(
            f"BH3Helper returned HTTP {response.status_code} for {url}; collection stopped"
        )
    response.raise_for_status()
    if _captcha_present(response.text):
        raise BH3HelperAccessError(
            f"BH3Helper presented a verification page for {url}; collection stopped"
        )
    return response


def inspect_bh3helper_access(
    client: httpx.Client,
    *,
    delay_seconds: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Check robots and the public homepage without treating 404 as a ban."""

    robots_status = "unavailable"
    robots_http_status: int | None = None
    robots_note = "robots.txt unavailable; conservative single-request pacing applies"
    try:
        if delay_seconds:
            sleeper(delay_seconds)
        response = client.get(BH3HELPER_ROBOTS)
        robots_http_status = response.status_code
        if response.status_code == 200:
            parser = RobotFileParser()
            parser.set_url(BH3HELPER_ROBOTS)
            parser.parse(response.text.splitlines())
            if not parser.can_fetch(DEFAULT_USER_AGENT, BH3HELPER_ROOT):
                raise BH3HelperAccessError(
                    "BH3Helper robots.txt explicitly disallows the public root"
                )
            robots_status = "allowed"
            robots_note = "robots.txt permits the configured user agent"
        elif response.status_code == 404:
            robots_status = "not_found"
            robots_note = "robots.txt returned 404; conservative pacing remains active"
        elif response.status_code in ACCESS_BLOCK_STATUSES:
            raise BH3HelperAccessError(
                f"BH3Helper robots.txt returned HTTP {response.status_code}; collection stopped"
            )
        else:
            robots_note = f"robots.txt returned HTTP {response.status_code}; conservative pacing remains active"
    except httpx.HTTPError as exc:
        robots_note = f"robots.txt unavailable ({type(exc).__name__}); conservative pacing remains active"

    root = _get(
        client,
        BH3HELPER_ROOT,
        delay_seconds=delay_seconds,
        sleeper=sleeper,
    )
    return {
        "checked_at": utc_now(),
        "robots_status": robots_status,
        "robots_http_status": robots_http_status,
        "robots_note": robots_note,
        "public_root_status": root.status_code,
        "source_tier": SOURCE_TIER,
        "official_host": False,
    }


def _render_if_needed(
    url: str,
    html: str,
    renderer: Callable[[str], str] | None,
    *,
    require_links: bool = False,
) -> tuple[str, bool]:
    soup = BeautifulSoup(html, "html.parser")
    visible = compact_text(soup.get_text("\n", strip=True))
    links = soup.find_all("a", href=True)
    insufficient = len(visible.replace("\n", "")) < 200 or (require_links and not links)
    if not insufficient or renderer is None:
        return html, False
    rendered = renderer(url)
    if _captcha_present(rendered):
        raise BH3HelperAccessError(
            f"BH3Helper presented a verification page while rendering {url}; collection stopped"
        )
    return rendered, True


def discover_public_scope_links(html: str) -> list[tuple[str, str]]:
    """Return only relevant links explicitly present in the supplied public page."""

    soup = BeautifulSoup(html, "html.parser")
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        url = _canonical_helper_url(str(anchor.get("href", "")), BH3HELPER_ROOT)
        if not title or not url or url == BH3HELPER_ROOT or url in seen:
            continue
        if any(marker in title for marker in EXCLUDED_SCOPE_MARKERS):
            continue
        target_title_match = any(
            target in title or title in target for target in TARGET_TITLES
        )
        target_chapter_match = bool(
            re.search(r"第(?:二十九|三十|三十一)章(?:\s|[:：]|$)", title)
            or re.search(r"(?:^|\D)(?:29|30|31)(?:章|\s|[:：]|$)", title)
        )
        topic_match = any(
            key in title
            for key in TOPIC_NAMES
            if key not in {"英桀"}
        )
        character_match = any(
            name in title
            for name in CHARACTER_NAMES
            if len(name) >= 2
        ) and any(marker in title for marker in ("档案", "追忆", "关于", "角色", "英桀"))
        if not (target_title_match or target_chapter_match or topic_match or character_match):
            continue
        seen.add(url)
        output.append((title, url))
    return output


def _section_title(node: Tag) -> str:
    section = node.find_parent(class_=re.compile(r"content-section"))
    if not isinstance(section, Tag):
        return ""
    heading = section.find(class_=re.compile(r"content-title"))
    return re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip() if heading else ""


def _metadata_text_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select(
        "script, style, noscript, nav, footer, .dialog-viewer-wrapper, .dialog-embedded, [class*='dialog-content'], [class*='dialog-text']"
    ):
        node.decompose()
    return soup


def _scalar(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        pattern = rf"(?:^|\n)\s*{re.escape(label)}\s*[:：]?\s*([^\n]{{1,80}})"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" ：:")
            if value and value not in labels:
                return value
    return ""


def _word_count(value: str) -> int | None:
    match = re.search(r"([\d,.]+)\s*([万萬千]?)", value)
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    multiplier = {"万": 10_000, "萬": 10_000, "千": 1_000}.get(
        match.group(2), 1
    )
    return int(number * multiplier)


def _text_fingerprint(text: str) -> tuple[str, list[str]]:
    normalized = re.sub(r"\s+", "", text)
    if not normalized:
        return "", []
    width = 5 if len(normalized) >= 5 else len(normalized)
    shingles = {
        normalized[index : index + width]
        for index in range(max(1, len(normalized) - width + 1))
    }
    signature = sorted(
        hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        for value in shingles
    )[:64]
    return content_hash(normalized), signature


def _matched_names(text: str) -> tuple[list[str], list[str]]:
    characters = [name for name in CHARACTER_NAMES if name in text]
    if "芽衣" in characters and "雷电芽衣" in characters:
        characters.remove("芽衣")
    topics = list(dict.fromkeys(name for name in TOPIC_NAMES if name in text))
    return characters, topics


def _content_type(title: str) -> tuple[str, str, str]:
    chapter_number = ""
    if "第二十九章" in title or re.search(r"(?:第|chapter\s*)29", title, re.I):
        chapter_number = "29"
    elif "第三十章" in title or re.search(r"(?:第|chapter\s*)30", title, re.I):
        chapter_number = "30"
    elif "第三十一章" in title or re.search(r"(?:第|chapter\s*)31", title, re.I):
        chapter_number = "31"
    if chapter_number:
        return "mainline_chapter", "致以无瑕之人", chapter_number
    if title in TARGET_TITLES or "往世乐土" in title or "乐土" in title:
        return "elysian_realm_arc", "往世乐土", ""
    if any(marker in title for marker in ARCHIVE_MARKERS):
        return "archive_index", "往世乐土", ""
    return "story_guide", "", ""


def _material_type(title: str, url: str) -> str:
    text = title.lower()
    if "漫画" in title or "comic" in text:
        return "official_comic"
    if "动画" in title:
        return "official_animation"
    if "音乐会" in title:
        return "official_concert"
    if "音乐" in title or "ost" in text:
        return "official_music"
    if "pv" in text or "预告" in title:
        return "official_pv"
    if "视频" in title or "bilibili.com" in url:
        return "official_video"
    if "资讯" in title or "news" in url:
        return "official_news"
    if "bh3.com" in url:
        return "official_website"
    return "unknown"


def _archive_type(title: str) -> str:
    for marker, value in ARCHIVE_MARKERS.items():
        if marker.lower() in title.lower():
            return value
    return "unknown_archive"


def _archive_alias_characters(text: str) -> list[str]:
    return [
        character
        for alias, character in ARCHIVE_CHARACTER_ALIASES.items()
        if alias in text
    ]


def parse_bh3helper_page(
    html: str,
    *,
    source_url: str,
    recommended_order: int | None = None,
) -> tuple[
    StoryNavigationRecord,
    list[BH3HelperOfficialLink],
    list[BH3HelperArchiveCandidate],
    list[BH3HelperAnnotation],
    dict[str, Any],
]:
    """Parse one rendered page after removing every dialogue-text container."""

    original = BeautifulSoup(html, "html.parser")
    dialogue_nodes = original.select(
        ".dialog-viewer-wrapper, .dialog-embedded, [class*='dialog-content'], [class*='dialog-text']"
    )
    dialogue_fragments: list[str] = []
    for node in dialogue_nodes:
        fragment = compact_text(node.get_text("\n", strip=True))
        if fragment and fragment not in dialogue_fragments:
            dialogue_fragments.append(fragment)
    dialogue_hash, dialogue_minhash = _text_fingerprint("\n".join(dialogue_fragments))
    embedded_dialogue_present = bool(dialogue_fragments)
    soup = _metadata_text_soup(html)
    page_title = ""
    if soup.title:
        page_title = re.sub(r"\s*[|｜].*$", "", soup.title.get_text(" ", strip=True)).strip()
    if not page_title:
        heading = soup.find(["h1", "h2"])
        if heading:
            page_title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
    if not page_title:
        raise ValueError(f"BH3Helper page has no public title: {source_url}")

    text = compact_text(soup.get_text("\n", strip=True))
    content_type, story_arc, chapter_number = _content_type(page_title)
    short_heading_text = "\n".join(
        node.get_text(" ", strip=True)
        for node in soup.find_all(["h1", "h2", "h3", "h4"])
    )
    characters, topics = _matched_names(f"{page_title}\n{short_heading_text}")
    word_count_text = _scalar(text, ("文本字数", "字数"))

    prerequisites: list[str] = []
    followups: list[str] = []
    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if not label:
            continue
        section = _section_title(anchor)
        if any(marker in section for marker in ("观前", "前置")):
            prerequisites.append(label)
        if any(marker in section for marker in ("观后", "后续")):
            followups.append(label)

    navigation = StoryNavigationRecord(
        navigation_id=stable_id("bh3helper_nav", source_url),
        title=page_title,
        content_type=content_type,  # type: ignore[arg-type]
        story_arc=story_arc,
        chapter_number=chapter_number,
        update_version=_scalar(text, ("更新版本", "版本")),
        update_date=_scalar(text, ("更新日期", "日期")),
        estimated_duration=_scalar(text, ("参考时长", "时长")),
        text_word_count=_word_count(word_count_text),
        recommended_order=recommended_order,
        prerequisites=list(dict.fromkeys(prerequisites)),
        followups=list(dict.fromkeys(followups)),
        character_names=characters,
        topic_names=topics,
        source_url=source_url,
    )

    links: list[BH3HelperOfficialLink] = []
    seen_links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = normalize_url(str(anchor.get("href", "")), source_url)
        domain = (urlsplit(url).hostname or "").lower()
        if not url or not any(
            domain == suffix or domain.endswith("." + suffix)
            for suffix in OFFICIAL_DOMAIN_SUFFIXES
        ):
            continue
        if url in seen_links:
            continue
        seen_links.add(url)
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        section = _section_title(anchor)
        title = label or section or f"待核验外链（{domain}）"
        links.append(
            BH3HelperOfficialLink(
                link_id=stable_id("bh3helper_link", f"{source_url}|{url}"),
                title=title[:160],
                url=url,
                target_domain=domain,
                material_type=_material_type(f"{section} {title}", url),  # type: ignore[arg-type]
                discovered_from=source_url,
            )
        )

    archives: list[BH3HelperArchiveCandidate] = []
    archive_titles: set[str] = set()
    for node in soup.find_all(["h2", "h3", "h4"]):
        title = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if not title or not any(marker.lower() in title.lower() for marker in ARCHIVE_MARKERS):
            continue
        if title in archive_titles:
            continue
        archive_titles.add(title)
        archive_scope = node.find_parent(class_=re.compile(r"content-section"))
        archive_scope_text = title
        if isinstance(archive_scope, Tag):
            archive_scope_text = "\n".join(
                heading.get_text(" ", strip=True)
                for heading in archive_scope.find_all(["h2", "h3", "h4"])
            )
        archive_characters, archive_topics = _matched_names(archive_scope_text)
        archive_characters.extend(
            character
            for character in _archive_alias_characters(archive_scope_text)
            if character not in archive_characters
        )
        archives.append(
            BH3HelperArchiveCandidate(
                candidate_id=stable_id("bh3helper_archive", f"{source_url}|{title}"),
                title=title[:160],
                archive_type=_archive_type(title),  # type: ignore[arg-type]
                source_url=source_url,
                discovered_from=source_url,
                character_names=archive_characters,
                topic_names=archive_topics,
            )
        )

    annotations: list[BH3HelperAnnotation] = []
    seen_annotations: set[str] = set()
    for node in soup.select(".content-hint, [class*='hint'], [class*='notice']"):
        summary = compact_text(node.get_text(" ", strip=True))[:500]
        if not summary or summary in seen_annotations:
            continue
        if not any(
            marker in summary
            for marker in (
                "提示",
                "建议",
                "推荐",
                "注意",
                "本站",
                "作者",
                "自行",
                "操作",
                "观看",
                "剧透",
                "整理",
                "说明",
            )
        ):
            continue
        seen_annotations.add(summary)
        section = _section_title(node)
        annotation_type = "content_notice"
        if "操作" in summary:
            annotation_type = "operation_instruction"
        elif any(key in summary for key in ("建议", "观前", "观看")):
            annotation_type = "viewing_advice"
        elif any(key in summary for key in ("整理", "本站", "作者")):
            annotation_type = "curation_note"
        annotations.append(
            BH3HelperAnnotation(
                annotation_id=stable_id("bh3helper_note", f"{source_url}|{summary}"),
                title=(section or "社区内容提示")[:160],
                annotation_type=annotation_type,  # type: ignore[arg-type]
                section=section[:160],
                summary=summary,
                source_url=source_url,
            )
        )

    page_audit = {
        "source_url": source_url,
        "title": page_title,
        "status": "success",
        "embedded_dialogue_present": embedded_dialogue_present,
        "embedded_dialogue_content_hash": dialogue_hash,
        "embedded_dialogue_minhash": dialogue_minhash,
        "embedded_dialogue_text_saved": False,
        "navigation_metadata_only": True,
        "official_host": False,
        "parsed_at": utc_now(),
        "parser_version": 5,
    }
    return navigation, links, archives, annotations, page_audit


def _default_renderer(timeout_seconds: float) -> Callable[[str], str]:
    instance = PlaywrightRenderer(DEFAULT_USER_AGENT, timeout_seconds)
    return instance.render


def discover_bh3helper(
    paths: PipelinePaths | None = None,
    *,
    scope: str = "elysia",
    max_pages: int = 30,
    delay_seconds: float = 3.0,
    concurrency: int = 1,
    timeout_seconds: float = 20.0,
    client: httpx.Client | None = None,
    renderer: Callable[[str], str] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Discover only public, explicitly linked in-scope pages and parse metadata."""

    if scope != "elysia":
        raise ValueError("BH3Helper discovery supports scope=elysia only")
    if not 1 <= max_pages <= 30:
        raise ValueError("max_pages must be between 1 and 30")
    if concurrency != 1:
        raise ValueError("BH3Helper discovery requires concurrency=1")
    if client is None and delay_seconds < 3:
        raise ValueError("Live BH3Helper discovery requires delay >= 3 seconds")
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    owns_client = client is None
    http = client or httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    render = renderer or _default_renderer(timeout_seconds)
    try:
        access = inspect_bh3helper_access(
            http, delay_seconds=delay_seconds, sleeper=sleeper
        )
        root_response = _get(
            http, BH3HELPER_ROOT, delay_seconds=delay_seconds, sleeper=sleeper
        )
        root_html, root_rendered = _render_if_needed(
            BH3HELPER_ROOT, root_response.text, render, require_links=True
        )
        discovered = discover_public_scope_links(root_html)
        selected = discovered[:max_pages]

        selected_urls = {url for _, url in selected}
        navigation_by_url = {
            str(row.get("source_url", "")): row
            for row in read_jsonl(paths.bh3helper_navigation)
            if str(row.get("source_url", "")) in selected_urls
        }
        links_by_id = {
            str(row.get("link_id", "")): row
            for row in read_jsonl(paths.bh3helper_official_links)
            if str(row.get("discovered_from", "")) in selected_urls
        }
        archives_by_id = {
            str(row.get("candidate_id", "")): row
            for row in read_jsonl(paths.bh3helper_archive_candidates)
            if str(row.get("discovered_from", "")) in selected_urls
        }
        annotations_by_id = {
            str(row.get("annotation_id", "")): row
            for row in read_jsonl(paths.bh3helper_annotations)
            if str(row.get("source_url", "")) in selected_urls
        }
        previous_manifest = read_json(paths.bh3helper_manifest, {})
        page_by_url = {
            str(row.get("source_url", "")): row
            for row in previous_manifest.get("pages", [])
            if isinstance(row, dict)
            and str(row.get("source_url", "")) in selected_urls
        }
        restrictions: list[str] = []
        parsed_this_run = 0
        for order, (link_title, url) in enumerate(selected, 1):
            if (
                url in navigation_by_url
                and page_by_url.get(url, {}).get("parser_version") == 5
            ):
                continue
            try:
                response = _get(
                    http, url, delay_seconds=delay_seconds, sleeper=sleeper
                )
                html, rendered = _render_if_needed(url, response.text, render)
                navigation, links, archives, annotations, page_audit = (
                    parse_bh3helper_page(
                        html,
                        source_url=url,
                        recommended_order=order,
                    )
                )
                page_audit.update(
                    {
                        "discovered_title": link_title,
                        "discovered_from": BH3HELPER_ROOT,
                        "rendered": rendered,
                    }
                )
                navigation_by_url[url] = navigation.model_dump(mode="json")
                links_by_id = {
                    key: value
                    for key, value in links_by_id.items()
                    if str(value.get("discovered_from", "")) != url
                }
                archives_by_id = {
                    key: value
                    for key, value in archives_by_id.items()
                    if str(value.get("discovered_from", "")) != url
                }
                annotations_by_id = {
                    key: value
                    for key, value in annotations_by_id.items()
                    if str(value.get("source_url", "")) != url
                }
                for row in links:
                    links_by_id[row.link_id] = row.model_dump(mode="json")
                for row in archives:
                    archives_by_id[row.candidate_id] = row.model_dump(mode="json")
                for row in annotations:
                    annotations_by_id[row.annotation_id] = row.model_dump(mode="json")
                page_by_url[url] = page_audit
                parsed_this_run += 1
            except (httpx.HTTPError, RenderUnavailableError, ValueError) as exc:
                page_by_url[url] = {
                    "source_url": url,
                    "title": link_title,
                    "status": "failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "parsed_at": utc_now(),
                }

        write_jsonl(paths.bh3helper_navigation, navigation_by_url.values())
        write_jsonl(paths.bh3helper_official_links, links_by_id.values())
        write_jsonl(paths.bh3helper_archive_candidates, archives_by_id.values())
        write_jsonl(paths.bh3helper_annotations, annotations_by_id.values())
        payload = {
            "generated_at": utc_now(),
            "scope": scope,
            "source_type": SOURCE_TYPE,
            "source_tier": SOURCE_TIER,
            "official_host": False,
            "access": access,
            "root_rendered": root_rendered,
            "discovery_method": "public_anchor_links_only",
            "numeric_id_scanning": False,
            "pages": list(page_by_url.values()),
            "discovered_pages": [
                {"title": title, "url": url, "discovered_from": BH3HELPER_ROOT}
                for title, url in discovered
            ],
            "relevant_pages_discovered": len(discovered),
            "pages_selected": len(selected),
            "pages_parsed_this_run": parsed_this_run,
            "pages_parsed_total": len(navigation_by_url),
            "navigation_records": len(navigation_by_url),
            "official_link_candidates": len(links_by_id),
            "archive_candidates": len(archives_by_id),
            "curator_annotations": len(annotations_by_id),
            "dialogue_text_saved": False,
            "encountered_restrictions": restrictions,
        }
        write_json(paths.bh3helper_manifest, payload)
        return payload
    except BH3HelperAccessError as exc:
        payload = {
            "generated_at": utc_now(),
            "scope": scope,
            "source_type": SOURCE_TYPE,
            "source_tier": SOURCE_TIER,
            "official_host": False,
            "stopped": True,
            "reason": str(exc),
            "encountered_restrictions": [str(exc)],
            "dialogue_text_saved": False,
        }
        write_json(paths.bh3helper_manifest, payload)
        raise
    finally:
        if owns_client:
            http.close()


def _normalized_story_title(value: str) -> str:
    value = re.sub(r"[\s·•—–_\-:：，。！？!?（）()《》\[\]]+", "", value.lower())
    return value.replace("第二十九章", "29").replace("第三十章", "30").replace("第三十一章", "31")


def _bh3text_group_candidates(paths: PipelinePaths) -> list[dict[str, str]]:
    groups: dict[str, dict[str, Any]] = {}
    rows = [
        *read_jsonl(paths.bh3text_documents),
        *read_jsonl(paths.bh3text_candidate_audit_jsonl),
    ]
    for row in rows:
        chapter = str(row.get("chapter", "")).strip()
        title = chapter or str(row.get("title", "")).strip()
        url = str(row.get("source_url") or row.get("url") or "")
        if not title or not url:
            continue
        key = _normalized_story_title(title)
        group = groups.setdefault(
            key,
            {"title": title, "url": url, "dialogue_fragments": []},
        )
        for turn in row.get("dialogue_turns", []):
            if isinstance(turn, dict) and turn.get("text"):
                group["dialogue_fragments"].append(str(turn["text"]))
    output: list[dict[str, str]] = []
    for group in groups.values():
        group_hash, group_minhash = _text_fingerprint(
            "\n".join(group.pop("dialogue_fragments"))
        )
        output.append(
            {
                "title": str(group["title"]),
                "url": str(group["url"]),
                "content_hash": group_hash,
                "minhash": "|".join(group_minhash),
            }
        )
    return output


def _build_link_graph(
    paths: PipelinePaths,
    duplicates: list[BH3HelperDuplicateMap],
) -> list[SourceLinkGraphEdge]:
    navigation = [StoryNavigationRecord.model_validate(row) for row in read_jsonl(paths.bh3helper_navigation)]
    official_links = [BH3HelperOfficialLink.model_validate(row) for row in read_jsonl(paths.bh3helper_official_links)]
    archives = [BH3HelperArchiveCandidate.model_validate(row) for row in read_jsonl(paths.bh3helper_archive_candidates)]
    edges: dict[str, SourceLinkGraphEdge] = {}

    def add(source: str, relation: str, target: str, source_url: str, target_url: str, confidence: float) -> None:
        if relation in ROLE_RELATIONS:
            raise ValueError("Role relation cannot enter the source link graph")
        edge = SourceLinkGraphEdge(
            edge_id=stable_id("source_edge", f"{source}|{relation}|{target}"),
            source_node=source,
            relation=relation,  # type: ignore[arg-type]
            target_node=target,
            source_url=source_url,
            target_url=target_url,
            confidence=confidence,
        )
        edges[edge.edge_id] = edge

    for row in navigation:
        add("bh3helper_root", "GUIDES_TO", row.navigation_id, BH3HELPER_ROOT, row.source_url, 1.0)
    for row in official_links:
        nav = next((item for item in navigation if item.source_url == row.discovered_from), None)
        if nav:
            add(nav.navigation_id, "LINKS_TO", row.link_id, nav.source_url, row.url, 0.8)
    for row in archives:
        nav = next((item for item in navigation if item.source_url == row.discovered_from), None)
        if nav:
            add(nav.navigation_id, "ARCHIVE_AVAILABLE_AT", row.candidate_id, nav.source_url, row.source_url, 0.8)
    for row in duplicates:
        add(row.helper_navigation_id, "TRANSCRIPT_AVAILABLE_AT", row.bh3text_node, row.helper_url, row.bh3text_url, row.similarity)
        add(row.helper_navigation_id, "POSSIBLE_DUPLICATE_OF", row.bh3text_node, row.helper_url, row.bh3text_url, row.similarity)
    ordered = sorted((row for row in navigation if row.recommended_order), key=lambda row: row.recommended_order or 0)
    for previous, current in zip(ordered, ordered[1:]):
        add(previous.navigation_id, "PRECEDES", current.navigation_id, previous.source_url, current.source_url, 0.8)
        add(current.navigation_id, "FOLLOWS", previous.navigation_id, current.source_url, previous.source_url, 0.8)
    return list(edges.values())


def map_duplicate_sources(paths: PipelinePaths | None = None) -> dict[str, int]:
    """Map duplicate chapter sources without reading or copying helper dialogue."""

    paths = paths or PipelinePaths()
    navigation = [StoryNavigationRecord.model_validate(row) for row in read_jsonl(paths.bh3helper_navigation)]
    bh3text_groups = _bh3text_group_candidates(paths)
    page_audits = {
        str(row.get("source_url", "")): row
        for row in read_json(paths.bh3helper_manifest, {}).get("pages", [])
        if isinstance(row, dict)
    }
    mappings: dict[str, BH3HelperDuplicateMap] = {}
    for helper in navigation:
        helper_key = _normalized_story_title(helper.title)
        for candidate in bh3text_groups:
            candidate_key = _normalized_story_title(candidate["title"])
            chapter_match = bool(
                helper.chapter_number
                and helper.chapter_number in candidate_key
            )
            title_match = helper_key == candidate_key or helper_key in candidate_key or candidate_key in helper_key
            if not (chapter_match or title_match):
                continue
            basis: list[str] = []
            if title_match:
                basis.append("normalized_title")
            if chapter_match:
                basis.append("chapter_number")
            helper_audit = page_audits.get(helper.source_url, {})
            helper_hash = str(helper_audit.get("embedded_dialogue_content_hash", ""))
            if helper_hash and helper_hash == candidate.get("content_hash"):
                basis.append("content_hash")
                text_similarity = 1.0
            else:
                helper_signature = set(
                    str(value)
                    for value in helper_audit.get("embedded_dialogue_minhash", [])
                )
                candidate_signature = set(
                    value for value in candidate.get("minhash", "").split("|") if value
                )
                denominator = min(len(helper_signature), len(candidate_signature))
                text_similarity = (
                    len(helper_signature & candidate_signature) / denominator
                    if denominator
                    else 0.0
                )
                if text_similarity >= 0.5:
                    basis.append("text_similarity")
            mapping = BH3HelperDuplicateMap(
                mapping_id=stable_id("bh3helper_dup", f"{helper.source_url}|{candidate['url']}"),
                helper_navigation_id=helper.navigation_id,
                helper_title=helper.title,
                helper_url=helper.source_url,
                bh3text_node=stable_id("bh3text_chapter", candidate["title"]),
                bh3text_title=candidate["title"],
                bh3text_url=candidate["url"],
                match_basis=basis,  # type: ignore[arg-type]
                similarity=max(
                    0.95 if chapter_match and title_match else 0.9,
                    text_similarity,
                ),
            )
            mappings[mapping.mapping_id] = mapping
            break
    rows = list(mappings.values())
    write_jsonl(paths.bh3helper_duplicate_map, [row.model_dump(mode="json") for row in rows])
    graph = _build_link_graph(paths, rows)
    write_jsonl(paths.source_link_graph, [row.model_dump(mode="json") for row in graph])
    return {"duplicate_mappings": len(rows), "source_link_edges": len(graph)}


def build_story_navigation(paths: PipelinePaths | None = None) -> dict[str, int]:
    """Build a metadata-only navigation index isolated from both lore corpora."""

    paths = paths or PipelinePaths()
    navigation = [StoryNavigationRecord.model_validate(row) for row in read_jsonl(paths.bh3helper_navigation)]
    official_links = [BH3HelperOfficialLink.model_validate(row) for row in read_jsonl(paths.bh3helper_official_links)]
    archive_rows = read_jsonl(paths.bh3helper_archive_candidates)
    for row in archive_rows:
        names = [str(value) for value in row.get("character_names", [])]
        for character in _archive_alias_characters(str(row.get("title", ""))):
            if character not in names:
                names.append(character)
        row["character_names"] = names
    write_jsonl(paths.bh3helper_archive_candidates, archive_rows)
    archives = [BH3HelperArchiveCandidate.model_validate(row) for row in archive_rows]
    duplicates = [BH3HelperDuplicateMap.model_validate(row) for row in read_jsonl(paths.bh3helper_duplicate_map)]
    chunks: list[StoryNavigationChunk] = []
    for row in navigation:
        row_links = [item for item in official_links if item.discovered_from == row.source_url]
        row_archives = [item for item in archives if item.discovered_from == row.source_url]
        row_duplicates = [item for item in duplicates if item.helper_navigation_id == row.navigation_id]
        fields = [
            f"章节：{row.title}",
            f"推荐顺序：{row.recommended_order or '待审核'}",
            f"所属篇章：{row.story_arc or '待审核'}",
            f"版本：{row.update_version or '待审核'}",
            f"参考时长：{row.estimated_duration or '待审核'}",
            f"相关角色：{'、'.join(row.character_names) or '待审核'}",
            f"相关档案：{'、'.join(item.title for item in row_archives) or '无已发现候选'}",
            f"官方物料候选：{'、'.join(f'{item.title} ({item.url})' for item in row_links) or '无'}",
            f"BH3Text文本入口：{'、'.join(item.bh3text_url for item in row_duplicates) or '无已映射入口'}",
            "用途限制：仅用于剧情导航，不得据此回答角色事实或人物关系。",
        ]
        chunks.append(
            StoryNavigationChunk(
                chunk_id=stable_id("story_nav_chunk", row.navigation_id),
                navigation_id=row.navigation_id,
                title=row.title,
                content="\n".join(fields),
                source_url=row.source_url,
            )
        )
    write_jsonl(paths.story_navigation_chunks, [row.model_dump(mode="json") for row in chunks])
    return {
        "navigation_records": len(navigation),
        "navigation_chunks": len(chunks),
        "main_lore_chunks_written": 0,
        "bh3text_chunks_written": 0,
    }


def bh3helper_status(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    manifest = read_json(paths.bh3helper_manifest, {})
    return {
        "related_pages_discovered": int(manifest.get("relevant_pages_discovered", 0)),
        "pages_parsed": len(read_jsonl(paths.bh3helper_navigation)),
        "navigation_records": len(read_jsonl(paths.bh3helper_navigation)),
        "official_link_candidates": len(read_jsonl(paths.bh3helper_official_links)),
        "archive_candidates": len(read_jsonl(paths.bh3helper_archive_candidates)),
        "curator_annotations": len(read_jsonl(paths.bh3helper_annotations)),
        "duplicate_mappings": len(read_jsonl(paths.bh3helper_duplicate_map)),
        "navigation_chunks": len(read_jsonl(paths.story_navigation_chunks)),
        "source_link_edges": len(read_jsonl(paths.source_link_graph)),
    }
