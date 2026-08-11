from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from pydantic_ai_harness import FileSystem, Shell
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from .subagent_runtime import MODEL_SPECS


def _build_model(alias: str):
    if alias == "opus5":
        provider = AnthropicProvider(
            api_key=os.environ["AIAPIFLOW_CLAUDE_KEY"],
            base_url="https://aiapiflow.com",
        )
        return AnthropicModel("claude-opus-5", provider=provider)
    if alias == "m3":
        provider = AnthropicProvider(
            api_key=os.environ["MINIMAX_API_KEY"],
            base_url="https://api.minimax.io/anthropic",
        )
        return AnthropicModel("MiniMax-M3", provider=provider)
    if alias in {"terra", "luna"}:
        model_name = "gpt-5.6-terra" if alias == "terra" else "gpt-5.6-luna"
        return OpenAIResponsesModel(model_name, provider=OpenAICodexProvider())
    raise ValueError(f"unknown model alias: {alias}")


def _build_worker_capabilities(workspace_dir: str):
    """Build the default coding-worker capability bundle for one local workspace."""
    workspace = Path(workspace_dir).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace_dir is not a directory: {workspace}")

    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    pnpm_bin = Path.home() / ".local" / "share" / "pnpm"
    shell_env = os.environ.copy()
    shell_env["PATH"] = f"{guard_bin}:{pnpm_bin}:{shell_env.get('PATH', '')}"
    denied_env_patterns = [
        *LLM_API_KEY_ENV_PATTERNS,
        "MINIMAX_*",
        "AIAPIFLOW_*",
    ]

    return [
        FileSystem(root_dir=workspace),
        Shell(
            cwd=workspace,
            env=shell_env,
            denied_env_patterns=denied_env_patterns,
            default_timeout=60.0,
            max_output_chars=50_000,
        ),
        RepoContext(
            workspace_dir=workspace,
            nested_traversal=True,
        ),
        ToolOutputLimits(),
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


async def _run(payload: dict[str, Any]) -> dict[str, Any]:
    alias = str(payload["model"]).strip().lower()
    if alias not in MODEL_SPECS:
        raise ValueError(f"unknown model alias: {alias}")
    task = str(payload["task"])
    output_tokens_limit = int(payload.get("output_tokens_limit", 4096))
    model = _build_model(alias)
    workspace_dir = payload.get("workspace_dir")
    capabilities = _build_worker_capabilities(str(workspace_dir)) if workspace_dir else []
    agent = Agent(model, capabilities=capabilities)
    result = await agent.run(
        task,
        usage_limits=UsageLimits(
            output_tokens_limit=output_tokens_limit
        ),
    )
    spec = MODEL_SPECS[alias]
    return {
        "ok": True,
        "model": alias,
        "provider": spec["provider"],
        "model_name": spec["model"],
        "output": str(result.output),
        "usage": _usage_summary(result),
    }


def main() -> None:
    payload = json.loads(sys.stdin.read())
    result = asyncio.run(_run(payload))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
