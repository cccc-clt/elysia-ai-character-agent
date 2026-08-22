"""Low-rate, resumable crawler for allowlisted public official pages."""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from data_pipeline.config import CrawlSettings, PipelinePaths, SCOPE_KEYWORDS
from data_pipeline.extractor import ExtractedPage, extract_html
from data_pipeline.renderer import PlaywrightRenderer, RenderUnavailableError
from data_pipeline.schemas import CandidateAuditRecord, CrawlRecord, PageDocument
from data_pipeline.utils import (
    content_hash,
    effective_text_length,
    is_allowed_url,
    normalize_url,
    read_json,
    read_jsonl,
    stable_id,
    upsert_jsonl,
    utc_now,
    write_json,
)


CAPTCHA_MARKERS = (
    "验证码",
    "人机验证",
    "安全验证",
    "captcha",
    "verify you are human",
)


class DomainHaltedError(RuntimeError):
    def __init__(self, domain: str, reason: str) -> None:
        super().__init__(reason)
        self.domain = domain
        self.reason = reason


class FetchError(RuntimeError):
    pass


def _source_type(domain: str) -> str:
    if domain == "baike.mihoyo.com":
        return "official_wiki"
    if domain == "comic.bh3.com":
        return "official_comic"
    return "official_site"


def _read_seed_urls(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            urls.append(stripped)
    return urls


class OfficialLoreCrawler:
    def __init__(
        self,
        settings: CrawlSettings,
        paths: PipelinePaths | None = None,
        *,
        client: httpx.Client | None = None,
        renderer: PlaywrightRenderer | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.paths = paths or PipelinePaths()
        self.paths.ensure_runtime_dirs()
        self._owns_client = client is None
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=settings.timeout_seconds,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.5",
                "Accept-Language": "zh-CN,zh;q=0.9",
                # Some official endpoints advertise a broken compressed
                # robots.txt response. Identity encoding keeps the compliance
                # check readable without bypassing any access rule.
                "Accept-Encoding": "identity",
            },
        )
        self.renderer = renderer
        if renderer is None and settings.render_dynamic:
            self.renderer = PlaywrightRenderer(
                settings.user_agent, settings.timeout_seconds
            )
        self._last_request_at = 0.0
        self._robots_cache: dict[str, RobotFileParser | bool] = {}
        self._halted_domains: dict[str, str] = {}
        self.logger = self._build_logger()
        self.manifest = self._load_manifest()

    def _build_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"data_pipeline.crawler.{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = logging.FileHandler(self.paths.log, encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(handler)
        return logger

    def _load_manifest(self) -> dict[str, Any]:
        default = {
            "scope": self.settings.scope,
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "settings": {},
            "discovered_urls": [],
            "records": [],
        }
        manifest = read_json(self.paths.manifest, default)
        if manifest.get("scope") != self.settings.scope:
            return default
        manifest.setdefault("discovered_urls", [])
        manifest.setdefault("records", [])
        return manifest

    def _save_manifest(self) -> None:
        self.manifest["updated_at"] = utc_now()
        self.manifest["settings"] = {
            "scope": self.settings.scope,
            "max_pages": self.settings.max_pages,
            "delay_seconds": self.settings.delay_seconds,
            "concurrency": self.settings.concurrency,
            "timeout_seconds": self.settings.timeout_seconds,
            "max_retries": self.settings.max_retries,
            "user_agent": self.settings.user_agent,
            "render_dynamic": self.settings.render_dynamic,
        }
        self.manifest["summary"] = self.status()
        write_json(self.paths.manifest, self.manifest)

    def _record(
        self,
        url: str,
        status: str,
        reason: str = "",
        document_id: str = "",
        digest: str = "",
    ) -> None:
        record = CrawlRecord(
            url=url,
            status=status,
            reason=reason[:500],
            document_id=document_id,
            content_hash=digest,
            recorded_at=utc_now(),
        ).model_dump(mode="json")
        records = self.manifest.setdefault("records", [])
        for index, existing in enumerate(records):
            if existing.get("url") == url:
                records[index] = record
                break
        else:
            records.append(record)
        self.logger.info("crawl status=%s url=%s reason=%s", status, url, reason)
        self._save_manifest()

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.settings.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _get(self, url: str) -> httpx.Response:
        last_error = ""
        for attempt in range(self.settings.max_retries + 1):
            self._wait_for_rate_limit()
            try:
                response = self.client.get(url)
            except httpx.HTTPError as exc:
                last_error = f"network_error:{type(exc).__name__}"
                if attempt < self.settings.max_retries:
                    continue
                raise FetchError(last_error) from exc
            domain = (response.url.host or urlsplit(url).hostname or "").lower()
            if response.status_code in {403, 429}:
                raise DomainHaltedError(domain, f"http_{response.status_code}")
            if response.status_code >= 500 and attempt < self.settings.max_retries:
                last_error = f"http_{response.status_code}"
                continue
            if response.status_code >= 400:
                raise FetchError(f"http_{response.status_code}")
            return response
        raise FetchError(last_error or "request_failed")

    def _robots_allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        domain = (parts.hostname or "").lower()
        cached = self._robots_cache.get(domain)
        if cached is False:
            return False, "robots_unavailable"
        if isinstance(cached, RobotFileParser):
            return cached.can_fetch("ElysiaLoreResearchBot", url), "robots_txt"

        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response = self._get(robots_url)
        except FetchError as exc:
            if "http_404" in str(exc):
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse([])
                self._robots_cache[domain] = parser
                return True, "robots_not_found"
            self._robots_cache[domain] = False
            return False, f"robots_check_failed:{exc}"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        self._robots_cache[domain] = parser
        allowed = parser.can_fetch("ElysiaLoreResearchBot", url)
        return allowed, "robots_txt"

    def _fetch_and_extract(
        self,
        url: str,
        *,
        accept_insufficient: bool = False,
    ) -> tuple[ExtractedPage, str, int]:
        response = self._get(url)
        final_url = normalize_url(str(response.url))
        if not is_allowed_url(final_url, self.settings.allowed_path_prefixes):
            raise FetchError("redirected_outside_allowlist")
        length_header = response.headers.get("content-length", "")
        if length_header.isdigit() and int(length_header) > self.settings.max_response_bytes:
            raise FetchError("response_too_large")
        body = response.text
        if len(body.encode("utf-8")) > self.settings.max_response_bytes:
            raise FetchError("response_too_large")
        lowered = body.lower()
        if any(marker in lowered for marker in CAPTCHA_MARKERS):
            domain = urlsplit(final_url).hostname or ""
            raise DomainHaltedError(domain, "captcha_or_access_challenge")
        extracted = extract_html(body, final_url)
        if not extracted.needs_dynamic_render:
            return extracted, final_url, response.status_code
        if not self.settings.render_dynamic or self.renderer is None:
            raise FetchError("dynamic_render_required_but_disabled")
        self._wait_for_rate_limit()
        try:
            rendered_html = self.renderer.render(final_url)
        except RenderUnavailableError as exc:
            raise FetchError(f"renderer_unavailable:{exc}") from exc
        lowered_rendered = rendered_html.lower()
        if any(marker in lowered_rendered for marker in CAPTCHA_MARKERS):
            domain = urlsplit(final_url).hostname or ""
            raise DomainHaltedError(domain, "captcha_or_access_challenge")
        rendered = extract_html(rendered_html, final_url)
        if rendered.needs_dynamic_render and not accept_insufficient:
            raise FetchError(
                f"insufficient_content:{effective_text_length(rendered.content)}_chars"
            )
        return rendered, final_url, response.status_code

    def inspect_public_url(self, url: str) -> dict[str, Any]:
        """Fetch one allowlisted public page for metadata audit without persisting body."""

        normalized = normalize_url(url)
        if not is_allowed_url(normalized, self.settings.allowed_path_prefixes):
            return {
                "url": normalized or url,
                "metadata_status": "failed",
                "reason": "outside_allowlist_or_blocked_path",
            }
        domain = (urlsplit(normalized).hostname or "").lower()
        if domain in self._halted_domains:
            return {
                "url": normalized,
                "metadata_status": "failed",
                "reason": f"domain_halted:{self._halted_domains[domain]}",
            }
        try:
            allowed, robots_reason = self._robots_allowed(normalized)
        except DomainHaltedError as exc:
            self._halted_domains[exc.domain] = exc.reason
            return {
                "url": normalized,
                "metadata_status": "failed",
                "reason": f"domain_halted:{exc.reason}",
            }
        if not allowed:
            return {
                "url": normalized,
                "metadata_status": (
                    "robots_disallowed"
                    if robots_reason == "robots_txt"
                    else "failed"
                ),
                "reason": robots_reason,
            }
        try:
            extracted, final_url, http_status = self._fetch_and_extract(
                normalized, accept_insufficient=True
            )
        except DomainHaltedError as exc:
            self._halted_domains[exc.domain] = exc.reason
            return {
                "url": normalized,
                "metadata_status": "failed",
                "reason": f"domain_halted:{exc.reason}",
            }
        except FetchError as exc:
            return {
                "url": normalized,
                "metadata_status": "failed",
                "reason": str(exc),
            }
        return {
            "url": normalized,
            "metadata_status": (
                "insufficient_content"
                if extracted.needs_dynamic_render
                else "success"
            ),
            "reason": (
                f"insufficient_content:{effective_text_length(extracted.content)}_chars"
                if extracted.needs_dynamic_render
                else ""
            ),
            "title": extracted.title,
            "content": extracted.content,
            "final_url": final_url,
            "http_status": http_status,
            "links": [
                {"url": link.url, "label": link.label}
                for link in extracted.links
            ],
        }

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _link_matches_scope(self, label: str, url: str) -> bool:
        haystack = f"{label} {url}".lower()
        return any(
            keyword.lower() in haystack
            for keyword in SCOPE_KEYWORDS[self.settings.scope]
        )

    def _audited_include_urls(self) -> list[str] | None:
        if not self.paths.candidate_audit_jsonl.exists():
            return None
        records: list[CandidateAuditRecord] = []
        for row in read_jsonl(self.paths.candidate_audit_jsonl):
            try:
                record = CandidateAuditRecord.model_validate(row)
            except ValueError:
                continue
            if record.decision == "include":
                records.append(record)
        records.sort(key=lambda record: record.crawl_priority)
        return [normalize_url(record.url) for record in records]

    def _discover_from(self, extracted: ExtractedPage, queue: deque[str]) -> None:
        discovered = self.manifest.setdefault("discovered_urls", [])
        known = set(discovered)
        known.update(queue)
        for link in extracted.links:
            if not is_allowed_url(link.url, self.settings.allowed_path_prefixes):
                continue
            if not self._link_matches_scope(link.label, link.url):
                continue
            if link.url in known:
                continue
            discovered.append(link.url)
            queue.append(link.url)
            known.add(link.url)

    def dry_run(self, seed_path: Path | None = None) -> dict[str, Any]:
        audited = self._audited_include_urls()
        seeds = (
            audited
            if audited is not None
            else _read_seed_urls(seed_path or self.paths.seeds)
        )
        accepted: list[str] = []
        rejected: list[dict[str, str]] = []
        for seed in seeds:
            normalized = normalize_url(seed)
            if is_allowed_url(normalized, self.settings.allowed_path_prefixes):
                accepted.append(normalized)
            else:
                rejected.append({"url": seed, "reason": "outside_allowlist"})
        if audited is None:
            for url in self.manifest.get("discovered_urls", []):
                normalized = normalize_url(str(url))
                if (
                    normalized
                    and normalized not in accepted
                    and is_allowed_url(normalized, self.settings.allowed_path_prefixes)
                ):
                    accepted.append(normalized)
        return {
            "dry_run": True,
            "scope": self.settings.scope,
            "candidate_source": (
                "candidate_audit_include" if audited is not None else "seed_and_discovery"
            ),
            "accepted_count": len(accepted[: self.settings.max_pages]),
            "accepted_urls": accepted[: self.settings.max_pages],
            "rejected": rejected,
            "network_requests": 0,
        }

    def crawl(self, seed_path: Path | None = None) -> dict[str, Any]:
        audited = self._audited_include_urls()
        seeds = (
            audited
            if audited is not None
            else _read_seed_urls(seed_path or self.paths.seeds)
        )
        discovered = [str(item) for item in self.manifest.get("discovered_urls", [])]
        initial = seeds if audited is not None else seeds + discovered
        queue: deque[str] = deque()
        queued: set[str] = set()
        for raw_url in initial:
            url = normalize_url(raw_url)
            if not url or url in queued:
                continue
            queued.add(url)
            queue.append(url)
        if audited is None:
            self.manifest["discovered_urls"] = list(queue)

        records_by_url = {
            str(record.get("url")): record
            for record in self.manifest.get("records", [])
        }
        # Transient skips (for example an unavailable robots.txt or a domain
        # halted earlier in the same run) must be eligible for a later retry.
        terminal = {"success", "duplicate", "robots_disallowed"}
        raw_rows = read_jsonl(self.paths.raw_documents)
        known_hashes = {
            str(row.get("content_hash")): str(row.get("document_id"))
            for row in raw_rows
            if row.get("content_hash")
        }
        attempted_this_run = 0
        recorded_urls = set(records_by_url)

        try:
            while queue and attempted_this_run < self.settings.max_pages:
                url = queue.popleft()
                prior = records_by_url.get(url, {})
                if prior.get("status") in terminal:
                    continue
                if url not in recorded_urls and len(recorded_urls) >= self.settings.max_pages:
                    break
                recorded_urls.add(url)
                attempted_this_run += 1
                if not is_allowed_url(url, self.settings.allowed_path_prefixes):
                    self._record(url, "skipped", "outside_allowlist_or_blocked_path")
                    continue
                domain = (urlsplit(url).hostname or "").lower()
                if domain in self._halted_domains:
                    self._record(
                        url,
                        "skipped",
                        f"domain_halted:{self._halted_domains[domain]}",
                    )
                    continue
                try:
                    allowed, robots_reason = self._robots_allowed(url)
                except DomainHaltedError as exc:
                    self._halted_domains[exc.domain] = exc.reason
                    self._record(url, "failed", f"domain_halted:{exc.reason}")
                    continue
                if not allowed:
                    status = (
                        "robots_disallowed"
                        if robots_reason == "robots_txt"
                        else "failed"
                    )
                    self._record(url, status, robots_reason)
                    continue
                try:
                    extracted, fetched_url, _ = self._fetch_and_extract(url)
                except DomainHaltedError as exc:
                    self._halted_domains[exc.domain] = exc.reason
                    self._record(url, "failed", f"domain_halted:{exc.reason}")
                    continue
                except FetchError as exc:
                    self._record(url, "failed", str(exc))
                    continue

                canonical = normalize_url(extracted.canonical_url or fetched_url)
                if not is_allowed_url(canonical, self.settings.allowed_path_prefixes):
                    canonical = fetched_url
                digest = content_hash(extracted.content)
                duplicate_of = known_hashes.get(digest)
                if duplicate_of:
                    self._record(
                        url,
                        "duplicate",
                        f"same_content_as:{duplicate_of}",
                        duplicate_of,
                        digest,
                    )
                    if audited is None:
                        self._discover_from(extracted, queue)
                    continue
                document_id = stable_id("doc", canonical)
                document = PageDocument(
                    document_id=document_id,
                    title=extracted.title,
                    canonical_url=canonical,
                    source_domain=urlsplit(canonical).hostname or domain,
                    source_type=_source_type(domain),
                    content=extracted.content,
                    content_hash=digest,
                    retrieved_at=utc_now(),
                )
                upsert_jsonl(
                    self.paths.raw_documents,
                    document.model_dump(mode="json"),
                    "document_id",
                )
                known_hashes[digest] = document_id
                if audited is None:
                    self._discover_from(extracted, queue)
                self._record(url, "success", "", document_id, digest)
        finally:
            self.manifest["discovered_urls"] = list(dict.fromkeys(
                [*self.manifest.get("discovered_urls", []), *queue]
            ))
            self._save_manifest()
            self.close()
        return self.status()

    def status(self) -> dict[str, int]:
        records = self.manifest.get("records", [])
        counts = {
            "discovered": len(set(self.manifest.get("discovered_urls", []))),
            "success": 0,
            "skipped": 0,
            "robots_disallowed": 0,
            "failed": 0,
            "duplicate": 0,
        }
        for record in records:
            status = str(record.get("status", ""))
            if status in counts:
                counts[status] += 1
        return counts
