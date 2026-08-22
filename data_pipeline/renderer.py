"""Optional Playwright fallback for JavaScript-rendered public pages."""

from __future__ import annotations

import re
import time


class RenderUnavailableError(RuntimeError):
    """Raised when Playwright or its Chromium binary is unavailable."""


class PlaywrightRenderer:
    def __init__(self, user_agent: str, timeout_seconds: float = 20.0) -> None:
        self.user_agent = user_agent
        self.timeout_ms = int(timeout_seconds * 1000)

    def render(self, url: str) -> str:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RenderUnavailableError(
                "Playwright is not installed; see data_pipeline/README.md"
            ) from exc

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()

                def block_binary_assets(route: object) -> None:
                    resource_type = route.request.resource_type  # type: ignore[attr-defined]
                    if resource_type in {"image", "media", "font"}:
                        route.abort()  # type: ignore[attr-defined]
                    else:
                        route.continue_()  # type: ignore[attr-defined]

                page.route("**/*", block_binary_assets)
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                deadline = time.monotonic() + min(8.0, self.timeout_ms / 1000)
                while time.monotonic() < deadline:
                    page.wait_for_timeout(500)
                    try:
                        visible_text = page.locator("body").inner_text(timeout=1_500)
                    except PlaywrightError:
                        continue
                    if len(re.sub(r"\s+", "", visible_text)) >= 200:
                        break
                html = page.content()
                context.close()
                browser.close()
                return html
        except PlaywrightError as exc:
            raise RenderUnavailableError(
                "Playwright Chromium is unavailable or the public page timed out"
            ) from exc
