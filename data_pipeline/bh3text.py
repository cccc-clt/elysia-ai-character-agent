"""Conservative BH3Text discovery and supplemental transcript processing.

BH3Text is a community-hosted archive that claims to preserve game dialogue.  It
is deliberately isolated from Tier A data and from the main lore chunk file.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

from data_pipeline.config import CORE_CHARACTERS, DEFAULT_USER_AGENT, PipelinePaths
from data_pipeline.schemas import (
    BH3TextCandidateAudit,
    BH3TextChunk,
    BH3TextDocument,
    BH3TextPendingRelation,
    BH3TextVerificationRecord,
    DialogueEvidenceEdge,
    DialogueTurn,
)
from data_pipeline.utils import (
    content_hash,
    normalize_url,
    read_json,
    read_jsonl,
    stable_id,
    utc_now,
    write_json,
    write_jsonl,
)


BH3TEXT_ROOT = "https://www.bh3text.com/dialog/"
BH3TEXT_ABOUT = "https://www.bh3text.com/about/"
BH3TEXT_ROBOTS = "https://www.bh3text.com/robots.txt"
SOURCE_TYPE = "community_game_text_archive"
SOURCE_TIER = "Tier B-primary-transcript"

TARGET_DIRECTORIES: dict[str, tuple[str, str]] = {
    "在无限的阴影之中": ("往世乐土", "在无限的阴影之中"),
    "致世界上的另一个我": ("往世乐土", "致世界上的另一个我"),
    "愿时光永驻此刻，愿明日——": (
        "往世乐土",
        "愿时光永驻此刻，愿明日——",
    ),
    "第二十九章 来自乐土": ("主线第一部", "第二十九章 来自乐土"),
    "第三十章 英雄们的葬礼": ("主线第一部", "第三十章 英雄们的葬礼"),
    "第三十一章 因你而在的故事": (
        "主线第一部",
        "第三十一章 因你而在的故事",
    ),
}

CHARACTER_NAMES = tuple(dict.fromkeys((*CORE_CHARACTERS, "芽衣", "雷电芽衣")))
TOPIC_NAMES = (
    "十三英桀",
    "逐火十三英桀",
    "逐火之蛾",
    "往世乐土",
    "永世乐土",
    "前文明",
    "融合战士",
    "记忆体",
    "人之律者",
    "第十三律者",
    "始源之律者",
    "侵蚀之律者",
    "约束的惨剧",
    "约束惨剧",
    "黄金庭院",
    "黄金庭园",
    "英桀",
)

ACCESS_BLOCK_STATUSES = {403, 412, 429}
CAPTCHA_MARKERS = ("验证码", "captcha", "人机验证", "访问过于频繁")
NAVIGATION_TEXT = {
    "返回",
    "< 返回",
    "← 对话文本",
    "上一页",
    "下一页",
    "首页",
    "关于",
    "关于本站",
    "|",
}

COVERAGE_GAP_KEYWORDS = (
    "爱莉希雅",
    "第十三律者",
    "人之律者",
    "英桀",
    "十三英桀",
    "往世乐土",
    "永世乐土",
    "记忆体",
    "记忆",
    "宴会",
    "舞会",
    "黄金庭院",
    "始源",
    "侵蚀之律者",
    "凯文",
    "伊甸",
    "维尔薇",
    "阿波尼亚",
    "梅比乌斯",
    "格蕾修",
    "科斯魔",
    "帕朵菲莉丝",
    "千劫",
    "苏",
    "樱",
    "华",
    "芽衣",
)

PURE_GAMEPLAY_TITLE_MARKERS = (
    "卡牌",
    "宝箱",
    "寻宝游戏",
    "探索",
    "战斗操作",
    "操作教学",
    "系统提示",
    "使用法则",
    "谜题x珍宝",
    "点亮未解谜题",
)

GROUP_PRIORITY = (
    "mainline_31",
    "elysian_realm_3",
    "mainline_29",
    "mainline_30",
    "elysian_realm_1",
    "elysian_realm_2",
)

VERIFICATION_QUOTAS = {
    "elysian_realm_1": 2,
    "elysian_realm_2": 1,
    "elysian_realm_3": 1,
    "mainline_29": 2,
    "mainline_30": 2,
    "mainline_31": 2,
}


class BH3TextAccessError(RuntimeError):
    """Raised when access policy or a public-page restriction stops collection."""


def load_bh3text_collection_groups(path: Path) -> dict[str, dict[str, Any]]:
    """Load and validate chapter-level collection targets."""

    if not path.exists():
        raise FileNotFoundError(f"BH3Text collection group config not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_groups = payload.get("bh3text_collection_groups") if isinstance(payload, dict) else None
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise ValueError("bh3text_collection_groups must be a non-empty mapping")
    groups: dict[str, dict[str, Any]] = {}
    chapters: set[str] = set()
    for group_id, value in raw_groups.items():
        if not isinstance(group_id, str) or not isinstance(value, dict):
            raise ValueError("Invalid BH3Text collection group")
        chapter = str(value.get("chapter", "")).strip()
        target_total = value.get("target_total")
        if not chapter or not isinstance(target_total, int) or not 1 <= target_total <= 100:
            raise ValueError(f"Invalid BH3Text group target: {group_id}")
        if chapter in chapters:
            raise ValueError(f"Duplicate BH3Text group chapter: {chapter}")
        chapters.add(chapter)
        groups[group_id] = {"chapter": chapter, "target_total": target_total}
    return groups


def _group_id_for_chapter(
    chapter: str,
    groups: dict[str, dict[str, Any]],
) -> str:
    return next(
        (
            group_id
            for group_id, value in groups.items()
            if value["chapter"] == chapter
        ),
        "",
    )


def _is_pure_gameplay_title(title: str) -> bool:
    return any(marker.lower() in title.lower() for marker in PURE_GAMEPLAY_TITLE_MARKERS)


def _coverage_gap_relevance(row: BH3TextCandidateAudit) -> int:
    keyword_hits = sum(keyword in row.title for keyword in COVERAGE_GAP_KEYWORDS)
    score = row.priority_score + keyword_hits * 100
    if row.chapter == "第三十一章 因你而在的故事":
        score += 1_000
    if "关于" in row.title:
        score += 40
    if _is_pure_gameplay_title(row.title):
        score -= 10_000
    return score


def _group_counts(
    documents: Iterable[BH3TextDocument],
    groups: dict[str, dict[str, Any]],
) -> dict[str, int]:
    counts = {group_id: 0 for group_id in groups}
    for document in documents:
        group_id = _group_id_for_chapter(document.chapter, groups)
        if group_id:
            counts[group_id] += 1
    return counts


def _group_coverage_snapshot(
    groups: dict[str, dict[str, Any]],
    counts: dict[str, int],
    *,
    manifest_counts: dict[str, Any] | None = None,
    selected: list[BH3TextCandidateAudit] | None = None,
) -> dict[str, Any]:
    selected_counts: dict[str, int] = {}
    for row in selected or []:
        group_id = _group_id_for_chapter(row.chapter, groups)
        if group_id:
            selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
    rows: list[dict[str, Any]] = []
    for group_id, value in groups.items():
        current = counts.get(group_id, 0)
        target = int(value["target_total"])
        chapter = str(value["chapter"])
        manifest_value = (manifest_counts or {}).get(chapter)
        rows.append(
            {
                "group_id": group_id,
                "chapter": chapter,
                "target_total": target,
                "successful_documents": current,
                # Discovery-only manifests created by older pipeline versions did not
                # retain chapter_counts. Successful documents remain the source of
                # truth in that compatibility case.
                "manifest_documents": (
                    current if manifest_value is None else int(manifest_value)
                ),
                "remaining_gap": max(0, target - current),
                "selected_new_pages": selected_counts.get(group_id, 0),
                "quota_status": "satisfied" if current >= target else "gap",
            }
        )
    return {
        "generated_at": utc_now(),
        "total_documents": sum(counts.values()),
        "groups": rows,
    }


def select_coverage_gap_candidates(
    rows: list[BH3TextCandidateAudit],
    existing_documents: Iterable[BH3TextDocument],
    groups: dict[str, dict[str, Any]],
    *,
    max_new_pages: int,
) -> list[BH3TextCandidateAudit]:
    """Fill per-group gaps without revisiting successful URLs or exceeding quotas."""

    if not 1 <= max_new_pages <= 40:
        raise ValueError("max_new_pages must be between 1 and 40")
    existing_list = list(existing_documents)
    existing_urls = {row.source_url for row in existing_list}
    counts = _group_counts(existing_list, groups)
    selected: list[BH3TextCandidateAudit] = []
    priority = [*GROUP_PRIORITY, *sorted(set(groups) - set(GROUP_PRIORITY))]
    for group_id in priority:
        if len(selected) >= max_new_pages or group_id not in groups:
            break
        target = int(groups[group_id]["target_total"])
        gap = max(0, target - counts.get(group_id, 0))
        if gap == 0:
            continue
        candidates = sorted(
            (
                row
                for row in rows
                if row.decision == "include"
                and row.url not in existing_urls
                and _group_id_for_chapter(row.chapter, groups) == group_id
                and not _is_pure_gameplay_title(row.title)
            ),
            key=lambda row: (-_coverage_gap_relevance(row), row.title, row.url),
        )
        take = min(gap, max_new_pages - len(selected))
        selected.extend(candidates[:take])
    return selected


def _select_balanced_candidate_audit(
    rows: list[BH3TextCandidateAudit],
    groups: dict[str, dict[str, Any]],
    max_candidates: int,
) -> list[BH3TextCandidateAudit]:
    """Reserve chapter-local candidate capacity before filling by global score."""

    selected: list[BH3TextCandidateAudit] = []
    for group_id in GROUP_PRIORITY:
        if group_id not in groups:
            continue
        target = int(groups[group_id]["target_total"]) + 10
        group_rows = sorted(
            (
                row
                for row in rows
                if _group_id_for_chapter(row.chapter, groups) == group_id
            ),
            key=lambda row: (-_coverage_gap_relevance(row), row.title, row.url),
        )
        for row in group_rows[:target]:
            if row not in selected and len(selected) < max_candidates:
                selected.append(row)
    for row in sorted(
        rows,
        key=lambda item: (-item.priority_score, item.chapter, item.title, item.url),
    ):
        if len(selected) >= max_candidates:
            break
        if row not in selected:
            selected.append(row)
    return selected


def _canonical_bh3text_url(url: str, base_url: str = BH3TEXT_ROOT) -> str:
    normalized = normalize_url(url, base_url)
    parts = urlsplit(normalized)
    if parts.scheme != "https" or parts.hostname != "www.bh3text.com":
        return ""
    if not (parts.path == "/dialog" or parts.path.startswith("/dialog/")):
        return ""
    return normalized


def _visible_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip("。")


def _captcha_present(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in CAPTCHA_MARKERS)


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
        raise BH3TextAccessError(
            f"BH3Text returned HTTP {response.status_code} for {url}; collection stopped"
        )
    response.raise_for_status()
    if _captcha_present(response.text):
        raise BH3TextAccessError(
            f"BH3Text presented a verification page for {url}; collection stopped"
        )
    return response


def inspect_bh3text_access(
    client: httpx.Client,
    *,
    delay_seconds: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Inspect robots, public root access, and the site usage statement."""

    robots_status = "unavailable"
    robots_http_status: int | None = None
    robots_note = "robots.txt could not be fetched; conservative limits remain active"
    robots_allowed = True
    try:
        if delay_seconds:
            sleeper(delay_seconds)
        robots = client.get(BH3TEXT_ROBOTS)
        robots_http_status = robots.status_code
        if robots.status_code == 200:
            parser = RobotFileParser()
            parser.set_url(BH3TEXT_ROBOTS)
            parser.parse(robots.text.splitlines())
            robots_allowed = parser.can_fetch(DEFAULT_USER_AGENT, BH3TEXT_ROOT)
            robots_status = "allowed" if robots_allowed else "disallowed"
            robots_note = (
                "robots.txt permits the configured user agent"
                if robots_allowed
                else "robots.txt explicitly disallows the dialogue directory"
            )
        elif robots.status_code == 404:
            robots_status = "not_found"
            robots_note = "robots.txt returned 404; conservative single-request pacing applies"
        elif robots.status_code in ACCESS_BLOCK_STATUSES:
            raise BH3TextAccessError(
                f"BH3Text robots.txt returned HTTP {robots.status_code}; collection stopped"
            )
        else:
            robots_status = "unavailable"
            robots_note = (
                f"robots.txt returned HTTP {robots.status_code}; "
                "conservative single-request pacing applies"
            )
    except httpx.HTTPError as exc:
        robots_note = (
            f"robots.txt unavailable ({type(exc).__name__}); "
            "conservative single-request pacing applies"
        )
    if not robots_allowed:
        raise BH3TextAccessError(robots_note)

    root = _get(
        client,
        BH3TEXT_ROOT,
        delay_seconds=delay_seconds,
        sleeper=sleeper,
    )
    about = _get(
        client,
        BH3TEXT_ABOUT,
        delay_seconds=delay_seconds,
        sleeper=sleeper,
    )
    about_text = BeautifulSoup(about.text, "html.parser").get_text(" ", strip=True)
    usage_statement_found = all(
        marker in about_text for marker in ("游戏文本存档", "网络收集", "版权")
    )
    return {
        "checked_at": utc_now(),
        "robots_status": robots_status,
        "robots_http_status": robots_http_status,
        "robots_note": robots_note,
        "public_root_status": root.status_code,
        "about_status": about.status_code,
        "usage_statement_found": usage_statement_found,
        "source_classification": SOURCE_TIER,
        "official_host": False,
    }


