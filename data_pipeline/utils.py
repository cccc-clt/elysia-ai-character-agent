"""Shared deterministic and filesystem helpers for the pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from data_pipeline.config import BLOCKED_PATH_PARTS


TRACKING_QUERY_KEYS = {
    "from",
    "source",
    "spm",
    "timestamp",
    "share_code",
    "share_from",
}

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "sign",
    "signature",
    "token",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: str, length: int = 20) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Normalize public URLs while retaining unknown route parameters."""

    absolute = urljoin(base_url, url) if base_url else url
    parts = urlsplit(absolute.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return ""
    try:
        port = parts.port
    except ValueError:
        return ""
    netloc = host
    if port and not (scheme == "http" and port == 80) and not (
        scheme == "https" and port == 443
    ):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if (
            lowered.startswith("utm_")
            or lowered in TRACKING_QUERY_KEYS
            or lowered in SENSITIVE_QUERY_KEYS
        ):
            continue
        query_pairs.append((key, value))
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def is_allowed_url(
    url: str,
    allowed_path_prefixes: dict[str, tuple[str, ...]],
) -> bool:
    normalized = normalize_url(url)
    if not normalized:
        return False
    parts = urlsplit(normalized)
    host = (parts.hostname or "").lower()
    prefixes = allowed_path_prefixes.get(host)
    if not prefixes:
        return False
    lowered_path = parts.path.lower()
    if any(part in lowered_path for part in BLOCKED_PATH_PARTS):
        return False
    return any(
        lowered_path == prefix.lower().rstrip("/")
        or lowered_path.startswith(prefix.lower().rstrip("/") + "/")
        for prefix in prefixes
    )


def compact_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = re.sub(r"[\t\f\v ]+", " ", raw_line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines).strip()


def effective_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row must be an object at {path}:{line_number}")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def upsert_jsonl(path: Path, row: dict[str, Any], key: str) -> bool:
    """Insert or replace one JSONL row; return False for an identical rerun."""

    rows = read_jsonl(path)
    target = row.get(key)
    changed = True
    for index, existing in enumerate(rows):
        if existing.get(key) != target:
            continue
        if existing == row:
            return False
        rows[index] = row
        break
    else:
        rows.append(row)
    write_jsonl(path, rows)
    return changed


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def safe_filename(value: str, fallback: str = "document") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-_")
    return (cleaned[:80] or fallback).lower()


def redact_sensitive(value: Any) -> Any:
    sensitive = {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "cookie",
        "set-cookie",
    }
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if key.lower() in sensitive else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value
