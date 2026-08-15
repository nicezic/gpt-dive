from __future__ import annotations

import asyncio
import json
import math
import os
import signal
from pathlib import Path
from typing import Any

AGY = Path.home() / ".local" / "bin" / "agy"
DEFAULT_MODEL = "gemini-3.7-flash-high"
_PROVIDER = "antigravity"


def _build_command(
    *, task: str, model: str, timeout: float, workspace_dir: str | None = None
) -> list[str]:
    if not task.strip():
        raise ValueError("task must not be empty")
    if not model.strip():
        raise ValueError("model must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    print_timeout = f"{max(1, math.ceil(timeout))}s"
    command = [
        str(AGY),
        "-p",
        task,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--mode",
        "plan",
        "--dangerously-skip-permissions",
        "--print-timeout",
        print_timeout,
    ]
    if workspace_dir is not None:
        command.extend(["--add-dir", workspace_dir])
    return command


def _parse_stream_json(stdout_text: str) -> dict[str, Any]:
    terminal: dict[str, Any] | None = None
    for line_number, raw_line in enumerate(stdout_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid agy stream-json on line {line_number}: {exc}") from exc
        if not isinstance(event, dict):
            raise TypeError(f"invalid agy stream-json event on line {line_number}")
        if event.get("event") == "result":
            result = event.get("result")
            if not isinstance(result, dict):
                raise TypeError("agy result event is missing result object")
            terminal = result

    if terminal is None:
        raise ValueError("agy stream-json did not contain a terminal result event")
    return terminal


async def invoke_agy_worker(
    *,
    task: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 120.0,
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    """Run one read-only Antigravity worker through the official agy CLI."""
    if not AGY.is_file():
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": f"agy executable not found: {AGY}",
        }

    run_cwd: str | None = None
    if workspace_dir is not None:
        workspace = Path(workspace_dir).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace_dir is not a directory: {workspace}")
        run_cwd = str(workspace)

    command = _build_command(
        task=task, model=model, timeout=timeout, workspace_dir=run_cwd
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=run_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": f"failed to launch agy: {exc}",
        }

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2.0)
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": f"agy worker timed out after {timeout} seconds",
        }

    stdout_text = stdout.decode(errors="replace").strip()
    stderr_text = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": f"agy exited with code {proc.returncode}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_text[-2000:],
        }

    try:
        result = _parse_stream_json(stdout_text)
    except (TypeError, ValueError) as exc:
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": str(exc),
            "stdout": stdout_text[-2000:],
            "stderr": stderr_text[-2000:],
        }

    status = str(result.get("status", ""))
    response = result.get("response")
    if status != "SUCCESS" or not isinstance(response, str):
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "conversation_id": result.get("conversation_id"),
            "status": status or None,
            "error": "agy did not return a successful terminal result",
            "response": response,
            "stderr": stderr_text[-2000:],
        }

    payload: dict[str, Any] = {
        "ok": True,
        "provider": _PROVIDER,
        "model_name": model,
        "conversation_id": result.get("conversation_id"),
        "output": response.rstrip("\n"),
    }
    usage = result.get("usage")
    if isinstance(usage, dict):
        payload["usage"] = usage
    if stderr_text:
        payload["worker_stderr"] = stderr_text[-2000:]
    return payload
