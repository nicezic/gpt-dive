from __future__ import annotations

import asyncio
import json
import sys

from .bare import _run_worker


def main() -> None:
    payload = json.loads(sys.stdin.read())
    result = asyncio.run(_run_worker(payload))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
