"""Conservative Bilibili metadata audit and subtitle-review pipeline.

The module intentionally keeps every video artifact outside the main lore RAG.
It performs one no-cookie public HTML request per inspected page, never downloads
audio/video, and never turns video co-occurrence into a confirmed fact/relation.
"""

from __future__ import annotations

import html as html_module
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

import httpx
import yaml
from bs4 import BeautifulSoup
from pydantic import ValidationError

from data_pipeline.config import CORE_CHARACTERS, CORE_CONCEPTS, PipelinePaths
from data_pipeline.schemas import (
    BilibiliVideoMetadata,
    VideoManualRecord,
    VideoPart,
    VideoSubtitleChunk,
    VideoSubtitleCue,
    VideoSubtitleTrack,
)
from data_pipeline.utils import compact_text, read_jsonl, stable_id, utc_now, write_json, write_jsonl


BILIBILI_VIDEO_RE = re.compile(r"\b(BV[0-9A-Za-z]{10})\b")
BLOCKED_STATUSES = {403, 412, 429}
SUBTITLE_HOSTS = {"aisubtitle.hdslb.com"}
SUBTITLE_SUFFIXES = {".srt", ".vtt", ".txt", ".md", ".json", ".yaml", ".yml"}
SOUND_ONLY_RE = re.compile(
    r"^\s*[\[【（(].{0,24}(?:音乐|音效|掌声|笑声|music|applause).{0,24}[\]】）)]\s*$",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})"
)


def normalize_bilibili_video_url(value: str) -> tuple[str, str]:
    """Return canonical public video URL and BV id; reject unrelated URLs."""

    match = BILIBILI_VIDEO_RE.search(value.strip())
    if not match:
        raise ValueError(f"No valid Bilibili BV id found: {value}")
    video_id = match.group(1)
    if value.strip().startswith(("http://", "https://")):
        host = (urlsplit(value.strip()).hostname or "").lower()
        if host not in {"bilibili.com", "www.bilibili.com"}:
            raise ValueError(f"Unsupported Bilibili host: {host}")
    return f"https://www.bilibili.com/video/{video_id}", video_id


def load_video_seeds(path: Path) -> list[str]:
    if not path.exists():
        return []
    seeds: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        canonical, _ = normalize_bilibili_video_url(line)
        if canonical not in seen:
            seeds.append(canonical)
            seen.add(canonical)
    return seeds


