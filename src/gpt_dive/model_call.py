from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CachePoint, UsageLimits
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai_harness import CodeMode, FileSystem

from .filesystem_policy import harness_denied_patterns, is_secret_path
from .model_registry import (
    PROVIDER_ROUTES,
    ModelAlias,
    build_model,
    build_provider_model,
    model_output_tokens_limit,
    resolve_model,
    verify_provider_model,
)
from .runtime_env import build_runtime_path
from .worker_subprocess import run_bounded_worker, stderr_tail

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

_PEER_CACHE_BREAK = "\n<!-- GPT_DIVE_PEER_CACHE_BREAK -->\n"
_PEER_DEFAULT_OUTPUT_TOKENS_LIMIT = 8_192

_PEER_REVIEW_INSTRUCTIONS = (
    "Act as an independent peer reviewer. Use the supplied packet as the primary evidence path. "
    "Do not reread evidence already embedded in the packet. Read/write file tools are available inside the scoped workspace only when extra evidence is materially necessary. "
    "Return the complete review as your final response; the host will persist it to peer_answer.md. "
    "Do not guess merely to save tokens. Still consider token economy because premium-model reasoning, tool outputs, "
    "and new context cost money even when a stable prompt prefix is cached. Avoid broad exploratory tool use by default. "
    "When broader research can wait, state focused questions or the exact evidence needed so the host can return it in "
    "the next packet, potentially using a cheaper subagent."
)


def _build_peer_review_capabilities(workspace_dir: str) -> list[Any]:
    """Build a compact read/write inspection surface for peer review."""
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
            read_only=False,
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
    output_tokens_limit: int | None,
) -> ModelAlias:
    alias = resolve_model(model, lane="peer_review")
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")
    if output_tokens_limit is not None and output_tokens_limit <= 0:
        raise ValueError("output_tokens_limit must be greater than 0")
    return alias


async def _run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    peer_review = bool(payload.get("peer_review", False))
    prompt = str(payload["prompt"])
    workspace_dir = payload.get("workspace_dir")
    anthropic_thinking = payload.get("anthropic_thinking")

    if peer_review:
        provider = str(payload["provider"])
        route = PROVIDER_ROUTES.get(provider)
        if route is None:
            known = ", ".join(sorted(PROVIDER_ROUTES))
            return {
                "ok": False,
                "mode": "peer-review",
                "provider": provider,
                "error": f"unknown peer provider {provider!r}; registered providers: {known}",
            }
        explicit_model = bool(payload.get("model") and str(payload["model"]).strip())
        model_name = str(payload["model"]).strip() if explicit_model else route.default_model
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        if not workspace_dir:
            raise ValueError("workspace_dir is required for peer-review mode")

        if explicit_model:
            verification = await verify_provider_model(provider, model_name)
            if verification["checked"] and not verification["exists"]:
                return {
                    "ok": False,
                    "mode": "peer-review",
                    "model": model_name,
                    "provider": provider,
                    "error": (
                        f"model {model_name!r} is not offered by provider {provider!r}"
                    ),
                    "available_models": sorted(verification["available"]),
                }

        output_tokens_limit = (
            model_output_tokens_limit(model_name) or _PEER_DEFAULT_OUTPUT_TOKENS_LIMIT
        )
        agent = Agent(
            build_provider_model(provider, model_name),
            instructions=_PEER_REVIEW_INSTRUCTIONS,
            capabilities=_build_peer_review_capabilities(str(workspace_dir)),
            model_settings=AnthropicModelSettings(max_tokens=output_tokens_limit),
        )
    else:
        output_tokens_limit = int(payload.get("output_tokens_limit", 4096))
        alias = _validate(str(payload["model"]), prompt, 1.0, output_tokens_limit)
        if anthropic_thinking is not None:
            if anthropic_thinking not in {"adaptive", "disabled"}:
                raise ValueError("anthropic_thinking must be 'adaptive', 'disabled', or None")
            if alias.transport != "anthropic-compatible":
                raise ValueError("anthropic_thinking requires an Anthropic-compatible model")
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
    if peer_review and provider == "kunavo" and model_name == "claude-opus-5" and _PEER_CACHE_BREAK in prompt:
        stable_base, round_delta = prompt.split(_PEER_CACHE_BREAK, 1)
        if not stable_base.strip() or not round_delta.strip():
            raise ValueError("Kunavo peer cache marker requires non-empty base and round delta")
        run_prompt = [stable_base, CachePoint(ttl="5m"), round_delta]

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
        "model": model_name if peer_review else alias.value,
        "provider": provider if peer_review else alias.provider,
        "model_name": model_name if peer_review else alias.model_name,
        "output": str(result.output),
        "mode": "peer-review" if peer_review else "model-call",
        "finish_reason": finish_reason,
        "provider_finish_reason": provider_finish_reason,
        "truncated": truncated,
        "usage": _usage_summary(result),
    }


async def invoke_model_call(
    *,
    model: str | ModelAlias | None,
    prompt: str,
    timeout: float,
    output_tokens_limit: int = 4096,
    peer_review: bool = False,
    provider: str | None = None,
    workspace_dir: str | None = None,
    anthropic_thinking: str | None = None,
) -> dict[str, Any]:
    """Run a model call, using provider + exact model name for peer review."""
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    if peer_review:
        if not provider:
            raise ValueError("provider is required for peer-review mode")
        provider_label = provider
        payload_model = str(model).strip() if model is not None and str(model).strip() else None
        model_label = payload_model or ""
        requested_output_tokens_limit = None
    else:
        if model is None:
            raise ValueError("model is required for alias-based model calls")
        alias = _validate(model, prompt, timeout, output_tokens_limit)
        model_label = alias.value
        provider_label = alias.provider
        payload_model = alias.value
        requested_output_tokens_limit = output_tokens_limit

    payload = json.dumps(
        {
            "provider": provider if peer_review else None,
            "model": payload_model,
            "prompt": prompt,
            "output_tokens_limit": requested_output_tokens_limit,
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
        "gpt_dive.model_call_worker",
        "--worker",
    ]
    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))

    outcome = await run_bounded_worker(
        command,
        stdin_payload=payload,
        env=env,
        timeout=timeout,
        log_label="MODEL_CALL",
    )
    stdout_text = outcome["stdout_text"]
    stderr_text = outcome["stderr_text"]
    if outcome["timed_out"]:
        return {
            "ok": False,
            "model": model_label,
            "provider": provider_label,
            "error": f"model call timed out after {timeout} seconds",
        }
    if outcome["returncode"] != 0:
        return {
            "ok": False,
            "model": model_label,
            "provider": provider_label,
            "error": f"model call worker exited with code {outcome['returncode']}",
            "stderr": stderr_tail(stderr_text),
        }

    try:
        result = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "model": model_label,
            "provider": provider_label,
            "error": f"invalid model call worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_text[-2000:],
        }

    if stderr_text:
        result["worker_stderr"] = stderr_text[-2000:]
    return result

