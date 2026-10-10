from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.exceptions import AgentRunError, ModelHTTPError
from pydantic_ai_harness import FileSystem, Shell
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.tool_output_limits import (
    Band,
    LocalFileStore,
    Spill,
    ToolOutputLimits,
    Truncate,
)

from .model_registry import get_model, resolve_model
from .runtime_env import DENIED_MODEL_ENV_PATTERNS, build_runtime_path

_TOOL_OUTPUT_SPILL_THRESHOLD_CHARS = 8_000
_TOOL_OUTPUT_SPILL_TTL = timedelta(hours=48)


def _build_tool_output_limits() -> ToolOutputLimits:
    """Bound large worker tool returns while keeping lossless read-back available."""
    return ToolOutputLimits(
        bands=[
            Band(
                over=_TOOL_OUTPUT_SPILL_THRESHOLD_CHARS,
                action=Spill(then=Truncate()),
            )
        ],
        store=LocalFileStore(cleanup_after=_TOOL_OUTPUT_SPILL_TTL),
    )


def _build_worker_capabilities(workspace_dir: str):
    """Build the default coding-worker capability bundle for one local workspace."""
    workspace = Path(workspace_dir).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace_dir is not a directory: {workspace}")

    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    shell_env = os.environ.copy()
    shell_env["PATH"] = build_runtime_path(guard_bin, inherited=shell_env.get("PATH"))
    return [
        LocalWorkspace(workspace),
        FileSystem(root_dir=workspace),
        Shell(
            env=shell_env,
            denied_env_patterns=DENIED_MODEL_ENV_PATTERNS,
            default_timeout=60.0,
            max_output_chars=50_000,
        ),
        RepoContext(nested_traversal=True),
        _build_tool_output_limits(),
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
    raw_model = str(payload["alias"])
    provider, model_name = resolve_model(raw_model)
    task = str(payload["task"])
    raw_limit = payload.get("output_tokens_limit")
    output_tokens_limit = int(raw_limit) if raw_limit is not None else None
    workspace_dir = payload.get("workspace_dir")
    capabilities = (
        _build_worker_capabilities(str(workspace_dir)) if workspace_dir else []
    )
    agent = Agent(get_model(raw_model), capabilities=capabilities)
    usage_limits = (
        UsageLimits(output_tokens_limit=output_tokens_limit)
        if output_tokens_limit is not None
        else None
    )
    result = await agent.run(
        task,
        usage_limits=usage_limits,
    )
    return {
        "ok": True,
        "alias": raw_model,
        "model_id": f"{provider}/{model_name}",
        "model": raw_model,
        "model_alias": raw_model,
        "provider": provider,
        "model_name": model_name,
        "output": str(result.output),
        "usage": _usage_summary(result),
    }


def main() -> None:
    payload = json.loads(sys.stdin.read())
    try:
        result = asyncio.run(_run(payload))
    except AgentRunError as exc:
        error = {"category": "model", "code": type(exc).__name__,
                 "message": "Subagent model run failed.", "recovery": "inspect_first"}
        if isinstance(exc, ModelHTTPError):
            error["http_status"] = exc.status_code
        result = {"ok": False, "error": error}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
