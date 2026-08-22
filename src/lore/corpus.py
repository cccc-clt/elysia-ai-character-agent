"""Load isolated lore corpora from local, Git-ignored pipeline outputs."""

from __future__ import annotations

import json
import re
import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.config import PROJECT_ROOT, LoreRAGConfig
from src.lore.models import CorpusName, LoreChunk


CORPUS_PATHS: dict[CorpusName, Path] = {
    "official_lore": PROJECT_ROOT / "data" / "chunks" / "elysia_lore_chunks.jsonl",
    "bh3text_dialogue": PROJECT_ROOT / "data" / "chunks" / "bh3text_lore_chunks.jsonl",
    "story_navigation": PROJECT_ROOT / "data" / "story_guide" / "story_navigation_chunks.jsonl",
}

SOURCE_PRECEDENCE = {
    "A": 0,
    "A-manual": 1,
    "Tier B-primary-transcript": 2,
    "B-recording": 3,
    "Tier B-curated-index": 4,
    "B": 5,
    "C": 6,
    "pending": 7,
}

_IGNORED_SOURCE_QUERY_KEYS = {"from", "source", "spm", "timestamp"}


def canonical_source_url(value: str) -> str:
    if value.startswith("manual-official://"):
        return value
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return value
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return value
    netloc = host if not port or port == 443 else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in _IGNORED_SOURCE_QUERY_KEYS
        ),
        doseq=True,
    )
    return urlunparse(("https", netloc, path, "", query, ""))


def normalized_content_hash(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", "", normalized)
    return sha256(normalized.encode("utf-8")).hexdigest()


def is_safe_source_url(value: str) -> bool:
    if value.startswith("manual-official://"):
        return True
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _official_chunk(row: dict[str, Any]) -> LoreChunk | None:
    metadata = row.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    source_url = canonical_source_url(str(metadata.get("source_url", "")))
    if not is_safe_source_url(source_url):
        return None
    return LoreChunk(
        chunk_id=str(row.get("chunk_id", "")),
        document_id=str(metadata.get("document_id", "")),
        corpus="official_lore",
        content=str(row.get("content", "")),
        title=str(metadata.get("title", "")),
        source_url=source_url,
        source_type=str(metadata.get("source_type", "")),
        source_tier=str(metadata.get("source_tier", "A")),
        review_status="accepted",
        character_names=tuple(str(value) for value in metadata.get("entity_names", [])),
    )


def _bh3text_chunk(row: dict[str, Any]) -> LoreChunk | None:
    source_url = canonical_source_url(str(row.get("source_url", "")))
    if not source_url.startswith("https://www.bh3text.com/dialog/"):
        return None
    return LoreChunk(
        chunk_id=str(row.get("chunk_id", "")),
        document_id=str(row.get("document_id", "")),
        corpus="bh3text_dialogue",
        content=str(row.get("content", "")),
        title=str(row.get("title", "")),
        source_url=source_url,
        source_type=str(row.get("source_type", "community_game_text_archive")),
        source_tier=str(row.get("source_tier", "Tier B-primary-transcript")),
        review_status=str(row.get("review_status", "unverified_transcript")),
        chapter=str(row.get("chapter", "")),
        scene=str(row.get("scene", "")),
        character_names=tuple(str(value) for value in row.get("character_names", [])),
        topic_names=tuple(str(value) for value in row.get("topic_names", [])),
    )


def _navigation_chunk(row: dict[str, Any]) -> LoreChunk | None:
    source_url = canonical_source_url(str(row.get("source_url", "")))
    if not source_url.startswith("https://bh3helper.xrysnow.xyz/"):
        return None
    return LoreChunk(
        chunk_id=str(row.get("chunk_id", "")),
        document_id=str(row.get("navigation_id", "")),
        corpus="story_navigation",
        content=str(row.get("content", "")),
        title=str(row.get("title", "")),
        source_url=source_url,
        source_type=str(row.get("source_type", "community_story_guide")),
        source_tier=str(row.get("source_tier", "Tier B-curated-index")),
        review_status=str(row.get("review_status", "pending")),
    )


class LoreCorpus:
    """Deep module for source-safe loading, filtering, and exact deduplication."""

    def __init__(
        self,
        config: LoreRAGConfig,
        *,
        corpus_paths: dict[CorpusName, Path] | None = None,
    ) -> None:
        self._config = config
        self._paths = corpus_paths or CORPUS_PATHS
        self._cache: dict[
            tuple[CorpusName, ...], tuple[tuple[LoreChunk, ...], tuple[str, ...]]
        ] = {}

    def load(self, corpora: Iterable[CorpusName]) -> tuple[list[LoreChunk], list[str]]:
        requested = list(dict.fromkeys(corpora))
        cache_key = tuple(requested)
        if cache_key in self._cache:
            cached_chunks, cached_warnings = self._cache[cache_key]
            return list(cached_chunks), list(cached_warnings)
        warnings: list[str] = []
        chunks: list[LoreChunk] = []
        for corpus in requested:
            path = self._paths[corpus]
            if not path.exists():
                warnings.append(f"missing_corpus:{corpus}")
                continue
            if corpus == "official_lore":
                parsed = (_official_chunk(row) for row in _read_jsonl(path))
            elif corpus == "bh3text_dialogue":
                if not (
                    self._config.prototype_mode
                    and self._config.allow_unverified_transcripts
                ):
                    warnings.append("unverified_transcripts_disabled")
                    continue
                parsed = (_bh3text_chunk(row) for row in _read_jsonl(path))
            else:
                parsed = (_navigation_chunk(row) for row in _read_jsonl(path))
            chunks.extend(row for row in parsed if row and row.chunk_id and row.content)

        deduplicated: dict[str, LoreChunk] = {}
        hashes: dict[str, str] = {}
        for chunk in sorted(
            chunks,
            key=lambda row: (SOURCE_PRECEDENCE.get(row.source_tier, 99), row.chunk_id),
        ):
            digest = normalized_content_hash(chunk.content)
            if chunk.chunk_id in deduplicated or digest in hashes:
                continue
            deduplicated[chunk.chunk_id] = chunk
            hashes[digest] = chunk.chunk_id
        result = list(deduplicated.values())
        self._cache[cache_key] = (tuple(result), tuple(warnings))
        return result, warnings

    @staticmethod
    def signature(chunks: Iterable[LoreChunk]) -> str:
        value = "\n".join(
            sorted(
                ":".join(
                    (
                        row.chunk_id,
                        row.title,
                        row.chapter,
                        row.scene,
                        "|".join(row.character_names),
                        "|".join(row.topic_names),
                        sha256(row.content.encode("utf-8")).hexdigest(),
                    )
                )
                for row in chunks
            )
        )
        return sha256(value.encode("utf-8")).hexdigest()
