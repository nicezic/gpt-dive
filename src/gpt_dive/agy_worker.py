from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .worker_subprocess import run_bounded_worker, stderr_tail

AGY = Path.home() / ".local" / "bin" / "agy"
DEFAULT_MODEL = "gemini-3.7-flash-high"
_PROVIDER = "antigravity"


def _build_command(
    *,
    task: str,
    model: str,
    timeout: float,
    workspace_dir: str | None = None,
    conversation_id: str | None = None,
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
    if conversation_id is not None:
        command.extend(["--conversation", conversation_id])
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


def _extract_stream_metadata(
    stdout_text: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Best-effort metadata extraction from a possibly incomplete AGY stream."""
    conversation_id: str | None = None
    terminal: dict[str, Any] | None = None

    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        candidates = [event, event.get("step_update"), event.get("result")]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            value = candidate.get("conversation_id")
            if isinstance(value, str) and value.strip():
                conversation_id = value

        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            terminal = event["result"]

    return conversation_id, terminal


async def invoke_agy_worker(
    *,
    task: str,
    model: str = DEFAULT_MODEL,
    timeout: float,
    workspace_dir: str | None = None,
    conversation_id: str | None = None,
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
        task=task,
        model=model,
        timeout=timeout,
        workspace_dir=run_cwd,
        conversation_id=conversation_id,
    )

    try:
        outcome = await run_bounded_worker(
            command,
            cwd=run_cwd,
            timeout=timeout,
            log_label="AGY",
        )
    except OSError as exc:
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": f"failed to launch agy: {exc}",
        }

    stdout_text = outcome["stdout_text"]
    stderr_text = outcome["stderr_text"]
    if outcome["timed_out"]:
        conversation_id, terminal = _extract_stream_metadata(stdout_text)
        payload: dict[str, Any] = {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "timed_out": True,
            "error": f"agy worker timed out after {timeout} seconds",
        }
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if terminal is not None:
            response = terminal.get("response")
            if isinstance(response, str) and response:
                payload["partial_output"] = response.rstrip("\n")
        if stdout_text:
            payload["stdout"] = stdout_text[-4000:]
        if stderr_text:
            payload["stderr"] = stderr_tail(stderr_text)
        return payload

    if outcome["returncode"] != 0:
        return {
            "ok": False,
            "provider": _PROVIDER,
            "model_name": model,
            "error": f"agy exited with code {outcome['returncode']}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_tail(stderr_text),
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
            "stderr": stderr_tail(stderr_text),
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
            "stderr": stderr_tail(stderr_text),
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
        payload["worker_stderr"] = stderr_tail(stderr_text)
    return payload
