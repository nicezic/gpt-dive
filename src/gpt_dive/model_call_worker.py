from __future__ import annotations

import asyncio
import json
import sys

from pydantic_ai.exceptions import AgentRunError, ModelHTTPError

from .model_call import _run_worker


def main() -> None:
    payload = json.loads(sys.stdin.read())
    try:
        result = asyncio.run(_run_worker(payload))
    except AgentRunError as exc:
        error: dict[str, str | int] = {
            "category": "model",
            "code": type(exc).__name__,
            "message": "Model invocation failed.",
            "recovery": "inspect_first",
        }
        if isinstance(exc, ModelHTTPError):
            error["http_status"] = exc.status_code
        result = {"ok": False, "error": error}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
