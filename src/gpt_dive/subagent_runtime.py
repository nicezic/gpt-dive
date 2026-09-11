from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .model_registry import model_catalog, resolve_model
from .runtime_env import build_runtime_path
from .worker_subprocess import run_bounded_worker, stderr_tail, worker_failure

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

# Backward-compatible derived view. ModelAlias remains the SSOT.
MODEL_SPECS = model_catalog()


def _validate_call(
    alias: str, task: str, timeout: float, output_tokens_limit: int
) -> tuple[str, str]:
    prov, model_name = resolve_model(alias)
    if not task.strip():
        raise ValueError("task must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")
    if output_tokens_limit <= 0:
        raise ValueError("output_tokens_limit must be greater than 0")
    return prov, model_name


async def invoke_subagent(
    *,
    alias: str | None = None,
    task: str,
    timeout: float,
    output_tokens_limit: int = 4096,
    workspace_dir: str | None = None,
    model_alias: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run one registered coding subagent with credentials scoped to a child process."""
    effective_alias = alias or model_alias or kwargs.get("user_alias_model") or model
    if not effective_alias:
        raise ValueError("unknown model alias: must provide alias")
    provider, model_name = _validate_call(effective_alias, task, timeout, output_tokens_limit)
    payload = json.dumps(
        {
            "alias": effective_alias,
            "model_alias": effective_alias,
            "model": effective_alias,
            "provider": provider,
            "model_name": model_name,
            "model_id": f"{provider}/{model_name}",
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
    failure = worker_failure(outcome, kind="subagent", timeout=timeout)
    if failure is not None:
        failure["alias"] = effective_alias
        failure["model_alias"] = effective_alias
        failure["model"] = effective_alias
        failure["provider"] = provider
        failure["model_name"] = model_name
        failure["model_id"] = f"{provider}/{model_name}"
        if not outcome.timed_out:
            failure["stderr"] = stderr_tail(outcome.stderr_text)
        return failure

    stdout_text = outcome.stdout_text
    stderr_text = outcome.stderr_text
    try:
        result = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "alias": effective_alias,
            "model_alias": effective_alias,
            "model": effective_alias,
            "provider": provider,
            "model_name": model_name,
            "model_id": f"{provider}/{model_name}",
            "error": f"invalid subagent worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_tail(stderr_text),
        }

    if stderr_text:
        result["worker_stderr"] = stderr_tail(stderr_text)
    return result
