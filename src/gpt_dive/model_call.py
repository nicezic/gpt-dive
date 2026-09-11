from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CachePoint, UsageLimits
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai_harness import CodeMode, FileSystem
from pydantic_ai_harness.filesystem import FileSystemToolset

from .filesystem_policy import harness_denied_patterns, is_secret_path
from .model_registry import (
    PROVIDER_ROUTES,
    build_model,
    build_provider_model,
    model_output_tokens_limit,
    resolve_model,
    verify_provider_model,
)
from .runtime_env import build_runtime_path
from .worker_subprocess import run_bounded_worker, stderr_tail, worker_failure

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDS = Path.home() / ".local" / "bin" / "creds"
UV = Path.home() / ".local" / "bin" / "uv"

_PEER_CACHE_BREAK = "\n<!-- GPT_DIVE_PEER_CACHE_BREAK -->\n"
_PEER_DEFAULT_OUTPUT_TOKENS_LIMIT = 8_192
_PEER_READ_OUTPUT_BYTES = 256 * 1024

_EMPTY_PROMPT_ERROR = "prompt must not be empty"


class _PeerFileSystemToolset(FileSystemToolset[Any]):
    async def read_file(
        self, path: str, *, offset: int = 0, limit: int | None = None
    ) -> str:
        # A formatted source line costs at least 8 bytes (line number + tab + newline),
        # so this default line bound cannot fire before the 256 KiB output bound.
        if limit is None:
            limit = _PEER_READ_OUTPUT_BYTES // 8
        text = await super().read_file(path, offset=offset, limit=limit)
        encoded = text.encode("utf-8")
        if len(encoded) <= _PEER_READ_OUTPUT_BYTES:
            return text

        reserve = 128
        prefix = encoded[: _PEER_READ_OUTPUT_BYTES - reserve].decode(
            "utf-8", errors="ignore"
        )
        header_end = prefix.find("\n")
        last_newline = prefix.rfind("\n")
        if last_newline > header_end:
            prefix = prefix[: last_newline + 1]
            last_line = prefix.rstrip("\n").rsplit("\n", 1)[-1]
            line_number = last_line.split("\t", 1)[0].strip()
            if line_number.isdigit():
                return (
                    prefix
                    + f"... (read_file output capped at 256 KiB. "
                    f"Use offset={line_number} to continue reading.)\n"
                )
        return prefix + "\n... (read_file output capped at 256 KiB; narrow with offset/limit.)\n"


class _PeerFileSystem(FileSystem):
    def get_toolset(self) -> FileSystemToolset[Any]:
        return _PeerFileSystemToolset(
            root_dir=Path(self.root_dir),
            allowed_patterns=self.allowed_patterns,
            denied_patterns=self.denied_patterns,
            protected_patterns=self.protected_patterns,
            max_read_lines=self.max_read_lines,
            max_list_results=self.max_list_results,
            max_search_results=self.max_search_results,
            max_find_results=self.max_find_results,
        )


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
        _PeerFileSystem(
            root_dir=workspace,
            read_only=False,
            denied_patterns=denied_patterns,
        ),
        CodeMode(),
    ]


def _peer_model_label(payload_model: str | None, provider: str) -> str:
    """Best-effort model label for error envelopes.

    Explicit ids win; otherwise report the route's default so transport-error
    envelopes never carry an empty ``model`` field. Unknown providers keep
    "" — the worker reports the authoritative unknown-provider error.
    """
    if payload_model:
        return payload_model
    route = PROVIDER_ROUTES.get(provider)
    return route.default_model if route else ""


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


