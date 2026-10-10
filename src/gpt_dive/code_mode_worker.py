from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from pydantic_monty import MontyError, MontyTypingError

from .code_capabilities import build_code_registry, code_runtime
from .code_mode_errors import WORKER_ERROR_MESSAGES, category_for, recovery_for
from .code_mode_protocol import CODE_MODE_WORKER_PROTOCOL
from .command_runtime import RuntimeRecord, runtime_record
from .execution_store import ExecutionStore


def _emit(envelope: dict[str, Any]) -> None:
    text = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def _run(request: dict[str, Any], *, record: RuntimeRecord) -> Any:
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


def _emit_error(
    code: str,
    detail: str,
    *,
    category: str | None = None,
    recovery: str | None = None,
    message: str | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    store: ExecutionStore | None = None,
    execution_id: str | None = None,
) -> None:
    error: dict[str, Any] = {
        "category": category or category_for(code),
        "code": code,
        "message": message or WORKER_ERROR_MESSAGES.get(code, code),
        "detail": detail,
        "recovery": recovery or recovery_for(code),
    }
    if diagnostics is not None:
        error["diagnostics"] = diagnostics
        error["diagnostics_total"] = len(diagnostics)
    _emit({"v": CODE_MODE_WORKER_PROTOCOL, "ok": False, "error": error})
    if store is not None and execution_id is not None:
        store.record_error_event(execution_id, error)


def _typing_diagnostics(error: MontyTypingError) -> list[dict[str, Any]]:
    items = json.loads(error.display())
    if not isinstance(items, list):
        raise ValueError("Expected a list of Monty diagnostics")
    diagnostics = []
    for item in items:
        if not isinstance(item, dict):
            continue
        diagnostic = dict(item)
        # MontyCodeRuntime prepends exactly one 'import asyncio' source line.
        for field in ("location", "end_location"):
            loc = diagnostic.get(field)
            if isinstance(loc, dict) and isinstance(loc.get("row"), int):
                diagnostic[field] = {**loc, "row": max(1, loc["row"] - 1)}
        diagnostics.append(diagnostic)
    return diagnostics


def main() -> None:
    args = _parse_args()
    try:
        request = json.loads(args.request.read_text())
    finally:
        args.request.unlink(missing_ok=True)

    store = ExecutionStore(args.store)
    record = runtime_record(store.get(args.execution), store=store)
    try:
        output = asyncio.run(_run(request, record=record))
        try:
            _emit(
                {
                    "v": CODE_MODE_WORKER_PROTOCOL,
                    "ok": True,
                    "result": output,
                }
            )
        except (TypeError, ValueError) as exc:
            _emit_error(
                "non_json_result", str(exc), store=store, execution_id=args.execution
            )
            raise SystemExit(1) from exc
    except SystemExit:
        raise
    except MontyTypingError as exc:
        try:
            diagnostics = _typing_diagnostics(exc)
        except (ValueError, TypeError):
            diagnostics = []
        _emit_error(
            "MontyTypingError",
            diagnostics[0]["message"] if diagnostics else exc.display(),
            category="monty",
            recovery="correct_input",
            message="Monty rejected the code before execution.",
            diagnostics=diagnostics if diagnostics else None,
            store=store,
            execution_id=args.execution,
        )
        raise SystemExit(1) from exc
    except MontyError as exc:
        inner = exc.exception()
        diagnostic: dict[str, Any] = {
            "code": type(inner).__name__,
            "message": str(inner),
        }
        if hasattr(exc, "traceback"):
            frames = exc.traceback()
            if frames:
                frame = frames[-1].dict()
                diagnostic["location"] = {
                    "row": max(1, frame["line"] - 1),
                    "column": frame["column"],
                }
        _emit_error(
            type(exc).__name__,
            exc.display() if hasattr(exc, "display") else str(exc),
            category="monty",
            recovery="inspect_first",
            message=str(exc),
            diagnostics=[diagnostic],
            store=store,
            execution_id=args.execution,
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit_error(
            type(exc).__name__,
            "".join(traceback.format_exception_only(type(exc), exc)).strip(),
            category="execution",
            recovery="inspect_first",
            message="Code Mode Execution failed.",
            store=store,
            execution_id=args.execution,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
