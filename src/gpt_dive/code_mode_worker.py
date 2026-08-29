from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .code_capabilities import build_code_registry, code_runtime
from .command_runtime import runtime_record
from .execution_store import ExecutionStore
from .code_mode_protocol import CODE_MODE_WORKER_PROTOCOL


def _emit(envelope: dict[str, Any]) -> None:
    text = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def _run(
    request: dict[str, Any], *, record: dict[str, object]
) -> dict[str, Any]:
    if request.get("v") != CODE_MODE_WORKER_PROTOCOL:
        raise ValueError("unsupported Code Mode Worker request protocol version")
    code = request.get("code")
    cwd = request.get("cwd")
    payload = request.get("payload")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Worker request requires non-empty code")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Worker cwd must be a string or null")
    if payload is not None and not isinstance(payload, str):
        raise ValueError("Worker payload must be a string or null")
    return await code_runtime.run(
        code,
        build_code_registry(cwd, record=record),
        cwd=cwd,
        payload=payload,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--execution", required=True)
    parser.add_argument("--request", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        request = json.loads(args.request.read_text())
    finally:
        args.request.unlink(missing_ok=True)

    store = ExecutionStore(args.store)
    record = runtime_record(store.get(args.execution))
    try:
        result = asyncio.run(_run(request, record=record))
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
                    "code": "execution_error",
                    "message": str(exc) or type(exc).__name__,
                },
            }
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
