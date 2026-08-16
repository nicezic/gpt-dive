from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, UsageLimits
from pydantic_ai_harness import CodeMode, FileSystem

from .filesystem_policy import harness_denied_patterns, is_secret_path
from .model_registry import ModelAlias, build_model, resolve_model
from .runtime_env import build_runtime_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

_PEER_REVIEW_INSTRUCTIONS = (
    "Act as an independent peer reviewer. The packet carries the causal context and may include "
    "a first-run Code Mode evidence loader; use that supplied packet as the primary evidence path. "
    "Keep extra tool turns rare because third-party gateways may replay expensive uncached input. "
    "If evidence is still insufficient, identify the missing information and suggest focused questions "
    "or a better next packet instead of exploratory browsing unless the gap materially blocks judgment."
)


def _build_peer_review_capabilities(workspace_dir: str) -> list[Any]:
    """Build a compact read-only inspection surface for peer review."""
    workspace = Path(workspace_dir).expanduser().resolve()
    home = Path.home().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace_dir is not a directory: {workspace}")
    if is_secret_path(workspace, home=home):
        raise ValueError(f"workspace_dir is a credential/secret path: {workspace}")
    denied_patterns = harness_denied_patterns(root=workspace, home=home)
    return [
        FileSystem(
            root_dir=workspace,
            read_only=True,
            denied_patterns=denied_patterns,
        ),
        CodeMode(),
    ]


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

    peer_review = bool(payload.get("peer_review", False))
    workspace_dir = payload.get("workspace_dir")
    if peer_review:
        if not workspace_dir:
            raise ValueError("workspace_dir is required for peer-review mode")
        agent = Agent(
            build_model(alias),
            instructions=_PEER_REVIEW_INSTRUCTIONS,
            capabilities=_build_peer_review_capabilities(str(workspace_dir)),
        )
    else:
        # Preserve the true tool-less primitive for m3_evidence and direct low-level use.
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
        "mode": "peer-review" if peer_review else "bare",
        "usage": _usage_summary(result),
    }


async def invoke_bare(
    *,
    model: str | ModelAlias,
    prompt: str,
    timeout: float = 120.0,
    output_tokens_limit: int = 4096,
    peer_review: bool = False,
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    """Run a model call through the registry, optionally with peer-review inspection tools."""
    alias = _validate(model, prompt, timeout, output_tokens_limit)
    payload = json.dumps(
        {
            "model": alias.value,
            "prompt": prompt,
            "output_tokens_limit": output_tokens_limit,
            "peer_review": peer_review,
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

