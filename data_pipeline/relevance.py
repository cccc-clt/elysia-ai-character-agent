"""Explainable local relevance scoring and document quality helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from data_pipeline.config import (
    CORE_CHARACTERS,
    CORE_CONCEPTS,
    GAMEPLAY_MARKERS,
    HARD_GAMEPLAY_MARKERS,
    HIGH_PRIORITY_CONCEPTS,
    LORE_MARKERS,
    NEWS_PROMO_MARKERS,
    RelevanceScoringConfig,
)
from data_pipeline.utils import compact_text


NAVIGATION_LINES = {
    "米哈游官方社区",
    "首页",
    "新闻",
    "角色",
    "舞台",
    "视听中心",
    "社区",
    "商城",
    "充值中心",
    "成长关爱系统",
    "返回",
    "打开App",
    "米游社·崩坏3",
    "最近搜索",
    "清空",
    "词条贡献者：",
    "词条贡献",
    "更多贡献者",
    "目录",
    "用户协议",
    "隐私政策",
    "儿童隐私政策",
    "自律公约",
    "成长关爱",
    "关于我们",
    "联系我们",
    "返回顶部",
    "下载",
    "登录",
    "点赞",
    "评论",
}

TAIL_BOUNDARY_PREFIXES = (
    "词条内容由圣芙蕾雅档案馆编辑团队原创",
    "建议与反馈",
)

NAVIGATION_PATTERNS = (
    re.compile(r"^点击(?:阅读|查看|展开|收起)"),
    re.compile(r"^(?:登录|打开).{0,8}(?:App|后)"),
    re.compile(r"^(?:官方微博|官方微信|官方B站|官方社区)$"),
    re.compile(r"^(?:上一页|下一页|上一话|下一话)$"),
)


@dataclass(frozen=True)
class CleanTextResult:
    content: str
    chinese_char_count: int
    navigation_noise_ratio: float
    duplicate_paragraph_count: int


@dataclass(frozen=True)
class RelevanceResult:
    matched_keywords: tuple[str, ...]
    relevance_score: int
    decision: str
    reason: str
    score_breakdown: tuple[str, ...]
    page_category: str


def count_chinese(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def is_discovery_index_url(url: str) -> bool:
    path = urlsplit(url).path.rstrip("/")
    return "/wiki/channel/" in path or path in {"/valkyries", "/book"}


def _is_navigation_line(line: str) -> bool:
    if line in NAVIGATION_LINES:
        return True
    return any(pattern.search(line) for pattern in NAVIGATION_PATTERNS)


def clean_document_text(text: str) -> CleanTextResult:
    compacted = compact_text(text)
    original_length = max(1, len(re.sub(r"\s+", "", compacted)))
    source_lines = compacted.splitlines()
    for index, line in enumerate(source_lines):
        if any(line.startswith(prefix) for prefix in TAIL_BOUNDARY_PREFIXES):
            source_lines = source_lines[:index]
            break
    kept: list[str] = []
    seen: set[str] = set()
    removed_characters = 0
    duplicate_count = 0
    for line in source_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_navigation_line(stripped):
            removed_characters += len(re.sub(r"\s+", "", stripped))
            continue
        if stripped in seen:
            duplicate_count += 1
            removed_characters += len(re.sub(r"\s+", "", stripped))
            continue
        seen.add(stripped)
        kept.append(stripped)
    cleaned = "\n".join(kept).strip()
    return CleanTextResult(
        content=cleaned,
        chinese_char_count=count_chinese(cleaned),
        navigation_noise_ratio=round(
            min(1.0, removed_characters / original_length), 4
        ),
        duplicate_paragraph_count=duplicate_count,
    )


def filter_official_news_content(text: str) -> str:
    """Keep lore/character paragraphs while dropping promotional combat lines."""

    output: list[str] = []
    numeric_combat = re.compile(
        r"(?:\d+(?:\.\d+)?%|技能倍率|攻击力|伤害提高|暴击率|消耗\s*\d+|水晶\s*[×x*]?\s*\d+)"
    )
    for line in compact_text(text).splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in NEWS_PROMO_MARKERS):
            continue
        if numeric_combat.search(stripped):
            continue
        output.append(stripped)
    return "\n".join(output).strip()


def clean_content_for_url(text: str, url: str) -> CleanTextResult:
    cleaned = clean_document_text(text)
    parts = urlsplit(url)
    if (parts.hostname or "").lower() not in {"www.bh3.com", "bh3.com"}:
        return cleaned
    if not parts.path.startswith(("/news/", "/content/", "/information/")):
        return cleaned
    filtered = filter_official_news_content(cleaned.content)
    return CleanTextResult(
        content=filtered,
        chinese_char_count=count_chinese(filtered),
        navigation_noise_ratio=cleaned.navigation_noise_ratio,
        duplicate_paragraph_count=cleaned.duplicate_paragraph_count,
    )


def _keyword_hits(text: str, *, allow_single_character: bool) -> list[str]:
    candidates = [*CORE_CHARACTERS, *CORE_CONCEPTS]
    selected: list[str] = []
    for keyword in sorted(set(candidates), key=len, reverse=True):
        if len(keyword) == 1:
            if not allow_single_character:
                continue
            pattern = rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(keyword)}(?![\u4e00-\u9fffA-Za-z0-9])"
            if not re.search(pattern, text):
                continue
        elif keyword not in text:
            continue
        if any(keyword in longer for longer in selected):
            continue
        selected.append(keyword)
    return selected


def classify_page(title: str, content: str, url: str) -> str:
    if is_discovery_index_url(url):
        return "navigation"
    # Wiki pages append recommendations and editor controls after the article.
    # Page-type signals are therefore evaluated on the leading article region,
    # not anywhere in the full DOM-derived text.
    combined = f"{title}\n{content[:1200]}"
    if any(marker in title for marker in NEWS_PROMO_MARKERS):
        return "gameplay"
    if any(marker in combined for marker in HARD_GAMEPLAY_MARKERS):
        return "gameplay"
    gameplay_hits = sum(1 for marker in GAMEPLAY_MARKERS if marker in combined)
    lore_hits = sum(1 for marker in LORE_MARKERS if marker in combined)
    core_hits = _keyword_hits(combined, allow_single_character=False)
    if gameplay_hits >= 3:
        return "gameplay"
    if gameplay_hits >= 2 and lore_hits > 0:
        return "mixed"
    if lore_hits > 0 or len(core_hits) >= 2:
        return "lore"
    return "unknown"


def score_candidate(
    *,
    title: str,
    content: str,
    url: str,
    metadata_status: str = "success",
    config: RelevanceScoringConfig | None = None,
) -> RelevanceResult:
    config = config or RelevanceScoringConfig()
    cleaned = clean_content_for_url(content, url)
    title_hits = _keyword_hits(title, allow_single_character=True)
    summary_hits = _keyword_hits(
        cleaned.content[:1200], allow_single_character=False
    )
    matched = tuple(dict.fromkeys([*title_hits, *summary_hits]))
    category = classify_page(title, cleaned.content, url)
    score = 0
    breakdown: list[str] = []

    if "爱莉希雅" in title:
        score += config.title_elysia
        breakdown.append(f"标题包含爱莉希雅 +{config.title_elysia}")
    if any(keyword in title for keyword in HIGH_PRIORITY_CONCEPTS):
        score += config.title_high_priority_concept
        breakdown.append(
            f"标题包含核心组织/概念 +{config.title_high_priority_concept}"
        )
    if any(keyword in CORE_CHARACTERS for keyword in title_hits):
        score += config.title_core_character
        breakdown.append(f"标题包含核心角色 +{config.title_core_character}")
    if len(summary_hits) >= config.summary_keyword_threshold:
        score += config.summary_multiple_keywords
        breakdown.append(
            f"正文包含至少{config.summary_keyword_threshold}个核心关键词 "
            f"+{config.summary_multiple_keywords}"
        )
    if category in {"lore", "mixed"}:
        score += config.lore_category
        breakdown.append(f"页面包含剧情/档案/设定信号 +{config.lore_category}")
    if category == "gameplay":
        score += config.gameplay_category
        breakdown.append(f"页面属于攻略/数值/战斗资料 {config.gameplay_category}")
    if category == "navigation":
        score += config.navigation_page
        breakdown.append(f"页面属于栏目导航 {config.navigation_page}")
    if cleaned.chinese_char_count < config.minimum_chinese_chars:
        score += config.insufficient_content
        breakdown.append(
            f"有效中文不足{config.minimum_chinese_chars}字 "
            f"{config.insufficient_content}"
        )

    exclusion_reason = ""
    if metadata_status != "success":
        exclusion_reason = f"元数据状态为 {metadata_status}"
    elif category == "navigation":
        exclusion_reason = "栏目页仅用于发现链接"
    elif cleaned.chinese_char_count < config.minimum_chinese_chars:
        exclusion_reason = "有效中文正文不足"
    elif category == "gameplay":
        exclusion_reason = "正文以怪物、技能、数值或战斗机制为主"
    elif not title_hits and len(summary_hits) < config.summary_keyword_threshold:
        exclusion_reason = "标题和正文摘要没有可靠的直接范围匹配"
    elif score < config.include_threshold:
        exclusion_reason = f"相关性得分低于 {config.include_threshold}"

    if exclusion_reason:
        decision = "exclude"
        reason = exclusion_reason
    else:
        decision = "include"
        reason = "直接匹配核心主题且未命中强排除规则"
    return RelevanceResult(
        matched_keywords=matched,
        relevance_score=score,
        decision=decision,
        reason=reason,
        score_breakdown=tuple(breakdown),
        page_category=category,
    )
