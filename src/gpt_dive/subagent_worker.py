from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, UsageLimits
from pydantic_ai_harness import FileSystem, Shell
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from .model_registry import build_model, resolve_model
from .runtime_env import build_runtime_path


def _build_worker_capabilities(workspace_dir: str):
    """Build the default coding-worker capability bundle for one local workspace."""
    workspace = Path(workspace_dir).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace_dir is not a directory: {workspace}")

    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    shell_env = os.environ.copy()
    shell_env["PATH"] = build_runtime_path(guard_bin, inherited=shell_env.get("PATH"))
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
    alias = resolve_model(str(payload["model"]), lane="subagent")
    task = str(payload["task"])
    output_tokens_limit = int(payload.get("output_tokens_limit", 4096))
    workspace_dir = payload.get("workspace_dir")
    capabilities = (
        _build_worker_capabilities(str(workspace_dir)) if workspace_dir else []
    )
    agent = Agent(build_model(alias), capabilities=capabilities)
    result = await agent.run(
        task,
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


def main() -> None:
    payload = json.loads(sys.stdin.read())
    result = asyncio.run(_run(payload))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