async def _run_worker(payload: dict[str, Any]) -> dict[str, Any]:
    peer_review = bool(payload.get("peer_review", False))
    prompt = str(payload["prompt"])
    workspace_dir = payload.get("workspace_dir")
    anthropic_thinking = payload.get("anthropic_thinking")

    if peer_review:
        provider = str(payload["provider"])
        route = PROVIDER_ROUTES.get(provider)
        if route is None and provider != "openai-codex":
            known = ", ".join(sorted((*PROVIDER_ROUTES, "openai-codex")))
            return {
                "ok": False,
                "mode": "peer-review",
                "provider": provider,
                "error": f"unknown peer provider {provider!r}; registered providers: {known}",
            }
        explicit_model = bool(payload.get("model") and str(payload["model"]).strip())
        if provider == "openai-codex" and not explicit_model:
            return {
                "ok": False,
                "mode": "peer-review",
                "provider": provider,
                "error": "model is required for openai-codex peer review",
            }
        if explicit_model:
            model_name = str(payload["model"]).strip()
        else:
            assert route is not None
            model_name = route.default_model
        # Defense line across the process boundary: this worker is spawned with
        # stdin JSON, so it re-checks what the host already validated in case a
        # future spawner skips the host-side gate.
        if not prompt.strip():
            raise ValueError(_EMPTY_PROMPT_ERROR)
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
        raw_model = str(
            payload.get("alias") or payload.get("model_alias") or payload.get("model")
        )
        provider, model_name = resolve_model(raw_model)
        route = PROVIDER_ROUTES.get(provider)
        transport = (
            "codex-subscription"
            if provider == "openai-codex"
            else (route.transport if route else "")
        )
        if anthropic_thinking is not None:
            if anthropic_thinking not in {"adaptive", "disabled"}:
                raise ValueError(
                    "anthropic_thinking must be 'adaptive', 'disabled', or None"
                )
            if transport != "anthropic-compatible":
                raise ValueError(
                    "anthropic_thinking requires an Anthropic-compatible model"
                )
        model_settings = (
            AnthropicModelSettings(anthropic_thinking={"type": anthropic_thinking})
            if anthropic_thinking is not None
            else None
        )
        agent = (
            Agent(build_model(raw_model), model_settings=model_settings)
            if model_settings
            else Agent(build_model(raw_model))
        )

    run_prompt: str | list[Any] = prompt
    if (
        peer_review
        and provider in ("micu", "micu-opus")
        and model_name == "claude-opus-5"
        and _PEER_CACHE_BREAK in prompt
    ):
        stable_base, round_delta = prompt.split(_PEER_CACHE_BREAK, 1)
        if not stable_base.strip() or not round_delta.strip():
            raise ValueError(
                "Micu peer cache marker requires non-empty base and round delta"
            )
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
    # Resolve the lane identity once instead of branching on peer_review per field.
    if peer_review:
        model_label = str(payload.get("alias") or payload.get("model_alias") or model_name)
        provider_label_result = provider
        resolved_model_name = model_name
        mode = "peer-review"
    else:
        model_label = raw_model
        provider_label_result = provider
        resolved_model_name = model_name
        mode = "model-call"
    return {
        "ok": not truncated,
        "alias": model_label,
        "model_id": f"{provider_label_result}/{resolved_model_name}",
        "model": model_label,
        "provider": provider_label_result,
        "model_name": resolved_model_name,
        "output": str(result.output),
        "mode": mode,
        "finish_reason": finish_reason,
        "provider_finish_reason": provider_finish_reason,
        "truncated": truncated,
        "usage": _usage_summary(result),
    }


async def invoke_model_call(
    *,
    alias: str | None = None,
    prompt: str,
    timeout: float,
    output_tokens_limit: int = 4096,
    peer_review: bool = False,
    provider: str | None = None,
    workspace_dir: str | None = None,
    anthropic_thinking: str | None = None,
    model_alias: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a model call, using alias for resolution."""
    effective_alias = (
        alias
        or model_alias
        or kwargs.get("user_alias_model")
        or (str(model) if model is not None else None)
    )
    if not prompt.strip():
        raise ValueError(_EMPTY_PROMPT_ERROR)
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    if peer_review:
        if not effective_alias and not provider:
            raise ValueError("alias is required for peer-review mode")
        if effective_alias:
            prov, model_name = resolve_model(effective_alias, provider=provider)
            provider_label = prov
            model_label = effective_alias
            payload_model = model_name
        else:
            assert provider is not None
            provider_label = provider
            payload_model = None
            model_label = _peer_model_label(payload_model, provider)
        requested_output_tokens_limit = None
    else:
        if effective_alias is None:
            raise ValueError("alias is required for model calls")
        provider_label, payload_model = resolve_model(effective_alias)
        if output_tokens_limit <= 0:
            raise ValueError("output_tokens_limit must be greater than 0")
        model_label = effective_alias
        requested_output_tokens_limit = output_tokens_limit

    payload = json.dumps(
        {
            "provider": provider_label if peer_review else None,
            "model": payload_model,
            "alias": model_label,
            "model_alias": model_label,
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
    failure = worker_failure(outcome, kind="model call", timeout=timeout)
    if failure is not None:
        failure["alias"] = model_label
        failure["model"] = model_label
        failure["model_alias"] = model_label
        failure["provider"] = provider_label
        if payload_model:
            failure["model_name"] = payload_model
            failure["model_id"] = f"{provider_label}/{payload_model}"
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
            "alias": model_label,
            "model": model_label,
            "model_alias": model_label,
            "provider": provider_label,
            "model_id": f"{provider_label}/{payload_model}" if payload_model else provider_label,
            "error": f"invalid model call worker JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_tail(stderr_text),
        }

    if stderr_text:
        result["worker_stderr"] = stderr_tail(stderr_text)
    return result
