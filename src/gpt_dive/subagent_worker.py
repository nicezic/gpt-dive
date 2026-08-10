from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai_codex import OpenAICodexProvider

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
    agent = Agent(model)
    result = await agent.run(
        task,
        usage_limits=UsageLimits(request_limit=2, output_tokens_limit=output_tokens_limit),
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
