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


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, browser: Browser) -> None:
    try:
        raw = await reader.readline()
        request = json.loads(raw)
        action = request.get("action")
        if action == "ping":
            response = {"ok": True, "action": "pong"}
        elif action == "send":
            url = str(request["url"])
            message = str(request["message"])
            page = find_page(browser, url)
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
    parser = argparse.ArgumentParser(description="Persistent Edge CDP bridge for Council input.")
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
