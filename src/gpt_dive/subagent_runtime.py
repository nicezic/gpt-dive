from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model_registry import ModelAlias, model_catalog, resolve_model
from .runtime_env import build_runtime_path
from .worker_subprocess import run_bounded_worker, stderr_tail

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

# Backward-compatible derived view. ModelAlias remains the SSOT.
MODEL_SPECS = model_catalog()


def _validate_call(
    model: str, task: str, timeout: float, output_tokens_limit: int
) -> ModelAlias:
    alias = resolve_model(model, lane="subagent")
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
    timeout: float,
    output_tokens_limit: int = 4096,
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    """Run one registered coding subagent with credentials scoped to a child process."""
    alias = _validate_call(model, task, timeout, output_tokens_limit)
    payload = json.dumps(
        {
            "model": alias.value,
            "task": task,
            "output_tokens_limit": output_tokens_limit,
            "workspace_dir": workspace_dir,
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
    child_env["PATH"] = build_runtime_path(inherited=child_env.get("PATH"))

    outcome = await run_bounded_worker(
        command,
        stdin_payload=payload,
        env=child_env,
        timeout=timeout,
        log_label="SUBAGENT",
    )
    stdout_text = outcome.stdout_text
    stderr_text = outcome.stderr_text
    if outcome.timed_out:
        return {
            "ok": False,
            "model": alias.value,
            "provider": alias.provider,
            "error": f"subagent call timed out after {timeout} seconds",
        }
    if outcome.returncode != 0:
        return {
            "ok": False,
            "model": alias.value,
            "provider": alias.provider,
            "error": f"subagent worker exited with code {outcome.returncode}",
            "stderr": stderr_tail(stderr_text),
        }

    try:
        result = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "model": alias.value,
            "provider": alias.provider,
            "error": f"invalid subagent worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_tail(stderr_text),
        }

    if stderr_text:
        result["worker_stderr"] = stderr_tail(stderr_text)
    return result
