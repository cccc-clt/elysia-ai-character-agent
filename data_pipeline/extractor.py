"""HTML discovery and conservative main-text extraction."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from data_pipeline.utils import compact_text, effective_text_length, normalize_url


CONTENT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    ".wiki-content",
    ".article-content",
    ".detail-content",
    ".content",
    "#content",
)


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    label: str


@dataclass(frozen=True)
class ExtractedPage:
    title: str
    content: str
    canonical_url: str
    links: tuple[DiscoveredLink, ...]
    needs_dynamic_render: bool


def _link_label(anchor: object) -> str:
    label = anchor.get_text(" ", strip=True)  # type: ignore[attr-defined]
    if label:
        return label
    image = anchor.find("img")  # type: ignore[attr-defined]
    if image:
        return str(image.get("alt") or image.get("title") or "").strip()
    return str(anchor.get("title") or "").strip()  # type: ignore[attr-defined]


def extract_html(html: str, page_url: str) -> ExtractedPage:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select(
        "script, style, noscript, template, svg, canvas, nav, footer, "
        "[aria-hidden='true'], .advertisement, .comments, .share"
    ):
        node.decompose()

    title = ""
    og_title = soup.select_one("meta[property='og:title']")
    if og_title:
        title = str(og_title.get("content") or "").strip()
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    if not title:
        heading = soup.find("h1")
        title = heading.get_text(" ", strip=True) if heading else "未命名官方页面"

    canonical_url = normalize_url(page_url)
    canonical_node = soup.select_one("link[rel~='canonical']")
    if canonical_node and canonical_node.get("href"):
        candidate = normalize_url(str(canonical_node["href"]), page_url)
        canonical_url = candidate or canonical_url

    main = None
    for selector in CONTENT_SELECTORS:
        candidate = soup.select_one(selector)
        if candidate and effective_text_length(candidate.get_text(" ", strip=True)) > 20:
            main = candidate
            break
    if main is None:
        main = soup.body or soup
    content = compact_text(main.get_text("\n", strip=True))

    links: list[DiscoveredLink] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = normalize_url(str(anchor.get("href") or ""), page_url)
        if not href or href in seen:
            continue
        seen.add(href)
        links.append(DiscoveredLink(href, _link_label(anchor)))

    lowered = content.lower()
    loading_only = lowered in {"loading", "loading...", "加载中", "加载中..."}
    needs_render = effective_text_length(content) < 200 or loading_only
    return ExtractedPage(
        title=title,
        content=content,
        canonical_url=canonical_url,
        links=tuple(links),
        needs_dynamic_render=needs_render,
    )

