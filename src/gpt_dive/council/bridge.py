from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any, Self

from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError


def find_devtools_active_port() -> Path:
    candidates = sorted(
        Path("/mnt/c/Users").glob(
            "*/AppData/Local/Microsoft/Edge/User Data/DevToolsActivePort"
        )
    )
    if len(candidates) != 1:
        rendered = ", ".join(map(str, candidates)) or "none"
        raise RuntimeError(
            "expected exactly one Edge DevToolsActivePort file; "
            f"found {len(candidates)}: {rendered}"
        )
    return candidates[0]


def read_endpoint(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"invalid DevToolsActivePort file: {path}")
    return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}"


def find_page(browser: Browser, url: str) -> Page:
    matches = [
        page
        for context in browser.contexts
        for page in context.pages
        if page.url == url
    ]
    if len(matches) != 1:
        urls = [page.url for context in browser.contexts for page in context.pages]
        raise RuntimeError(
            f"expected exactly one target ChatGPT tab, found {len(matches)}; "
            f"open tabs: {urls}"
        )
    return matches[0]


class SolBridge:
    """Persistent input-only connection to the user's existing Web SOL tab."""

    def __init__(self, devtools_active_port: str | Path | None = None) -> None:
        self._active_port = (
            Path(devtools_active_port).expanduser().resolve()
            if devtools_active_port is not None
            else None
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def started(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def start(self) -> None:
        if self.started:
            return
        active_port = self._active_port or find_devtools_active_port()
        endpoint = read_endpoint(active_port)
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(
                endpoint,
                no_defaults=True,
            )
        except Exception:
            await playwright.stop()
            raise
        self._playwright = playwright
        self._browser = browser

    async def close(self) -> None:
        # Stopping Playwright disconnects this client. Do not call browser.close(),
        # which could close the user's already-running Edge instance.
        playwright = self._playwright
        self._playwright = None
        self._browser = None
        if playwright is not None:
            await playwright.stop()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        browser = self._browser
        if browser is None or not browser.is_connected():
            raise RuntimeError("SOL bridge is not started")
        try:
            page = find_page(browser, url)
            composer = page.locator("#prompt-textarea")
            await composer.wait_for(state="visible", timeout=5_000)
            await composer.fill(message)
            await composer.press("Enter")
        except PlaywrightError as exc:
            raise RuntimeError(f"SOL browser input failed: {exc}") from exc
        return {"ok": True, "url": page.url}