def _load_official_accounts(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Invalid official-account allowlist: {path}") from exc
    accounts = payload.get("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("bilibili_official_accounts.yaml accounts must be a list")
    result: dict[str, str] = {}
    for row in accounts:
        if not isinstance(row, dict):
            raise ValueError("Each official account entry must be an object")
        uploader_id = str(row.get("uploader_id", "")).strip()
        evidence = str(row.get("evidence", "")).strip()
        if not uploader_id or not evidence:
            raise ValueError("Official account entries require uploader_id and evidence")
        result[uploader_id] = evidence
    return result


def classify_video(
    title: str,
    description: str,
    uploader_id: str,
    official_accounts: dict[str, str],
) -> tuple[str, str, bool, str]:
    """Classify conservatively; a title/uploader name never proves official status."""

    evidence = official_accounts.get(uploader_id, "")
    if evidence:
        return "official_video", "A", True, evidence
    text = f"{title}\n{description}".lower()
    if any(marker in text for marker in ("推测", "猜想", "脑洞", "理论", "fan theory")):
        return "fan_theory", "C", False, ""
    if any(marker in text for marker in ("分析", "解析", "考据", "analysis")):
        return "community_analysis", "C", False, ""
    if any(marker in text for marker in ("梳理", "讲解", "盘点", "整理", "总结")):
        return "community_lore_summary", "B", False, ""
    if any(marker in text for marker in ("全剧情", "剧情录屏", "主线剧情", "剧情合集")):
        return "official_game_recording", "B-recording", False, ""
    return "unknown_video", "pending", False, ""


def _extract_balanced_object(text: str, marker: str) -> dict[str, Any]:
    marker_index = text.find(marker)
    if marker_index < 0:
        return {}
    start = text.find("{", marker_index + len(marker))
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return {}
                return value if isinstance(value, dict) else {}
    return {}


def _meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    for attribute, value in selectors:
        tag = soup.find("meta", attrs={attribute: value})
        if tag and tag.get("content"):
            return html_module.unescape(str(tag["content"])).strip()
    return ""


def _published_at(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _term_present(text: str, term: str) -> bool:
    if len(term) == 1:
        return bool(
            re.search(
                rf"(?<![\u4e00-\u9fffA-Za-z0-9]){re.escape(term)}"
                rf"(?![\u4e00-\u9fffA-Za-z0-9])",
                text,
            )
        )
    return term in text


def _observed_metadata_topics(text: str) -> tuple[list[str], list[str]]:
    characters = [name for name in CORE_CHARACTERS if _term_present(text, name)]
    topic_aliases = {
        "逐火十三英桀": ("逐火十三英桀", "逐火十三英杰", "十三英桀", "十三英杰"),
        "往世乐土": ("往世乐土",),
        "永世乐土": ("永世乐土",),
        "融合战士": ("融合战士",),
        "记忆体": ("记忆体", "记忆被封存"),
        "前文明": ("前文明", "第一文明纪元"),
    }
    topics = [
        topic
        for topic, aliases in topic_aliases.items()
        if any(alias in text for alias in aliases)
    ]
    return characters, topics


def parse_public_video_html(
    html: str,
    canonical_url: str,
    official_accounts: dict[str, str] | None = None,
) -> BilibiliVideoMetadata:
    """Parse public HTML/meta/embedded initial state without calling an API."""

    _, video_id = normalize_bilibili_video_url(canonical_url)
    soup = BeautifulSoup(html, "html.parser")
    state = _extract_balanced_object(html, "__INITIAL_STATE__")
    video_data = state.get("videoData", {}) if isinstance(state, dict) else {}
    if not isinstance(video_data, dict):
        video_data = {}
    owner = video_data.get("owner", {})
    if not isinstance(owner, dict):
        owner = {}
    title = str(video_data.get("title") or _meta_content(soup, ("property", "og:title"))).strip()
    if title.endswith("_哔哩哔哩_bilibili"):
        title = title[: -len("_哔哩哔哩_bilibili")].strip()
    description = str(
        video_data.get("desc")
        or _meta_content(soup, ("name", "description"), ("property", "og:description"))
    ).strip()
    uploader_name = str(owner.get("name") or _meta_content(soup, ("name", "author"))).strip()
    uploader_id = str(owner.get("mid") or "").strip()
    content_type, tier, verified, identity_evidence = classify_video(
        title, description, uploader_id, official_accounts or {}
    )
    raw_pages = video_data.get("pages", [])
    parts = []
    if isinstance(raw_pages, list):
        for index, row in enumerate(raw_pages, 1):
            if not isinstance(row, dict):
                continue
            duration = row.get("duration")
            parts.append(
                VideoPart(
                    part_number=int(row.get("page") or index),
                    title=str(row.get("part") or ""),
                    duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
                )
            )
    subtitle = video_data.get("subtitle", {})
    raw_tracks = subtitle.get("list", []) if isinstance(subtitle, dict) else []
    tracks: list[VideoSubtitleTrack] = []
    if isinstance(raw_tracks, list):
        for row in raw_tracks:
            if not isinstance(row, dict):
                continue
            raw_url = str(row.get("subtitle_url") or "").strip()
            if raw_url.startswith("//"):
                raw_url = "https:" + raw_url
            tracks.append(
                VideoSubtitleTrack(
                    language_code=str(row.get("lan") or ""),
                    language_name=str(row.get("lan_doc") or ""),
                    public_url=raw_url,
                )
            )
    duration = video_data.get("duration")
    metadata_usable = bool(title or video_data)
    observed_characters, observed_topics = _observed_metadata_topics(
        "\n".join(
            [
                title,
                description,
                *(part.title for part in parts),
            ]
        )
    )
    return BilibiliVideoMetadata(
        video_id=video_id,
        canonical_url=canonical_url,
        title=title,
        uploader_name=uploader_name,
        uploader_id=uploader_id,
        published_at=_published_at(video_data.get("pubdate")),
        description=description,
        duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
        parts=parts,
        observed_characters=observed_characters,
        observed_topics=observed_topics,
        subtitle_available=bool(tracks),
        subtitle_tracks=tracks,
        uploader_verified=verified,
        official_identity_evidence=identity_evidence,
        content_type=content_type,  # type: ignore[arg-type]
        source_tier=tier,  # type: ignore[arg-type]
        review_status="pending",
        metadata_status="success" if metadata_usable else "failed",
        failure_reason="" if metadata_usable else "Public HTML contained no usable video metadata.",
        public_access=metadata_usable,
        subtitle_access_note=(
            "Public subtitle track advertised in page metadata; not yet reviewed."
            if tracks
            else "No public subtitle track advertised in page metadata."
        ),
        diagnostic_note=("" if metadata_usable else "Public HTML contained no usable metadata."),
        inspected_at=utc_now(),
    )


def _failed_metadata(
    canonical_url: str,
    status: str,
    reason: str,
) -> BilibiliVideoMetadata:
    _, video_id = normalize_bilibili_video_url(canonical_url)
    return BilibiliVideoMetadata(
        video_id=video_id,
        canonical_url=canonical_url,
        metadata_status=status,  # type: ignore[arg-type]
        failure_reason=reason,
        public_access=False,
        subtitle_access_note="Not checked because public metadata access failed.",
        diagnostic_note=reason,
        inspected_at=utc_now(),
    )


def _manual_template_for(metadata: BilibiliVideoMetadata, paths: PipelinePaths) -> None:
    target = paths.video_manual_inbox_dir / f"{metadata.video_id}.yaml"
    if target.exists():
        return
    payload = {
        "video_id": metadata.video_id,
        "title": metadata.title,
        "uploader_name": metadata.uploader_name,
        "content_type": metadata.content_type,
        "source_tier": metadata.source_tier,
        "topics": [],
        "characters": [],
        "segments": [
            {
                "start_time": "",
                "end_time": "",
                "summary": "",
                "evidence": "",
                "evidence_type": "",
            }
        ],
        "review_status": "pending",
        "reviewer_note": "",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def write_video_audit(
    metadata_rows: Sequence[BilibiliVideoMetadata], paths: PipelinePaths
) -> dict[str, int]:
    rows = [item.model_dump(mode="json") for item in metadata_rows]
    write_jsonl(paths.video_audit_jsonl, rows)
    lines = [
        "# Bilibili Source Audit",
        "",
        "> All entries remain pending. This audit uses public no-cookie page metadata only; no media, comments, danmaku, or uploader-profile scraping.",
        "",
        "| BV | title | uploader (UID) | published | duration | parts | subtitles | type / tier | access | review |",
        "|---|---|---|---|---:|---:|---|---|---|---|",
    ]
    for item in metadata_rows:
        published = item.published_at.isoformat() if item.published_at else ""
        lines.append(
            "| {bv} | {title} | {uploader} ({uid}) | {published} | {duration} | {parts} | {subs} | {kind} / {tier} | {access} | pending |".format(
                bv=item.video_id,
                title=item.title.replace("|", "\\|") or "Not verified",
                uploader=item.uploader_name.replace("|", "\\|") or "Not verified",
                uid=item.uploader_id or "Not verified",
                published=published or "Not verified",
                duration=item.duration_seconds if item.duration_seconds is not None else "Not verified",
                parts=len(item.parts),
                subs="public track found" if item.subtitle_available else "none/not verified",
                kind=item.content_type,
                tier=item.source_tier,
                access=item.metadata_status,
            )
        )
    lines.extend(["", "## Per-video evidence and review notes", ""])
    for item in metadata_rows:
        lines.extend(
            [
                "",
                f"- `{item.video_id}` official identity evidence: {item.official_identity_evidence or 'none; uploader is not allowlisted as official'}",
                f"- `{item.video_id}` subtitle note: {item.subtitle_access_note}",
                f"- `{item.video_id}` metadata-only coverage: characters={item.observed_characters or ['none']}; topics={item.observed_topics or ['none']}",
                f"- `{item.video_id}` diagnostic: {item.diagnostic_note or item.failure_reason or 'none'}",
            ]
        )
    paths.video_audit_markdown.parent.mkdir(parents=True, exist_ok=True)
    paths.video_audit_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "videos": len(metadata_rows),
        "metadata_success": sum(item.metadata_status == "success" for item in metadata_rows),
        "metadata_blocked": sum(item.metadata_status == "metadata_access_blocked" for item in metadata_rows),
        "metadata_failed": sum(item.metadata_status == "failed" for item in metadata_rows),
        "public_subtitles": sum(item.subtitle_available for item in metadata_rows),
        "pending_review": len(metadata_rows),
    }


def inspect_videos(
    paths: PipelinePaths | None = None,
    *,
    delay_seconds: float = 3.0,
    timeout_seconds: float = 20.0,
    client: httpx.Client | None = None,
) -> dict[str, int]:
    """Inspect each seed once; 403/412/429 are terminal and never retried."""

    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    official_accounts = _load_official_accounts(paths.bilibili_official_accounts)
    seeds = load_video_seeds(paths.video_seed_file)
    owns_client = client is None
    http = client or httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={
            "User-Agent": "ElysiaLoreResearchBot/1.0 (public metadata audit; no cookies)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    results: list[BilibiliVideoMetadata] = []
    try:
        for index, canonical_url in enumerate(seeds):
            if index and delay_seconds:
                time.sleep(delay_seconds)
            try:
                response = http.get(canonical_url)
                if response.status_code in BLOCKED_STATUSES:
                    metadata = _failed_metadata(
                        canonical_url,
                        "metadata_access_blocked",
                        f"HTTP {response.status_code}; no retry or bypass attempted.",
                    )
                elif response.status_code != 200:
                    metadata = _failed_metadata(
                        canonical_url,
                        "failed",
                        f"HTTP {response.status_code}; metadata not imported.",
                    )
                elif any(
                    marker in response.text
                    for marker in ("验证码", "请先登录", "登录后观看", "访问受限")
                ):
                    metadata = _failed_metadata(
                        canonical_url,
                        "metadata_access_blocked",
                        "Public page required login or presented an access challenge; no bypass attempted.",
                    )
                else:
                    metadata = parse_public_video_html(
                        response.text, canonical_url, official_accounts
                    )
            except httpx.HTTPError as exc:
                metadata = _failed_metadata(
                    canonical_url,
                    "failed",
                    f"{type(exc).__name__}: public page request failed.",
                )
            write_json(
                paths.video_metadata_dir / f"{metadata.video_id}.json",
                metadata.model_dump(mode="json"),
            )
            if not metadata.subtitle_available:
                _manual_template_for(metadata, paths)
            results.append(metadata)
    finally:
        if owns_client:
            http.close()
    return write_video_audit(results, paths)


def _seconds(value: str) -> float:
    normalized = value.replace(",", ".")
    parts = [float(part) for part in normalized.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid subtitle timestamp: {value}")


def parse_subtitle_text(text: str, suffix: str) -> list[VideoSubtitleCue]:
    suffix = suffix.lower()
    cues: list[VideoSubtitleCue] = []
    if suffix == ".json":
        payload = json.loads(text)
        raw_rows = payload.get("body", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_rows, list):
            raise ValueError("Subtitle JSON must contain a list or a body list")
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            content = str(row.get("content") or row.get("text") or "").strip()
            if content:
                cues.append(
                    VideoSubtitleCue(
                        start_seconds=float(row.get("from", row.get("start", 0))),
                        end_seconds=float(row.get("to", row.get("end", 0))),
                        content=content,
                    )
                )
        return cues
    if suffix in {".srt", ".vtt"}:
        blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
            if timing_index < 0:
                continue
            timing = TIME_RANGE_RE.search(lines[timing_index])
            if not timing:
                continue
            content = compact_text("\n".join(lines[timing_index + 1 :]))
            if content:
                cues.append(
                    VideoSubtitleCue(
                        start_seconds=_seconds(timing.group("start")),
                        end_seconds=_seconds(timing.group("end")),
                        content=content,
                    )
                )
        return cues
    previous = ""
    for raw_line in text.splitlines():
        content = raw_line.strip()
        if content and content != previous:
            cues.append(VideoSubtitleCue(start_seconds=0, end_seconds=0, content=content))
            previous = content
    return cues


def clean_subtitle_cues(cues: Iterable[VideoSubtitleCue]) -> list[VideoSubtitleCue]:
    cleaned: list[VideoSubtitleCue] = []
    previous = ""
    for cue in cues:
        content = compact_text(html_module.unescape(cue.content))
        if not content or SOUND_ONLY_RE.match(content) or content == previous:
            continue
        cleaned.append(
            VideoSubtitleCue(
                start_seconds=cue.start_seconds,
                end_seconds=cue.end_seconds,
                content=content,
            )
        )
        previous = content
    return cleaned


def _metadata_from_disk(video_id: str, paths: PipelinePaths) -> BilibiliVideoMetadata:
    path = paths.video_metadata_dir / f"{video_id}.json"
    if not path.exists():
        raise ValueError(f"Inspect metadata before processing subtitles: {video_id}")
    return BilibiliVideoMetadata.model_validate_json(path.read_text(encoding="utf-8"))


def _read_manual_record(path: Path) -> VideoManualRecord:
    if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
        raise ValueError("Manual video record must be YAML or JSON")
    try:
        payload = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.suffix.lower() == ".json"
            else yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        return VideoManualRecord.model_validate(payload)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"Invalid manual video record: {path}") from exc


def _manual_cues(record: VideoManualRecord) -> tuple[list[VideoSubtitleCue], str | None]:
    cues: list[VideoSubtitleCue] = []
    evidence_type: str | None = None
    for segment in record.segments:
        content = segment.evidence or segment.summary
        if not content:
            continue
        start = _seconds(segment.start_time) if segment.start_time else 0.0
        end = _seconds(segment.end_time) if segment.end_time else start
        cues.append(VideoSubtitleCue(start_seconds=start, end_seconds=end, content=content))
        if evidence_type is None and segment.evidence_type is not None:
            evidence_type = segment.evidence_type
    return cues, evidence_type


def _fetch_public_subtitle(
    url: str,
    client: httpx.Client,
) -> tuple[str, str]:
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in SUBTITLE_HOSTS:
        raise ValueError("Subtitle URL is not an allowlisted public subtitle CDN URL")
    response = client.get(url, headers={"Accept": "application/json,text/plain"})
    if response.status_code in BLOCKED_STATUSES:
        raise ValueError(f"Subtitle access blocked with HTTP {response.status_code}; no retry")
    response.raise_for_status()
    return response.text, ".json"


def _topic_matches(text: str) -> tuple[list[str], list[str]]:
    characters = [name for name in CORE_CHARACTERS if _term_present(text, name)]
    topics = [name for name in CORE_CONCEPTS if _term_present(text, name)]
    return characters, topics


def _build_video_chunks(
    metadata: BilibiliVideoMetadata,
    cues: Sequence[VideoSubtitleCue],
    evidence_type: str | None,
) -> list[VideoSubtitleChunk]:
    if metadata.source_tier == "C" or metadata.content_type in {"fan_theory", "community_analysis"}:
        return []
    chunks: list[VideoSubtitleChunk] = []
    current: list[VideoSubtitleCue] = []
    current_chars = 0
    for cue in cues:
        current.append(cue)
        current_chars += len(cue.content)
        if current_chars < 450:
            continue
        text = "\n".join(item.content for item in current)
        characters, topics = _topic_matches(text)
        start, end = current[0].start_seconds, current[-1].end_seconds
        chunks.append(
            VideoSubtitleChunk(
                chunk_id=stable_id("vchunk", f"{metadata.video_id}:{start}:{end}:{text}"),
                video_id=metadata.video_id,
                title=metadata.title,
                uploader_name=metadata.uploader_name,
                source_tier=metadata.source_tier,
                content_type=metadata.content_type,
                start_seconds=start,
                end_seconds=end,
                content=text,
                character_names=characters,
                topic_names=topics,
                source_url=f"{metadata.canonical_url}?t={int(start)}",
                evidence_type=evidence_type,  # type: ignore[arg-type]
                source_note="Video evidence is secondary and pending human review; it is not part of the main lore RAG.",
            )
        )
        current, current_chars = [], 0
    if current:
        text = "\n".join(item.content for item in current)
        characters, topics = _topic_matches(text)
        chunks.append(
            VideoSubtitleChunk(
                chunk_id=stable_id("vchunk", f"{metadata.video_id}:{current[0].start_seconds}:{current[-1].end_seconds}:{text}"),
                video_id=metadata.video_id,
                title=metadata.title,
                uploader_name=metadata.uploader_name,
                source_tier=metadata.source_tier,
                content_type=metadata.content_type,
                start_seconds=current[0].start_seconds,
                end_seconds=current[-1].end_seconds,
                content=text,
                character_names=characters,
                topic_names=topics,
                source_url=f"{metadata.canonical_url}?t={int(current[0].start_seconds)}",
                evidence_type=evidence_type,  # type: ignore[arg-type]
                source_note="Video evidence is secondary and pending human review; it is not part of the main lore RAG.",
            )
        )
    return chunks


def process_video_subtitles(
    video_id: str,
    paths: PipelinePaths | None = None,
    *,
    input_path: Path | None = None,
    timeout_seconds: float = 20.0,
    client: httpx.Client | None = None,
) -> dict[str, int]:
    paths = paths or PipelinePaths()
    paths.ensure_runtime_dirs()
    _, normalized_id = normalize_bilibili_video_url(video_id)
    metadata = _metadata_from_disk(normalized_id, paths)
    evidence_type: str | None = None
    owns_client = False
    if input_path is not None:
        suffix = input_path.suffix.lower()
        if suffix not in SUBTITLE_SUFFIXES:
            raise ValueError(f"Unsupported subtitle/manual input: {suffix}")
        if suffix in {".yaml", ".yml"}:
            manual = _read_manual_record(input_path)
            if manual.video_id != normalized_id:
                raise ValueError("Manual record video_id does not match requested video")
            if manual.content_type != metadata.content_type or manual.source_tier != metadata.source_tier:
                raise ValueError("Manual record classification must match inspected metadata")
            cues, evidence_type = _manual_cues(manual)
        else:
            cues = parse_subtitle_text(input_path.read_text(encoding="utf-8"), suffix)
    else:
        if not metadata.subtitle_tracks:
            _manual_template_for(metadata, paths)
            return {"video_id": normalized_id, "raw_cues": 0, "cleaned_cues": 0, "chunks": 0, "manual_required": 1}
        http = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        owns_client = client is None
        try:
            raw_text, suffix = _fetch_public_subtitle(metadata.subtitle_tracks[0].public_url, http)
        finally:
            if owns_client:
                http.close()
        cues = parse_subtitle_text(raw_text, suffix)
    cleaned = clean_subtitle_cues(cues)
    write_jsonl(
        paths.video_subtitles_raw_dir / f"{normalized_id}.jsonl",
        [item.model_dump(mode="json") for item in cues],
    )
    write_jsonl(
        paths.video_subtitles_cleaned_dir / f"{normalized_id}.jsonl",
        [item.model_dump(mode="json") for item in cleaned],
    )
    existing = [row for row in read_jsonl(paths.video_chunks) if row.get("video_id") != normalized_id]
    chunks = _build_video_chunks(metadata, cleaned, evidence_type)
    write_jsonl(paths.video_chunks, existing + [item.model_dump(mode="json") for item in chunks])
    return {
        "video_id": normalized_id,
        "raw_cues": len(cues),
        "cleaned_cues": len(cleaned),
        "chunks": len(chunks),
        "manual_required": 0,
    }


def process_all_video_subtitles(
    paths: PipelinePaths | None = None,
    *,
    delay_seconds: float = 3.0,
    timeout_seconds: float = 20.0,
) -> dict[str, int]:
    """Process advertised public tracks sequentially; create templates otherwise."""

    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")
    paths = paths or PipelinePaths()
    video_ids = [path.stem for path in sorted(paths.video_metadata_dir.glob("BV*.json"))]
    total_chunks = 0
    manual_required = 0
    failures = 0
    for index, video_id in enumerate(video_ids):
        if index and delay_seconds:
            time.sleep(delay_seconds)
        try:
            result = process_video_subtitles(
                video_id,
                paths,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, ValueError, httpx.HTTPError):
            failures += 1
            continue
        total_chunks += int(result["chunks"])
        manual_required += int(result["manual_required"])
    return {
        "videos": len(video_ids),
        "video_chunks": total_chunks,
        "manual_required": manual_required,
        "failures": failures,
    }


def build_video_review(paths: PipelinePaths | None = None) -> dict[str, int]:
    paths = paths or PipelinePaths()
    metadata_rows: list[BilibiliVideoMetadata] = []
    for path in sorted(paths.video_metadata_dir.glob("BV*.json")):
        metadata_rows.append(BilibiliVideoMetadata.model_validate_json(path.read_text(encoding="utf-8")))
    chunks = [VideoSubtitleChunk.model_validate(row) for row in read_jsonl(paths.video_chunks)]
    subtitle_lines = [
        "# Video Subtitle Review",
        "",
        "> Every item is pending. Video chunks are stored separately and never loaded by the main RAG builder.",
        "",
    ]
    for item in metadata_rows:
        item_chunks = [chunk for chunk in chunks if chunk.video_id == item.video_id]
        subtitle_lines.extend(
            [
                f"## {item.video_id} — {item.title or 'Metadata not verified'}",
                "",
                f"- classification: `{item.content_type}` / `{item.source_tier}`",
                f"- public subtitle advertised: `{item.subtitle_available}`",
                f"- metadata-only characters: `{'、'.join(item.observed_characters) or 'none'}`",
                f"- metadata-only topics: `{'、'.join(item.observed_topics) or 'none'}`",
                f"- pending chunks: `{len(item_chunks)}`",
                "- reviewer decision: `[ ] keep as secondary evidence  [ ] reject  [ ] request manual evidence`",
                "- reviewer note:",
                "",
            ]
        )
    fact_lines = [
        "# Video Fact Review",
        "",
        "> No facts or relations are automatically confirmed from video material. Co-occurrence and uploader narration are not relationship evidence.",
        "",
        "| BV | timestamp | proposed fact/relation | verbatim evidence | evidence type | corroborating Tier A source | decision |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in metadata_rows:
        fact_lines.append(f"| {item.video_id} | | | | | | pending |")
    paths.video_subtitle_review.parent.mkdir(parents=True, exist_ok=True)
    paths.video_subtitle_review.write_text("\n".join(subtitle_lines) + "\n", encoding="utf-8")
    paths.video_fact_review.write_text("\n".join(fact_lines) + "\n", encoding="utf-8")
    return {
        "videos": len(metadata_rows),
        "pending_video_chunks": len(chunks),
        "confirmed_video_facts": 0,
        "confirmed_video_relations": 0,
    }
