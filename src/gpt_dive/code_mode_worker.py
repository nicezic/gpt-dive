from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .app import CODE_MODE_WORKER_PROTOCOL, _build_code_registry, code_runtime


def _emit(envelope: dict[str, Any]) -> None:
    text = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def _run(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("v") != CODE_MODE_WORKER_PROTOCOL:
        raise ValueError("unsupported Code Mode worker request protocol version")
    code = request.get("code")
    cwd = request.get("cwd")
    payload = request.get("payload")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("worker request requires non-empty code")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("worker cwd must be a string or null")
    if payload is not None and not isinstance(payload, str):
        raise ValueError("worker payload must be a string or null")
    return await code_runtime.run(
        code,
        _build_code_registry(cwd),
        cwd=cwd,
        payload=payload,
        background=True,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: code_mode_worker.py <request.json>")
    request_path = Path(sys.argv[1])
    try:
        request = json.loads(request_path.read_text())
    finally:
        request_path.unlink(missing_ok=True)

    try:
        result = asyncio.run(_run(request))
        try:
            _emit({"v": CODE_MODE_WORKER_PROTOCOL, "ok": True, "result": result})
        except (TypeError, ValueError) as exc:
            _emit(
                {
                    "v": CODE_MODE_WORKER_PROTOCOL,
                    "ok": False,
                    "error": {
                        "code": "non_json_result",
                        "message": f"Code Mode result is not strict JSON: {exc}",
                    },
                }
            )
            raise SystemExit(1) from exc
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit(
            {
                "v": CODE_MODE_WORKER_PROTOCOL,
                "ok": False,
                "error": {
                    "code": "background_execution_error",
                    "message": str(exc) or type(exc).__name__,
                },
            }
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
