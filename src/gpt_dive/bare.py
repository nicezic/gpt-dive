from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CachePoint, UsageLimits
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai_harness import CodeMode, FileSystem

from .filesystem_policy import harness_denied_patterns, is_secret_path
from .model_registry import ModelAlias, build_model, resolve_model
from .runtime_env import build_runtime_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

_PEER_CACHE_BREAK = "\n<!-- GPT_DIVE_PEER_CACHE_BREAK -->\n"

_PEER_REVIEW_INSTRUCTIONS = (
    "Act as an independent peer reviewer. Use the supplied packet as the primary evidence path. "
    "Read-only tools are allowed when a missing fact materially blocks judgment or is likely to change the answer; "
    "do not guess merely to save tokens. Still consider token economy because premium-model reasoning, tool outputs, "
    "and new context cost money even when a stable prompt prefix is cached. Avoid broad exploratory tool use by default. "
    "When broader research can wait, state focused questions or the exact evidence needed so the host can return it in "
    "the next packet, potentially using a cheaper subagent."
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
    anthropic_thinking = payload.get("anthropic_thinking")
    if anthropic_thinking is not None:
        if anthropic_thinking not in {"adaptive", "disabled"}:
            raise ValueError("anthropic_thinking must be 'adaptive', 'disabled', or None")
        if alias.transport != "anthropic-compatible":
            raise ValueError("anthropic_thinking requires an Anthropic-compatible model")
    if peer_review:
        if not workspace_dir:
            raise ValueError("workspace_dir is required for peer-review mode")
        peer_model_settings = (
            AnthropicModelSettings(max_tokens=output_tokens_limit)
            if alias is ModelAlias.KUNAVO_OPUS5
            else None
        )
        agent = Agent(
            build_model(alias),
            instructions=_PEER_REVIEW_INSTRUCTIONS,
            capabilities=_build_peer_review_capabilities(str(workspace_dir)),
            model_settings=peer_model_settings,
        )
    else:
        # Preserve the true tool-less primitive for m3_evidence and direct low-level use.
        model_settings = (
            AnthropicModelSettings(anthropic_thinking={"type": anthropic_thinking})
            if anthropic_thinking is not None
            else None
        )
        agent = (
            Agent(build_model(alias), model_settings=model_settings)
            if model_settings
            else Agent(build_model(alias))
        )
    run_prompt: str | list[Any] = prompt
    if peer_review and alias is ModelAlias.KUNAVO_OPUS5 and _PEER_CACHE_BREAK in prompt:
        stable_base, round_delta = prompt.split(_PEER_CACHE_BREAK, 1)
        if not stable_base.strip() or not round_delta.strip():
            raise ValueError("Kunavo peer cache marker requires non-empty base and round delta")
        run_prompt = [stable_base, CachePoint(ttl="5m"), round_delta]

    # output_tokens_limit is a Pydantic usage budget, NOT the provider max_tokens cap.
    result = await agent.run(
        run_prompt,
        usage_limits=UsageLimits(output_tokens_limit=output_tokens_limit),
    )
    response = result.response
    finish_reason = response.finish_reason
    provider_details = response.provider_details or {}
    provider_finish_reason = provider_details.get("finish_reason")
    truncated = finish_reason == "length"
    return {
        "ok": not truncated,
        "model": alias.value,
        "provider": alias.provider,
        "model_name": alias.model_name,
        "output": str(result.output),
        "mode": "peer-review" if peer_review else "bare",
        "finish_reason": finish_reason,
        "provider_finish_reason": provider_finish_reason,
        "truncated": truncated,
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
    anthropic_thinking: str | None = None,
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
            "anthropic_thinking": anthropic_thinking,
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

