from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


async def _request(socket_path: Path, payload: dict[str, str]) -> dict[str, object]:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
    await writer.drain()
    response = json.loads(await reader.readline())
    writer.close()
    await writer.wait_closed()
    return response


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Send one message through the persistent Council Edge bridge."
    )
    parser.add_argument("--url", required=True, help="Exact ChatGPT conversation URL")
    parser.add_argument("--message", required=True, help="Message to send")
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/tmp/gpt-dive-council-edge.sock"),
    )
    args = parser.parse_args()

    result = await _request(
        args.socket,
        {"action": "send", "url": args.url, "message": args.message},
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error")))
    print(f"SEND_OK\t{result['url']}")


if __name__ == "__main__":
    asyncio.run(_main())