def _directory_links(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    output: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        title = _visible_title(anchor.get_text(" ", strip=True))
        if title not in TARGET_DIRECTORIES:
            continue
        url = _canonical_bh3text_url(str(anchor.get("href", "")), BH3TEXT_ROOT)
        if url:
            output[title] = url
    return output


def _detail_links(html: str, directory_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    directory_path = urlsplit(directory_url).path.rstrip("/") + "/"
    for anchor in soup.find_all("a", href=True):
        title = _visible_title(anchor.get_text(" ", strip=True))
        url = _canonical_bh3text_url(str(anchor.get("href", "")), directory_url)
        if not title or not url or url in seen:
            continue
        path = urlsplit(url).path
        if not path.startswith(directory_path) or path.rstrip("/") == directory_path.rstrip("/"):
            continue
        if title in NAVIGATION_TEXT or title.startswith(("←", "→")):
            continue
        seen.add(url)
        output.append((title, url))
    return output


def _matches(title: str) -> tuple[list[str], list[str]]:
    characters = [name for name in CHARACTER_NAMES if name in title]
    if "芽衣" in characters and "雷电芽衣" in characters:
        characters.remove("芽衣")
    topics = [name for name in TOPIC_NAMES if name in title]
    return characters, list(dict.fromkeys(topics))


def _score_candidate(
    title: str,
    *,
    arc: str,
    chapter: str,
    characters: list[str],
    topics: list[str],
) -> tuple[int, str, str]:
    score = len(characters) * 12 + len(topics) * 10
    reasons: list[str] = []
    if re.match(r"^.+-关于.+", title):
        score += 60
        reasons.append("角色关于主题/角色的专门场景")
    if "关于自身" in title:
        score += 30
        reasons.append("角色关于自身的直接场景")
    if title.startswith("爱莉希雅-") or "-关于爱莉希雅" in title:
        score += 30
        reasons.append("爱莉希雅双向高优先级标题")
    if arc == "主线第一部" and (characters or topics):
        score += 25
        reasons.append("主线29—31章中的明确角色/设定标题")
    elif arc == "主线第一部" and not _is_pure_gameplay_title(title):
        score += 8
        reasons.append("主线29—31章非玩法目录场景，保留供coverage-gap组内排序")
    if chapter == "第三十一章 因你而在的故事":
        score += 20
        reasons.append("主线31章最高补采优先级")
    if _is_pure_gameplay_title(title):
        score -= 100
        reasons.append("卡牌、宝箱、探索或无剧情系统/操作项")
    if characters:
        reasons.append("标题命中角色：" + "、".join(characters))
    if topics:
        reasons.append("标题命中主题：" + "、".join(topics))
    decision = "include" if score > 0 and not _is_pure_gameplay_title(title) else "exclude"
    if decision == "exclude":
        reasons.append("标题未命中本阶段角色或主题；不采集正文")
    return score, decision, "；".join(reasons)


def _write_candidate_markdown(
    path: Path,
    rows: list[BH3TextCandidateAudit],
    access: dict[str, Any],
) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.chapter] = counts.get(row.chapter, 0) + 1
    lines = [
        "# BH3Text 候选场景审计",
        "",
        "> BH3Text 不是米哈游官方网站。本表仅由允许范围内的公开栏目发现详情链接；栏目页不进入RAG。",
        "",
        f"- 来源等级：{SOURCE_TIER}",
        f"- robots：{access['robots_status']}（{access['robots_note']}）",
        f"- 公开目录HTTP：{access['public_root_status']}",
        f"- 站点使用说明已识别：{access['usage_statement_found']}",
        f"- 候选：{len(rows)}",
        f"- include：{sum(row.decision == 'include' for row in rows)}",
        f"- exclude：{sum(row.decision == 'exclude' for row in rows)}",
        "",
        "## 各章节候选数",
        "",
    ]
    lines.extend(f"- {chapter}: {count}" for chapter, count in sorted(counts.items()))
    lines.extend(
        [
            "",
            "| 决策 | 分数 | 篇章 | 章节 | 场景 | 命中角色 | 命中主题 | URL | 原因 |",
            "|---|---:|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row.decision} | {row.priority_score} | {row.arc} | {row.chapter} | "
            f"{row.scene} | {'、'.join(row.matched_characters) or '-'} | "
            f"{'、'.join(row.matched_topics) or '-'} | {row.url} | {row.reason} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover_bh3text(
    paths: PipelinePaths | None = None,
    *,
    scope: str = "elysia",
    max_candidates: int = 300,
    delay_seconds: float = 3.0,
    timeout_seconds: float = 20.0,
    client: httpx.Client | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Discover and audit candidates; never persist a directory as a document."""

    if scope != "elysia":
        raise ValueError("BH3Text discovery supports scope=elysia only")
    if not 1 <= max_candidates <= 300:
        raise ValueError("max_candidates must be between 1 and 300")
    if client is None and not 2 <= delay_seconds <= 3:
        raise ValueError("Live BH3Text discovery delay must be between 2 and 3 seconds")
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    owns_client = client is None
    http = client or httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    try:
        access = inspect_bh3text_access(
            http,
            delay_seconds=delay_seconds,
            sleeper=sleeper,
        )
        root = _get(
            http,
            BH3TEXT_ROOT,
            delay_seconds=delay_seconds,
            sleeper=sleeper,
        )
        directory_urls = _directory_links(root.text)
        missing = sorted(set(TARGET_DIRECTORIES) - set(directory_urls))
        candidates: list[BH3TextCandidateAudit] = []
        for directory_title, directory_url in directory_urls.items():
            arc, chapter = TARGET_DIRECTORIES[directory_title]
            response = _get(
                http,
                directory_url,
                delay_seconds=delay_seconds,
                sleeper=sleeper,
            )
            for title, url in _detail_links(response.text, directory_url):
                characters, topics = _matches(title)
                score, decision, reason = _score_candidate(
                    title,
                    arc=arc,
                    chapter=chapter,
                    characters=characters,
                    topics=topics,
                )
                candidates.append(
                    BH3TextCandidateAudit(
                        url=url,
                        arc=arc,
                        chapter=chapter,
                        scene=title,
                        title=title,
                        matched_characters=characters,
                        matched_topics=topics,
                        priority_score=score,
                        decision=decision,  # type: ignore[arg-type]
                        reason=reason,
                    )
                )
        groups = load_bh3text_collection_groups(paths.bh3text_collection_groups)
        rows = _select_balanced_candidate_audit(
            list({row.url: row for row in candidates}.values()),
            groups,
            max_candidates,
        )
        write_jsonl(
            paths.bh3text_candidate_audit_jsonl,
            [row.model_dump(mode="json") for row in rows],
        )
        _write_candidate_markdown(paths.bh3text_candidate_audit_markdown, rows, access)
        payload = {
            "generated_at": utc_now(),
            "scope": scope,
            "source_type": SOURCE_TYPE,
            "source_tier": SOURCE_TIER,
            "official_host": False,
            "access": access,
            "directory_pages_discovered": len(directory_urls),
            "missing_target_directories": missing,
            "candidate_scenes": len(rows),
            "candidate_selection_mode": "group_reservation_then_global_score",
            "included_scenes": sum(row.decision == "include" for row in rows),
            "excluded_scenes": sum(row.decision == "exclude" for row in rows),
            "directory_pages_in_rag": 0,
            "encountered_restrictions": [],
        }
        manifest = read_json(paths.bh3text_manifest, {})
        manifest.update(payload)
        write_json(paths.bh3text_manifest, manifest)
        return payload
    finally:
        if owns_client:
            http.close()


def _navigation_line(value: str, title: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped == title or stripped in NAVIGATION_TEXT:
        return True
    if set(stripped) <= {"*", "-", "—", "_", "|"}:
        return True
    if stripped.startswith(("←", "→")):
        return True
    return False


def _dialogue_lines(soup: BeautifulSoup, heading: Tag, title: str) -> list[str]:
    container = heading.find_parent(["main", "article"]) or heading.parent or soup
    lines: list[str] = []
    started = False
    for node in container.descendants:
        if node is heading:
            started = True
            continue
        if not started or not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if parent is None or parent.name in {"script", "style", "noscript"}:
            continue
        if parent.find_parent(["nav", "footer", "header", "script", "style"]):
            continue
        if parent.name == "a" or parent.find_parent("a"):
            continue
        for value in str(node).replace("\r", "\n").split("\n"):
            value = re.sub(r"[\t\f\v ]+", " ", value).strip()
            if not _navigation_line(value, title):
                lines.append(value)
    return lines


def _structured_dialogue_turns(soup: BeautifulSoup) -> list[DialogueTurn]:
    """Parse the site's explicit stage/dialog-line actor-content structure."""

    turns: list[DialogueTurn] = []
    for line in soup.select("section.stage .dialog-line"):
        content = line.select_one(".dialog-content")
        if content is None:
            continue
        text = re.sub(r"\s+", " ", content.get_text(" ", strip=True)).strip()
        if not text:
            continue
        actor = line.select_one(".dialog-actor")
        label = (
            re.sub(r"\s+", " ", actor.get_text(" ", strip=True)).strip()
            if actor is not None
            else ""
        )
        if not label or label in {"旁白", "画面", "场景", "系统"}:
            speaker = None
            turn_type = "narration"
        else:
            speaker = label.rstrip("：:")
            turn_type = "dialogue"
        turns.append(
            DialogueTurn(
                turn_index=len(turns) + 1,
                speaker=speaker,
                text=text,
                turn_type=turn_type,  # type: ignore[arg-type]
            )
        )
    return turns


def parse_bh3text_dialogue(
    html: str,
    *,
    source_url: str,
    arc: str,
    chapter: str,
    scene: str,
    retrieved_at: str | None = None,
) -> BH3TextDocument:
    """Parse explicit speakers and narration without contextual speaker guessing."""

    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    if not isinstance(heading, Tag):
        raise ValueError("BH3Text detail page has no h1 title")
    title = _visible_title(heading.get_text(" ", strip=True)) or scene
    turns = _structured_dialogue_turns(soup)
    if not turns:
        for line in _dialogue_lines(soup, heading, title):
            match = re.match(r"^([^：:\n]{1,30})[：:](.*)$", line)
            if match and match.group(2).strip():
                label = match.group(1).strip()
                text = match.group(2).strip()
                if label in {"旁白", "画面", "场景", "系统"}:
                    speaker = None
                    turn_type = "narration"
                else:
                    speaker = label
                    turn_type = "dialogue"
            else:
                speaker = None
                text = line
                turn_type = "narration"
            turns.append(
                DialogueTurn(
                    turn_index=len(turns) + 1,
                    speaker=speaker,
                    text=text,
                    turn_type=turn_type,  # type: ignore[arg-type]
                )
            )
    if not turns:
        raise ValueError("BH3Text detail page contains no dialogue or narration")
    rendered = "\n".join(
        f"{turn.speaker}：{turn.text}" if turn.speaker else turn.text for turn in turns
    )
    all_text = f"{title}\n{rendered}"
    character_names = sorted(
        {
            name
            for name in CHARACTER_NAMES
            if name in all_text and not (name == "芽衣" and "雷电芽衣" in all_text)
        }
    )
    topic_names = sorted({name for name in TOPIC_NAMES if name in all_text})
    return BH3TextDocument(
        document_id=stable_id("bh3text", source_url),
        title=title,
        arc=arc,
        chapter=chapter,
        scene=scene or title,
        source_url=source_url,
        dialogue_turns=turns,
        character_names=character_names,
        topic_names=topic_names,
        content_hash=content_hash(rendered),
        retrieved_at=retrieved_at or utc_now(),
    )


def _render_turn(turn: DialogueTurn) -> str:
    return f"{turn.speaker}：{turn.text}" if turn.speaker else turn.text


def _chinese_chars(turns: Iterable[DialogueTurn]) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", "".join(_render_turn(row) for row in turns)))


def chunk_bh3text_document(
    document: BH3TextDocument,
    *,
    minimum_chars: int = 600,
    maximum_chars: int = 1000,
    overlap_turns: int = 3,
) -> list[BH3TextChunk]:
    """Keep short scenes whole and split long scenes only between dialogue turns."""

    turns = document.dialogue_turns
    groups: list[list[DialogueTurn]] = []
    if _chinese_chars(turns) < 1200:
        groups = [turns]
    else:
        start = 0
        while start < len(turns):
            end = start
            size = 0
            while end < len(turns):
                turn_size = _chinese_chars([turns[end]])
                if end > start and size >= minimum_chars and size + turn_size > maximum_chars:
                    break
                size += turn_size
                end += 1
                if size >= maximum_chars:
                    break
            groups.append(turns[start:end])
            if end >= len(turns):
                break
            start = max(start + 1, end - overlap_turns)

    output: list[BH3TextChunk] = []
    for index, group in enumerate(groups, 1):
        content = "\n".join(_render_turn(turn) for turn in group)
        speakers = sorted({turn.speaker for turn in group if turn.speaker})
        output.append(
            BH3TextChunk(
                chunk_id=stable_id(
                    "bh3chunk",
                    f"{document.document_id}:{group[0].turn_index}:{group[-1].turn_index}:{content}",
                ),
                document_id=document.document_id,
                title=document.title,
                arc=document.arc,
                chapter=document.chapter,
                scene=document.scene,
                source_url=document.source_url,
                content=content,
                turn_start=group[0].turn_index,
                turn_end=group[-1].turn_index,
                dialogue_turns=group,
                speaker_names=speakers,
                character_names=document.character_names,
                topic_names=document.topic_names,
                review_status=document.review_status,
            )
        )
    return output


def build_dialogue_evidence_edges(
    document: BH3TextDocument,
) -> list[DialogueEvidenceEdge]:
    edges: dict[str, DialogueEvidenceEdge] = {}

    dialogue = [turn for turn in document.dialogue_turns if turn.speaker]
    for left, right in zip(dialogue, dialogue[1:]):
        if left.speaker == right.speaker:
            continue
        evidence = f"{_render_turn(left)} / {_render_turn(right)}"[:300]
        key = f"SPEAKS_TO:{left.speaker}:{right.speaker}"
        edges[key] = DialogueEvidenceEdge(
            edge_id=stable_id("edge", f"{document.document_id}:{key}"),
            source_entity=left.speaker or "",
            relation="SPEAKS_TO",
            target_entity=right.speaker or "",
            evidence=evidence,
            arc=document.arc,
            chapter=document.chapter,
            scene=document.scene,
            source_url=document.source_url,
        )

    about = re.match(r"^(.+?)-关于(.+?)(?:·其.+)?$", document.title)
    if about:
        source = about.group(1).strip()
        target = about.group(2).strip()
        if target == "自身":
            target = source
        key = f"SPEAKS_ABOUT:{source}:{target}"
        edges[key] = DialogueEvidenceEdge(
            edge_id=stable_id("edge", f"{document.document_id}:{key}"),
            source_entity=source,
            relation="SPEAKS_ABOUT",
            target_entity=target,
            evidence=f"页面标题明确为《{document.title}》；这只是文本证据边。",
            arc=document.arc,
            chapter=document.chapter,
            scene=document.scene,
            source_url=document.source_url,
        )

    speakers = sorted({turn.speaker for turn in dialogue if turn.speaker})
    for source, target in combinations(speakers, 2):
        key = f"APPEARS_WITH:{source}:{target}"
        edges[key] = DialogueEvidenceEdge(
            edge_id=stable_id("edge", f"{document.document_id}:{key}"),
            source_entity=source,
            relation="APPEARS_WITH",
            target_entity=target,
            evidence=f"{source}与{target}均有本场景明确署名台词；不推断语义关系。",
            arc=document.arc,
            chapter=document.chapter,
            scene=document.scene,
            source_url=document.source_url,
        )
    return sorted(edges.values(), key=lambda edge: edge.edge_id)


UNCERTAIN_MARKERS = (
    "玩笑",
    "假如",
    "如果",
    "或许",
    "可能",
    "难道",
    "？",
    "?",
    "听说",
    "据说",
    "我猜",
    "似乎",
    "不确定",
    "并非",
    "不是",
    "不信任",
)


def _semantic_patterns() -> list[tuple[re.Pattern[str], str, float]]:
    entities = sorted(set((*CHARACTER_NAMES, *TOPIC_NAMES)), key=len, reverse=True)
    entity = "(?:" + "|".join(re.escape(value) for value in entities) + ")"
    subject = f"(?P<source>{entity}|我)"
    target = f"(?P<target>{entity})"
    return [
        (re.compile(subject + r"(?:是|也是)" + target + r"(?:的)?(?:成员|一员)"), "MEMBER_OF", 0.82),
        (re.compile(subject + r"属于" + target), "MEMBER_OF", 0.78),
        (re.compile(subject + r"(?:又名|也被称为)" + target), "ALIAS_OF", 0.85),
        (re.compile(subject + r"参与(?:了|过)?" + target), "PARTICIPATED_IN", 0.8),
        (re.compile(subject + r"由" + target + r"(?:创造|制造)"), "CREATED_BY", 0.82),
        (re.compile(subject + r"(?:是|担任)" + target + r"(?:的)?(?:领袖|领导者)"), "LEADER_OF", 0.82),
        (re.compile(subject + r"是" + target + r"(?:的)?朋友"), "FRIEND_OF", 0.78),
        (re.compile(subject + r"信任" + target), "TRUSTS", 0.76),
        (re.compile(subject + r"认识" + target), "KNOWS", 0.72),
    ]


def extract_pending_semantic_relations(
    document: BH3TextDocument,
) -> list[BH3TextPendingRelation]:
    """Extract only narrow explicit assertions; every result remains pending."""

    output: dict[str, BH3TextPendingRelation] = {}
    for turn in document.dialogue_turns:
        if not turn.speaker or any(marker in turn.text for marker in UNCERTAIN_MARKERS):
            continue
        for pattern, relation, confidence in _semantic_patterns():
            for match in pattern.finditer(turn.text):
                source = match.group("source")
                target = match.group("target")
                if source == "我":
                    source = turn.speaker
                if source == target:
                    continue
                key = f"{source}:{relation}:{target}:{turn.turn_index}"
                output[key] = BH3TextPendingRelation(
                    relation_id=stable_id("bh3rel", f"{document.document_id}:{key}"),
                    source_entity=source,
                    relation=relation,  # type: ignore[arg-type]
                    target_entity=target,
                    evidence=turn.text[:300],
                    speaker=turn.speaker,
                    arc=document.arc,
                    chapter=document.chapter,
                    scene=document.scene,
                    source_url=document.source_url,
                    confidence=confidence,
                )
    return sorted(output.values(), key=lambda row: row.relation_id)


def _load_candidates(path: Path, *, accepted_only: bool) -> list[BH3TextCandidateAudit]:
    rows = [BH3TextCandidateAudit.model_validate(row) for row in read_jsonl(path)]
    if accepted_only:
        rows = [row for row in rows if row.decision == "include"]
    return sorted(rows, key=lambda row: (-row.priority_score, row.chapter, row.title))


def _select_with_verification_quota(
    rows: list[BH3TextCandidateAudit], max_pages: int
) -> list[BH3TextCandidateAudit]:
    selected: list[BH3TextCandidateAudit] = []

    def add_matching(predicate: Callable[[BH3TextCandidateAudit], bool], count: int) -> None:
        for row in rows:
            if len([item for item in selected if predicate(item)]) >= count:
                break
            if row not in selected and predicate(row):
                selected.append(row)

    add_matching(lambda row: "爱莉希雅" in row.title, 3)
    add_matching(lambda row: "伊甸" in row.title, 2)
    add_matching(lambda row: "凯文" in row.title, 1)
    add_matching(lambda row: "梅比乌斯" in row.title, 1)
    add_matching(lambda row: "芽衣" in row.title, 1)
    add_matching(lambda row: row.arc == "主线第一部", 2)
    add_matching(lambda row: row.chapter == "第三十一章 因你而在的故事", 1)
    for row in rows:
        if len(selected) >= max_pages:
            break
        if row not in selected:
            selected.append(row)
    return selected[:max_pages]


def _verification_summary(document: BH3TextDocument) -> str:
    speakers = sorted({turn.speaker for turn in document.dialogue_turns if turn.speaker})
    narration = sum(turn.turn_type == "narration" for turn in document.dialogue_turns)
    return (
        f"结构摘要：{'、'.join(speakers) or '无明确说话者'}共"
        f"{len(document.dialogue_turns)}轮，旁白{narration}轮；主题由页面标题《{document.title}》指示。"
    )


def _document_verification_text(document: BH3TextDocument) -> str:
    return "\n".join(
        [
            document.title,
            document.chapter,
            *document.character_names,
            *document.topic_names,
            *(turn.text for turn in document.dialogue_turns),
        ]
    )


def _verification_flags(document: BH3TextDocument) -> dict[str, bool]:
    text = _document_verification_text(document)
    speakers = {turn.speaker for turn in document.dialogue_turns if turn.speaker}
    return {
        "elysia": "爱莉希雅" in text,
        "interaction": len(speakers) >= 2,
        "setting": any(
            marker in text
            for marker in (
                "身份",
                "英桀",
                "律者",
                "记忆体",
                "第十三律者",
                "人之律者",
                "始源",
            )
        ),
        "long": len(document.dialogue_turns) >= 8,
    }


def _verification_score(
    document: BH3TextDocument,
    *,
    previous_document_ids: set[str],
) -> int:
    flags = _verification_flags(document)
    return (
        (2_000 if document.document_id in previous_document_ids else 0)
        + (1_000 if flags["elysia"] else 0)
        + (400 if flags["interaction"] else 0)
        + (250 if flags["setting"] else 0)
        + min(len(document.dialogue_turns), 100)
        + min(len(document.character_names), 5) * 20
    )


def select_verification_documents(
    documents: list[BH3TextDocument],
    groups: dict[str, dict[str, Any]],
    *,
    previous_document_ids: set[str] | None = None,
) -> list[BH3TextDocument]:
    """Choose the fixed 2/1/1/2/2/2 chapter sample with global quality constraints."""

    previous_ids = previous_document_ids or set()
    eligible = [row for row in documents if len(row.dialogue_turns) >= 3]
    by_group: dict[str, list[BH3TextDocument]] = {group_id: [] for group_id in groups}
    for document in eligible:
        group_id = _group_id_for_chapter(document.chapter, groups)
        if group_id:
            by_group[group_id].append(document)
    for rows in by_group.values():
        rows.sort(
            key=lambda row: (
                -_verification_score(row, previous_document_ids=previous_ids),
                row.title,
                row.source_url,
            )
        )
    selected: list[BH3TextDocument] = []
    for group_id, quota in VERIFICATION_QUOTAS.items():
        selected.extend(by_group.get(group_id, [])[:quota])

    def improve(flag: str, minimum: int) -> None:
        while sum(_verification_flags(row)[flag] for row in selected) < minimum:
            replacement: tuple[int, BH3TextDocument, BH3TextDocument] | None = None
            for group_id, group_rows in by_group.items():
                chosen = [
                    row
                    for row in selected
                    if _group_id_for_chapter(row.chapter, groups) == group_id
                ]
                alternatives = [
                    row
                    for row in group_rows
                    if row not in selected and _verification_flags(row)[flag]
                ]
                victims = [row for row in chosen if not _verification_flags(row)[flag]]
                if not alternatives or not victims:
                    continue
                alternative = alternatives[0]
                victim = min(
                    victims,
                    key=lambda row: _verification_score(
                        row, previous_document_ids=previous_ids
                    ),
                )
                gain = _verification_score(
                    alternative, previous_document_ids=previous_ids
                ) - _verification_score(victim, previous_document_ids=previous_ids)
                if replacement is None or gain > replacement[0]:
                    replacement = (gain, victim, alternative)
            if replacement is None:
                break
            _, victim, alternative = replacement
            selected[selected.index(victim)] = alternative

    improve("elysia", 5)
    improve("interaction", 3)
    improve("setting", 2)
    improve("long", 1)
    group_order = {group_id: index for index, group_id in enumerate(VERIFICATION_QUOTAS)}
    return sorted(
        selected,
        key=lambda row: (
            group_order.get(_group_id_for_chapter(row.chapter, groups), 99),
            -_verification_score(row, previous_document_ids=previous_ids),
            row.title,
        ),
    )


def _sample_turns(document: BH3TextDocument) -> list[DialogueTurn]:
    turns = document.dialogue_turns
    anchor = next(
        (
            index
            for index, turn in enumerate(turns)
            if turn.speaker == "爱莉希雅"
            or any(marker in turn.text for marker in ("英桀", "律者", "记忆体", "爱莉希雅"))
        ),
        0,
    )
    start = max(0, min(anchor - 1, len(turns) - 5))
    return turns[start : start + min(5, len(turns))]


def _verification_video_hint(
    document: BH3TextDocument,
    video_rows: list[dict[str, Any]],
) -> tuple[str, str]:
    chapter_number = {
        "第二十九章 来自乐土": "29章",
        "第三十章 英雄们的葬礼": "30章",
        "第三十一章 因你而在的故事": "31章",
    }.get(document.chapter, "")
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in video_rows:
        title = str(row.get("title", ""))
        # A character-name overlap is not enough to locate a mainline scene in a
        # video. Mainline hints must explicitly name the corresponding chapter.
        if chapter_number and chapter_number not in title:
            continue
        score = 0
        if chapter_number and chapter_number in title:
            score += 100
        if document.chapter == "愿时光永驻此刻，愿明日——" and "第三章" in title:
            score += 80
        score += sum(name in title for name in document.character_names) * 10
        score += len(set(row.get("observed_characters", [])) & set(document.character_names)) * 5
        if score:
            scored.append((score, row))
    if not scored:
        return "", ""
    video = max(scored, key=lambda item: item[0])[1]
    parts = video.get("parts", []) if isinstance(video.get("parts"), list) else []
    part = next(
        (
            str(item.get("part_number", ""))
            for item in parts
            if isinstance(item, dict)
            and any(name in str(item.get("title", "")) for name in document.character_names)
        ),
        "",
    )
    return str(video.get("video_id", "")), part


def write_transcript_verification(
    paths: PipelinePaths,
    documents: list[BH3TextDocument],
) -> int:
    groups = load_bh3text_collection_groups(paths.bh3text_collection_groups)
    previous_rows = {
        str(row.get("document_id", "")): row
        for row in read_jsonl(paths.bh3text_transcript_verification_jsonl)
    }
    selected_documents = select_verification_documents(
        documents,
        groups,
        previous_document_ids=set(previous_rows),
    )
    video_rows = read_jsonl(paths.video_audit_jsonl)
    output: list[BH3TextVerificationRecord] = []
    for document in selected_documents:
        previous = previous_rows.get(document.document_id, {})
        video_id, part = _verification_video_hint(document, video_rows)
        output.append(
            BH3TextVerificationRecord(
                verification_id=stable_id("bh3verify", document.document_id),
                document_id=document.document_id,
                title=document.title,
                arc=document.arc,
                chapter=document.chapter,
                source_url=document.source_url,
                video_id=video_id,
                suggested_video_part=part,
                video_timestamp=str(previous.get("video_timestamp", "")),
                sample_turns=_sample_turns(document),
                verification_status=str(
                    previous.get("verification_status", "not_checked")
                ),  # type: ignore[arg-type]
                mismatch_type=str(previous.get("mismatch_type", "")),
                reviewer_note=str(previous.get("reviewer_note", "")),
            )
        )
    write_jsonl(
        paths.bh3text_transcript_verification_jsonl,
        [row.model_dump(mode="json") for row in output],
    )
    lines = [
        "# BH3Text 剧情文本抽样核验",
        "",
        "> 默认均为 `not_checked`。程序未播放或下载B站视频，也绝不会自行填写 `match`。",
        "",
        "## 人工核验标准",
        "",
        "- `match`：场景标题一致或明确对应；说话者一致；抽样3～5轮台词内容一致；没有关键台词缺失；允许标点、空格和个别异体字差异。",
        "- `minor_mismatch`：少量标点、个别错字或不影响含义的格式差异。",
        "- `critical_mismatch`：说话者错误、台词被改写、大段缺失、不同剧情场景混合，或身份/关系/事件含义发生变化。",
        "- `not_checked`：尚未人工查看视频或游戏原文。",
        "",
    ]
    for index, row in enumerate(output, 1):
        turns = "\n".join(
            f"  - {turn.speaker or '旁白'}：{turn.text}"
            for turn in row.sample_turns
        )
        lines.extend(
            [
                f"## {index}. {row.title}",
                "",
                f"- verification_id：{row.verification_id}",
                f"- 篇章：{row.chapter}",
                f"- BH3Text URL：{row.source_url}",
                f"- 来源等级：{SOURCE_TIER}",
                f"- 对应B站视频BV号：{row.video_id or '待人工指定'}",
                f"- 推荐核验分P：{row.suggested_video_part or '待人工选择'}",
                f"- 视频时间点：{row.video_timestamp or '待填写'}",
                f"- 核验结果：{row.verification_status}",
                f"- mismatch_type：{row.mismatch_type}",
                f"- 审核备注：{row.reviewer_note}",
                "- 抽样台词：",
                turns,
                "",
            ]
        )
    paths.bh3text_transcript_verification.parent.mkdir(parents=True, exist_ok=True)
    paths.bh3text_transcript_verification.write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return len(output)


def build_vector_readiness(
    paths: PipelinePaths,
    documents: list[BH3TextDocument],
    chunks: list[BH3TextChunk],
) -> dict[str, Any]:
    verification_rows = [
        BH3TextVerificationRecord.model_validate(row)
        for row in read_jsonl(paths.bh3text_transcript_verification_jsonl)
    ]
    reviewed = sum(row.verification_status != "not_checked" for row in verification_rows)
    matches = sum(row.verification_status == "match" for row in verification_rows)
    critical = sum(
        row.verification_status == "critical_mismatch" for row in verification_rows
    )
    mainline_31 = sum(
        row.chapter == "第三十一章 因你而在的故事" for row in documents
    )
    all_source_urls = all(
        row.source_url.startswith("https://www.bh3text.com/dialog/") for row in chunks
    )
    fixture_markers = (
        "synthetic",
        "fixture",
        "example.invalid",
        "SYNTHETIC_",
        "/synthetic",
        "测试夹具",
    )
    fixture_hits = sum(
        any(
            marker.lower()
            in f"{row.title}\n{row.source_url}\n{row.content}".lower()
            for marker in fixture_markers
        )
        for row in chunks
    )
    thresholds = {
        "minimum_reviewed_scenes": 10,
        "minimum_matches": 8,
        "maximum_critical_mismatches": 0,
        "mainline_31_minimum_documents": 8,
        "minimum_total_bh3text_chunks": 120,
        "all_chunks_have_source_url": True,
        "test_fixture_hits": 0,
    }
    actual = {
        "reviewed_scenes": reviewed,
        "matches": matches,
        "critical_mismatches": critical,
        "mainline_31_documents": mainline_31,
        "total_bh3text_chunks": len(chunks),
        "all_chunks_have_source_url": all_source_urls,
        "test_fixture_hits": fixture_hits,
    }
    conditions = {
        "minimum_reviewed_scenes": reviewed >= 10,
        "minimum_matches": matches >= 8,
        "maximum_critical_mismatches": critical <= 0,
        "mainline_31_minimum_documents": mainline_31 >= 8,
        "minimum_total_bh3text_chunks": len(chunks) >= 120,
        "all_chunks_have_source_url": all_source_urls,
        "test_fixture_hits": fixture_hits == 0,
    }
    vector_ready = all(conditions.values())
    payload = {
        "generated_at": utc_now(),
        **thresholds,
        "actual": actual,
        "conditions_met": conditions,
        "manual_review_complete": reviewed >= 10,
        "vector_ready": vector_ready,
        "reason": (
            "全部质量门已通过；仍需单独决策是否建立向量索引"
            if vector_ready
            else "人工核验或数据质量门尚未全部通过，不得建立向量索引"
        ),
    }
    write_json(paths.vector_readiness, payload)
    return payload


def _rebuild_outputs(paths: PipelinePaths) -> dict[str, Any]:
    documents = [
        BH3TextDocument.model_validate(row) for row in read_jsonl(paths.bh3text_documents)
    ]
    chunks = [chunk for document in documents for chunk in chunk_bh3text_document(document)]
    evidence_edges = [
        edge for document in documents for edge in build_dialogue_evidence_edges(document)
    ]
    pending_relations = [
        relation
        for document in documents
        for relation in extract_pending_semantic_relations(document)
    ]
    write_jsonl(paths.bh3text_chunks, [row.model_dump(mode="json") for row in chunks])
    write_jsonl(
        paths.dialogue_evidence_edges,
        [row.model_dump(mode="json") for row in evidence_edges],
    )
    write_jsonl(
        paths.bh3text_relations_pending,
        [row.model_dump(mode="json") for row in pending_relations],
    )
    verification_count = write_transcript_verification(paths, documents)
    readiness = build_vector_readiness(paths, documents, chunks)
    sampled_verified = sum(
        row.get("verification_status") in {"match", "minor_mismatch"}
        for row in read_jsonl(paths.bh3text_transcript_verification_jsonl)
    )
    index_ready = bool(readiness["vector_ready"])
    return {
        "documents": len(documents),
        "dialogue_turns": sum(len(row.dialogue_turns) for row in documents),
        "chunks": len(chunks),
        "evidence_edges": len(evidence_edges),
        "pending_relations": len(pending_relations),
        "verification_scenes": verification_count,
        "sampled_verified_documents": sampled_verified,
        "independent_transcript_index_ready": index_ready,
        "independent_transcript_index_reason": (
            "至少10个抽样场景已人工核验，可评估建立独立剧情文本索引"
            if index_ready
            else "vector_readiness仍为false，尚未通过人工核验与数据质量门"
        ),
        "vector_ready": index_ready,
    }


def build_bh3text(paths: PipelinePaths | None = None) -> dict[str, Any]:
    """Rebuild all derived BH3Text outputs without collecting any page."""

    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    counts = _rebuild_outputs(paths)
    documents = [
        BH3TextDocument.model_validate(row)
        for row in read_jsonl(paths.bh3text_documents)
    ]
    by_chapter: dict[str, int] = {}
    for document in documents:
        by_chapter[document.chapter] = by_chapter.get(document.chapter, 0) + 1
    # Normalize snapshots generated by an older discovery manifest that omitted
    # chapter_counts. This never changes the historical before/after document
    # counts; it only makes their manifest view agree with the successful docs.
    for snapshot_path in (
        paths.bh3text_group_coverage_before,
        paths.bh3text_group_coverage_after,
    ):
        snapshot = read_json(snapshot_path, {})
        changed = False
        for row in snapshot.get("groups", []):
            if int(row.get("manifest_documents", 0)) == 0 and int(
                row.get("successful_documents", 0)
            ) > 0:
                row["manifest_documents"] = int(row["successful_documents"])
                row["manifest_count_source"] = "successful_documents_fallback"
                changed = True
        if changed:
            write_json(snapshot_path, snapshot)
    manifest = read_json(paths.bh3text_manifest, {})
    manifest.update(
        {
            "built_at": utc_now(),
            "chapter_counts": by_chapter,
            **counts,
        }
    )
    write_json(paths.bh3text_manifest, manifest)
    return {"chapter_counts": by_chapter, **counts}


def crawl_bh3text(
    paths: PipelinePaths | None = None,
    *,
    scope: str = "elysia",
    max_pages: int = 100,
    mode: str = "standard",
    max_new_pages: int = 40,
    delay_seconds: float = 3.0,
    concurrency: int = 1,
    accepted_candidates_only: bool = True,
    timeout_seconds: float = 20.0,
    client: httpx.Client | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Crawl audited details sequentially and rebuild isolated deterministic outputs."""

    if scope != "elysia":
        raise ValueError("BH3Text crawl supports scope=elysia only")
    if concurrency != 1:
        raise ValueError("BH3Text collection requires concurrency=1")
    if mode not in {"standard", "coverage-gap"}:
        raise ValueError("mode must be standard or coverage-gap")
    if mode == "standard" and not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100 in standard mode")
    if not 1 <= max_new_pages <= 40:
        raise ValueError("max_new_pages must be between 1 and 40")
    if not accepted_candidates_only:
        raise ValueError("BH3Text crawl requires --accepted-candidates-only")
    if not 2 <= delay_seconds <= 3 and client is None:
        raise ValueError("Live BH3Text collection delay must be between 2 and 3 seconds")
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    if not paths.bh3text_candidate_audit_jsonl.exists():
        raise ValueError("discover-bh3text must run before crawl-bh3text")
    existing = {
        row.source_url: row
        for row in (
            BH3TextDocument.model_validate(value)
            for value in read_jsonl(paths.bh3text_documents)
        )
    }
    existing_manifest = read_json(paths.bh3text_manifest, {})
    groups = load_bh3text_collection_groups(paths.bh3text_collection_groups)
    loaded_candidates = _load_candidates(
        paths.bh3text_candidate_audit_jsonl,
        accepted_only=accepted_candidates_only,
    )
    if mode == "coverage-gap":
        candidates = select_coverage_gap_candidates(
            loaded_candidates,
            existing.values(),
            groups,
            max_new_pages=max_new_pages,
        )
        before_counts = _group_counts(existing.values(), groups)
        before_snapshot = _group_coverage_snapshot(
            groups,
            before_counts,
            manifest_counts=existing_manifest.get("chapter_counts", {}),
            selected=candidates,
        )
        before_snapshot.update(
            {
                "mode": mode,
                "max_new_pages": max_new_pages,
                "selected_new_pages": len(candidates),
            }
        )
        write_json(paths.bh3text_group_coverage_before, before_snapshot)
    else:
        candidates = _select_with_verification_quota(loaded_candidates, max_pages)
        before_counts = _group_counts(existing.values(), groups)
    raw_rows = {str(row.get("source_url", "")): row for row in read_jsonl(paths.bh3text_raw_documents)}
    owns_client = client is None
    http = client or httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    access: dict[str, Any] = {}
    restrictions: list[str] = []
    collection_errors: list[str] = []
    fetched = 0
    skipped_existing = 0
    remaining_capacity = (
        max_new_pages if mode == "coverage-gap" else max(0, max_pages - len(existing))
    )
    current_group_counts = dict(before_counts)
    try:
        access = inspect_bh3text_access(
            http,
            delay_seconds=delay_seconds,
            sleeper=sleeper,
        )
        for candidate in candidates:
            if candidate.url in existing:
                skipped_existing += 1
                continue
            if fetched >= remaining_capacity:
                break
            group_id = _group_id_for_chapter(candidate.chapter, groups)
            if mode == "coverage-gap" and (
                not group_id
                or current_group_counts.get(group_id, 0)
                >= int(groups[group_id]["target_total"])
            ):
                continue
            try:
                response = _get(
                    http,
                    candidate.url,
                    delay_seconds=delay_seconds,
                    sleeper=sleeper,
                )
            except BH3TextAccessError as exc:
                restrictions.append(str(exc))
                break
            except httpx.HTTPError as exc:
                collection_errors.append(
                    f"{candidate.url}: {type(exc).__name__}"
                )
                break
            retrieved_at = utc_now()
            try:
                document = parse_bh3text_dialogue(
                    response.text,
                    source_url=candidate.url,
                    arc=candidate.arc,
                    chapter=candidate.chapter,
                    scene=candidate.scene,
                    retrieved_at=retrieved_at,
                )
            except ValueError as exc:
                collection_errors.append(f"{candidate.url}: {exc}")
                break
            existing[candidate.url] = document
            if group_id:
                current_group_counts[group_id] = current_group_counts.get(group_id, 0) + 1
            raw_rows[candidate.url] = {
                "document_id": document.document_id,
                "source_url": candidate.url,
                "title": document.title,
                "arc": candidate.arc,
                "chapter": candidate.chapter,
                "scene": candidate.scene,
                "html": response.text,
                "content_hash": content_hash(response.text),
                "retrieved_at": retrieved_at,
                "source_tier": SOURCE_TIER,
                "official_host": False,
            }
            fetched += 1
    finally:
        if owns_client:
            http.close()
    write_jsonl(paths.bh3text_raw_documents, raw_rows.values())
    documents = sorted(existing.values(), key=lambda row: row.source_url)
    write_jsonl(
        paths.bh3text_documents,
        [row.model_dump(mode="json") for row in documents],
    )
    counts = _rebuild_outputs(paths)
    by_chapter: dict[str, int] = {}
    characters: set[str] = set()
    topics: set[str] = set()
    for row in documents:
        by_chapter[row.chapter] = by_chapter.get(row.chapter, 0) + 1
        characters.update(row.character_names)
        topics.update(row.topic_names)
    if mode == "coverage-gap":
        after_counts = _group_counts(documents, groups)
        after_snapshot = _group_coverage_snapshot(
            groups,
            after_counts,
            manifest_counts=existing_manifest.get("chapter_counts", {}),
            selected=candidates,
        )
        after_snapshot.update(
            {
                "mode": mode,
                "max_new_pages": max_new_pages,
                "fetched_this_run": fetched,
                "collection_errors": collection_errors,
                "encountered_restrictions": restrictions,
            }
        )
        write_json(paths.bh3text_group_coverage_after, after_snapshot)
    manifest = read_json(paths.bh3text_manifest, {})
    manifest.update(
        {
            "crawled_at": utc_now(),
            "access": access,
            "crawl_limit": max_pages if mode == "standard" else max_new_pages,
            "crawl_mode": mode,
            "max_new_pages": max_new_pages if mode == "coverage-gap" else 0,
            "selected_candidates": len(candidates),
            "fetched_this_run": fetched,
            "skipped_existing": skipped_existing,
            "encountered_restrictions": restrictions,
            "collection_errors": collection_errors,
            "chapter_counts": by_chapter,
            "covered_characters": sorted(characters),
            "covered_topics": sorted(topics),
            **counts,
        }
    )
    write_json(paths.bh3text_manifest, manifest)
    return manifest
