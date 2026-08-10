from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

MODEL_SPECS: dict[str, dict[str, str]] = {
    "opus5": {
        "provider": "aiapiflow",
        "model": "claude-opus-5",
        "transport": "anthropic-compatible",
    },
    "m3": {
        "provider": "minimax",
        "model": "MiniMax-M3",
        "transport": "anthropic-compatible",
    },
    "terra": {
        "provider": "openai-codex",
        "model": "gpt-5.6-terra",
        "transport": "codex-subscription",
    },
    "luna": {
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "transport": "codex-subscription",
    },
}


def model_catalog() -> dict[str, dict[str, str]]:
    return {name: dict(spec) for name, spec in MODEL_SPECS.items()}


def _validate_call(model: str, task: str, timeout: float, output_tokens_limit: int) -> str:
    alias = model.strip().lower()
    if alias not in MODEL_SPECS:
        choices = ", ".join(sorted(MODEL_SPECS))
        raise ValueError(f"unknown subagent model alias {model!r}; choose one of: {choices}")
    if not task.strip():
        raise ValueError("task must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")
    if output_tokens_limit <= 0:
        raise ValueError("output_tokens_limit must be greater than 0")
    return alias


async def invoke_subagent(
    *,
    model: str,
    task: str,
    timeout: float = 120.0,
    output_tokens_limit: int = 4096,
) -> dict[str, Any]:
    """Run one registered model call with credentials scoped to a child process."""
    alias = _validate_call(model, task, timeout, output_tokens_limit)
    payload = json.dumps(
        {
            "model": alias,
            "task": task,
            "output_tokens_limit": output_tokens_limit,
        },
        ensure_ascii=False,
    ).encode()

    command = [
        str(CREDS),
        "run",
        "ai",
        "--",
        str(UV),
        "run",
        "--project",
        str(PROJECT_ROOT),
        "--python",
        "3.14",
        "python",
        "-m",
        "gpt_dive.subagent_worker",
    ]

    child_env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    child_env["PATH"] = f"{local_bin}:{child_env.get('PATH', '')}"

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env=child_env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {
            "ok": False,
            "model": alias,
            "provider": MODEL_SPECS[alias]["provider"],
            "error": f"subagent call timed out after {timeout} seconds",
        }

    stdout_text = stdout.decode(errors="replace").strip()
    stderr_text = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "model": alias,
            "provider": MODEL_SPECS[alias]["provider"],
            "error": f"subagent worker exited with code {proc.returncode}",
            "stderr": stderr_text[-2000:],
        }

    try:
        result = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "model": alias,
            "provider": MODEL_SPECS[alias]["provider"],
            "error": f"invalid subagent worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_text[-2000:],
        }

    if stderr_text:
        result["worker_stderr"] = stderr_text[-2000:]
    return result
