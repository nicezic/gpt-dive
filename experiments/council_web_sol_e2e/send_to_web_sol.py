# /// script
# requires-python = ">=3.14"
# dependencies = ["playwright"]
# ///
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


def _find_devtools_active_port() -> Path:
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


def _read_endpoint(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"invalid DevToolsActivePort file: {path}")
    port = lines[0].strip()
    websocket_path = lines[1].strip()
    return f"ws://127.0.0.1:{port}{websocket_path}"


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Send one message to an already-open ChatGPT Web SOL tab via Edge CDP."
    )
    parser.add_argument("--url", required=True, help="Exact ChatGPT conversation URL")
    parser.add_argument("--message", required=True, help="Message to send")
    parser.add_argument(
        "--devtools-active-port",
        type=Path,
        default=None,
        help="Optional Edge DevToolsActivePort file path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Attach and resolve the target tab without sending input",
    )
    args = parser.parse_args()

    active_port = args.devtools_active_port or _find_devtools_active_port()
    endpoint = _read_endpoint(active_port)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(
            endpoint,
            no_defaults=True,
        )
        matches = [
            page
            for context in browser.contexts
            for page in context.pages
            if page.url == args.url
        ]
        if len(matches) != 1:
            urls = [page.url for context in browser.contexts for page in context.pages]
            raise RuntimeError(
                f"expected exactly one target ChatGPT tab, found {len(matches)}; "
                f"open tabs: {urls}"
            )

        page = matches[0]
        if args.dry_run:
            print(f"DRY_RUN_OK\t{await page.title()}\t{page.url}")
            return

        composer = page.locator("#prompt-textarea")
        await composer.wait_for(state="visible", timeout=5_000)
        await composer.fill(args.message)
        await composer.press("Enter")
        print(f"SEND_OK\t{page.url}")


if __name__ == "__main__":
    asyncio.run(_main())
