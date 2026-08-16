from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import ClassVar, cast

from pydantic_ai_harness import CodeMode, FileSystem

import gpt_dive.bare as bare_module


class _FakeResult:
    output = "BARE_WORKER_OK"
    usage = SimpleNamespace(requests=1, input_tokens=7, output_tokens=5)


class _FakeAgent:
    init_args: ClassVar[tuple[object, ...]] = ()
    init_kwargs: ClassVar[dict[str, object]] = {}
    run_prompt = ""

    def __init__(self, *args, **kwargs) -> None:
        type(self).init_args = args
        type(self).init_kwargs = kwargs

    async def run(self, prompt: str, **kwargs):
        type(self).run_prompt = prompt
        return _FakeResult()


def test_bare_worker_builds_agent_without_tools_or_capabilities(monkeypatch) -> None:
    sentinel_model = object()
    monkeypatch.setattr(bare_module, "Agent", _FakeAgent)
    monkeypatch.setattr(bare_module, "build_model", lambda alias: sentinel_model)

    result = asyncio.run(
        bare_module._run_worker(
            {
                "model": "opus5",
                "prompt": "review this",
                "output_tokens_limit": 123,
            }
        )
    )

    assert _FakeAgent.init_args == (sentinel_model,)
    assert _FakeAgent.init_kwargs == {}
    assert _FakeAgent.run_prompt == "review this"
    assert result["ok"] is True
    assert result["model"] == "opus5"
    assert result["output"] == "BARE_WORKER_OK"
    assert result["mode"] == "bare"


def test_bare_worker_peer_review_uses_read_only_code_mode(monkeypatch, tmp_path) -> None:
    sentinel_model = object()
    monkeypatch.setattr(bare_module, "Agent", _FakeAgent)
    monkeypatch.setattr(bare_module, "build_model", lambda alias: sentinel_model)

    result = asyncio.run(
        bare_module._run_worker(
            {
                "model": "opus5",
                "prompt": "review this",
                "output_tokens_limit": 123,
                "peer_review": True,
                "workspace_dir": str(tmp_path),
            }
        )
    )

    assert _FakeAgent.init_args == (sentinel_model,)
    instructions = _FakeAgent.init_kwargs["instructions"]
    assert "independent peer reviewer" in str(instructions)
    capabilities = cast(list[object], _FakeAgent.init_kwargs["capabilities"])
    fs = next(cap for cap in capabilities if isinstance(cap, FileSystem))
    assert fs.read_only is True
    assert "**/.env" in fs.denied_patterns
    assert any(isinstance(cap, CodeMode) for cap in capabilities)
    assert _FakeAgent.run_prompt == "review this"
    assert result["ok"] is True
    assert result["mode"] == "peer-review"
