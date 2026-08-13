# /// script
# requires-python = ">=3.14"
# dependencies = ["playwright"]
# ///
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import Browser, Page, async_playwright
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


def find_page(
    browser: Browser,
    *,
    url: str | None = None,
    url_contains: str | None = None,
) -> Page:
    if (url is None) == (url_contains is None):
        raise ValueError("provide exactly one of url or url_contains")
    pages = [page for context in browser.contexts for page in context.pages]
    if url is not None:
        matches = [page for page in pages if page.url == url]
        target = url
    else:
        assert url_contains is not None
        matches = [page for page in pages if url_contains in page.url]
        target = f"*{url_contains}*"
    if len(matches) != 1:
        urls = [page.url for page in pages]
        raise RuntimeError(
            f"expected exactly one page matching {target!r}, found {len(matches)}; "
            f"open tabs: {urls}"
        )
    return matches[0]


def page_from_request(browser: Browser, request: dict) -> Page:
    if "url" in request:
        return find_page(browser, url=str(request["url"]))
    if "url_contains" in request:
        return find_page(browser, url_contains=str(request["url_contains"]))
    raise KeyError("url or url_contains")


async def inspect_page(page: Page) -> dict:
    body = await page.locator("body").inner_text(timeout=5_000)
    links = await page.locator("a").evaluate_all(
        "els => els.map(e => ({text: (e.innerText || '').trim(), href: e.href})).filter(x => x.text || x.href)"
    )
    buttons = await page.locator("button").evaluate_all(
        "els => els.map(e => ({text: (e.innerText || '').trim(), aria: e.getAttribute('aria-label'), disabled: e.disabled}))"
    )
    inputs = await page.locator("input, textarea, select").evaluate_all(
        "els => els.map(e => ({tag: e.tagName.toLowerCase(), type: e.type || null, name: e.name || null, id: e.id || null, placeholder: e.placeholder || null, value: e.value ?? null, aria: e.getAttribute('aria-label')}))"
    )
    return {
        "url": page.url,
        "title": await page.title(),
        "body": body[:30_000],
        "links": links[:300],
        "buttons": buttons[:300],
        "inputs": inputs[:300],
    }


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    browser: Browser,
) -> None:
    try:
        raw = await reader.readline()
        request = json.loads(raw)
        action = request.get("action")
        if action == "ping":
            response = {"ok": True, "action": "pong"}
        elif action == "list_pages":
            response = {
                "ok": True,
                "pages": [
                    {"url": page.url, "title": await page.title()}
                    for context in browser.contexts
                    for page in context.pages
                ],
            }
        elif action == "inspect":
            page = page_from_request(browser, request)
            response = {"ok": True, "action": "inspect", **(await inspect_page(page))}
        elif action == "goto":
            page = page_from_request(browser, request)
            destination = str(request["destination"])
            await page.goto(destination, wait_until="domcontentloaded", timeout=20_000)
            response = {
                "ok": True,
                "action": "goto",
                "url": page.url,
                "title": await page.title(),
            }
        elif action == "click":
            page = page_from_request(browser, request)
            selector = str(request["selector"])
            await page.locator(selector).click(timeout=10_000)
            response = {"ok": True, "action": "click", "url": page.url}
        elif action == "fill":
            page = page_from_request(browser, request)
            selector = str(request["selector"])
            value = str(request["value"])
            await page.locator(selector).fill(value, timeout=10_000)
            response = {"ok": True, "action": "fill", "url": page.url}
        elif action == "eval":
            page = page_from_request(browser, request)
            expression = str(request["expression"])
            result = await page.evaluate(expression)
            response = {"ok": True, "action": "eval", "url": page.url, "result": result}
        elif action == "capture":
            page = page_from_request(browser, request)
            captured = []

            async def on_response(resp):
                if resp.request.resource_type in {"xhr", "fetch"}:
                    item = {"url": resp.url, "status": resp.status}
                    try:
                        ct = (await resp.all_headers()).get("content-type", "")
                        if "json" in ct:
                            item["body"] = (await resp.text())[:12_000]
                    except PlaywrightError as exc:
                        item["body_error"] = f"{type(exc).__name__}: {exc}"
                    captured.append(item)

            page.on("response", on_response)
            await page.reload(wait_until="domcontentloaded", timeout=15_000)
            await asyncio.sleep(2)
            page.remove_listener("response", on_response)
            response = {
                "ok": True,
                "action": "capture",
                "url": page.url,
                "responses": captured,
            }
        elif action == "send":
            page = page_from_request(browser, request)
            message = str(request["message"])
            composer = page.locator("#prompt-textarea")
            await composer.wait_for(state="visible", timeout=5_000)
            await composer.fill(message)
            await composer.press("Enter")
            response = {"ok": True, "action": "send", "url": page.url}
        else:
            raise ValueError(f"unknown action: {action}")
    except (KeyError, RuntimeError, ValueError, PlaywrightError) as exc:
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode())
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persistent Edge CDP bridge for browser automation."
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/tmp/gpt-dive-council-edge.sock"),
    )
    parser.add_argument("--devtools-active-port", type=Path, default=None)
    args = parser.parse_args()

    active_port = args.devtools_active_port or find_devtools_active_port()
    endpoint = read_endpoint(active_port)
    socket_path = args.socket
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint, no_defaults=True)
        server = await asyncio.start_unix_server(
            lambda r, w: handle_client(r, w, browser),
            path=str(socket_path),
        )
        os.chmod(socket_path, 0o600)
        print(f"BRIDGE_READY\t{socket_path}\t{endpoint}", flush=True)
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
