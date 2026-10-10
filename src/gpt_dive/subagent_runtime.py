from __future__ import annotations

import json
from typing import Any

from .model_registry import resolve_model
from .worker_subprocess import (
    credentialed_python_worker,
    parse_worker_json,
    run_bounded_worker,
    stderr_tail,
    worker_failure,
)


def _validate_call(
    alias: str, task: str, timeout: float, output_tokens_limit: int | None
) -> tuple[str, str]:
    prov, model_name = resolve_model(alias)
    if not task.strip():
        raise ValueError("task must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")
    if output_tokens_limit is not None and output_tokens_limit <= 0:
        raise ValueError("output_tokens_limit must be greater than 0")
    return prov, model_name


async def invoke_subagent(
    *,
    alias: str,
    task: str,
    timeout: float,
    output_tokens_limit: int | None = None,
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    """Run one registered coding subagent with credentials scoped to a child process."""
    provider, model_name = _validate_call(alias, task, timeout, output_tokens_limit)
    payload = json.dumps(
        {
            "alias": alias,
            "provider": provider,
            "model_name": model_name,
            "model_id": f"{provider}/{model_name}",
            "task": task,
            "output_tokens_limit": output_tokens_limit,
            "workspace_dir": workspace_dir,
        },
        ensure_ascii=False,
    ).encode()

    command, env = credentialed_python_worker("gpt_dive.subagent_worker")

    outcome = await run_bounded_worker(
        command,
        stdin_payload=payload,
        env=env,
        timeout=timeout,
        log_label="SUBAGENT",
    )
    failure = worker_failure(outcome, kind="subagent", timeout=timeout)
    if failure is not None:
        failure["alias"] = alias
        failure["model_alias"] = alias
        failure["model"] = alias
        failure["provider"] = provider
        failure["model_name"] = model_name
        failure["model_id"] = f"{provider}/{model_name}"
        if not outcome.timed_out:
            failure["stderr"] = stderr_tail(outcome.stderr_text)
        return failure

    stdout_text = outcome.stdout_text
    stderr_text = outcome.stderr_text
    try:
        result = parse_worker_json(outcome)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "alias": alias,
            "model_alias": alias,
            "model": alias,
            "provider": provider,
            "model_name": model_name,
            "model_id": f"{provider}/{model_name}",
            "error": f"invalid subagent worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_tail(stderr_text),
        }

    return result
