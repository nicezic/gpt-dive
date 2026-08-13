from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, UsageLimits

from .model_registry import ModelAlias, build_model, resolve_model
from .runtime_env import build_runtime_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"


def _usage_summary(result: Any) -> dict[str, Any]:
    usage = result.usage
    if callable(usage):
        usage = usage()
    fields = (
        "requests",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    )
    return {
        name: value
        for name in fields
        if (value := getattr(usage, name, None)) not in (None, 0)
    }


def _validate(
    model: str | ModelAlias,
    prompt: str,
    timeout: float,
    output_tokens_limit: int,
) -> ModelAlias:
    alias = resolve_model(model, lane="bare")
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")
    if output_tokens_limit <= 0:
        raise ValueError("output_tokens_limit must be greater than 0")
    return alias


async def _run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    alias = _validate(
        str(payload["model"]),
        str(payload["prompt"]),
        1.0,
        int(payload.get("output_tokens_limit", 4096)),
    )
    prompt = str(payload["prompt"])
    output_tokens_limit = int(payload.get("output_tokens_limit", 4096))

    # Intentionally bare: no tools, capabilities, filesystem, shell, workspace,
    # repo context, system prompt, or additional instructions.
    agent = Agent(build_model(alias))
    # output_tokens_limit is a Pydantic usage budget, NOT the provider max_tokens cap.
    result = await agent.run(
        prompt,
        usage_limits=UsageLimits(output_tokens_limit=output_tokens_limit),
    )
    return {
        "ok": True,
        "model": alias.value,
        "provider": alias.provider,
        "model_name": alias.model_name,
        "output": str(result.output),
        "usage": _usage_summary(result),
    }


async def invoke_bare(
    *,
    model: str | ModelAlias,
    prompt: str,
    timeout: float = 120.0,
    output_tokens_limit: int = 4096,
) -> dict[str, Any]:
    """Run one tool-less model call through the central model registry."""
    alias = _validate(model, prompt, timeout, output_tokens_limit)
    payload = json.dumps(
        {
            "model": alias.value,
            "prompt": prompt,
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
        "gpt_dive.bare_worker",
        "--worker",
    ]
    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload), timeout=timeout
        )
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {
            "ok": False,
            "model": alias.value,
            "provider": alias.provider,
            "error": f"bare call timed out after {timeout} seconds",
        }

    stdout_text = stdout.decode(errors="replace").strip()
    stderr_text = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "model": alias.value,
            "provider": alias.provider,
            "error": f"bare worker exited with code {proc.returncode}",
            "stderr": stderr_text[-2000:],
        }

    try:
        result = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "model": alias.value,
            "provider": alias.provider,
            "error": f"invalid bare worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_text[-2000:],
        }

    if stderr_text:
        result["worker_stderr"] = stderr_text[-2000:]
    return result

