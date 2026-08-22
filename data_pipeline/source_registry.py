"""Validated source tiers and collection policy for lore inputs."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import TypeAdapter

from data_pipeline.config import PipelinePaths
from data_pipeline.schemas import SourceDefinition, SourceTier


def load_source_registry(
    path: Path | None = None,
    *,
    paths: PipelinePaths | None = None,
) -> list[SourceDefinition]:
    registry_path = path or (paths or PipelinePaths()).source_registry
    if not registry_path.exists():
        raise FileNotFoundError(f"Source registry not found: {registry_path}")
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("Source registry must contain a sources list")
    definitions = TypeAdapter(list[SourceDefinition]).validate_python(
        payload["sources"]
    )
    source_ids = [item.source_id for item in definitions]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Source registry contains duplicate source_id values")
    return definitions


def _url_matches(url: str, base_url: str) -> bool:
    target = urlsplit(url)
    base = urlsplit(base_url)
    if target.scheme not in {"http", "https"}:
        return False
    if (target.hostname or "").lower() != (base.hostname or "").lower():
        return False
    target_path = target.path.rstrip("/") or "/"
    base_path = base.path.rstrip("/") or "/"
    return target_path == base_path or target_path.startswith(base_path + "/")


def identify_source(
    definitions: list[SourceDefinition],
    *,
    url: str = "",
    source_type: str = "",
) -> SourceDefinition | None:
    if source_type:
        type_matches = [item for item in definitions if item.source_type == source_type]
        if len(type_matches) == 1:
            return type_matches[0]
    url_matches: list[tuple[int, SourceDefinition]] = []
    if url:
        for item in definitions:
            for base_url in item.base_urls:
                if _url_matches(url, base_url):
                    url_matches.append((len(base_url), item))
    if not url_matches:
        return None
    return max(url_matches, key=lambda pair: pair[0])[1]


def identify_source_tier(
    definitions: list[SourceDefinition],
    *,
    url: str = "",
    source_type: str = "",
) -> SourceTier | None:
    source = identify_source(definitions, url=url, source_type=source_type)
    return source.tier if source else None


def discovery_sources(
    definitions: list[SourceDefinition],
    source_ids: list[str],
) -> list[SourceDefinition]:
    selected: list[SourceDefinition] = []
    by_id = {item.source_id: item for item in definitions}
    for source_id in source_ids:
        source = by_id.get(source_id)
        if source is None:
            raise ValueError(f"Unknown source id: {source_id}")
        if source.tier != "A" or not source.enabled or not source.automated_collection:
            raise ValueError(f"Source is not enabled for automated Tier A discovery: {source_id}")
        selected.append(source)
    return selected
