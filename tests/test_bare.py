from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import ClassVar, cast

from pydantic_ai import CachePoint
from pydantic_ai_harness import CodeMode, FileSystem

import gpt_dive.bare as bare_module


class _FakeResult:
    output = "BARE_WORKER_OK"
    usage = SimpleNamespace(requests=1, input_tokens=7, output_tokens=5)
    response = SimpleNamespace(finish_reason="stop", provider_details={"finish_reason": "end_turn"})


class _FakeAgent:
    init_args: ClassVar[tuple[object, ...]] = ()
    init_kwargs: ClassVar[dict[str, object]] = {}
    run_prompt: ClassVar[object] = ""

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


def test_kunavo_peer_review_inserts_explicit_cache_point(monkeypatch, tmp_path) -> None:
    sentinel_model = object()
    monkeypatch.setattr(bare_module, "Agent", _FakeAgent)
    monkeypatch.setattr(bare_module, "build_model", lambda alias: sentinel_model)

    prompt = "STABLE BASE" + bare_module._PEER_CACHE_BREAK + "ROUND 2 DELTA"
    result = asyncio.run(
        bare_module._run_worker(
            {
                "model": "kunavo-opus5",
                "prompt": prompt,
                "output_tokens_limit": 123,
                "peer_review": True,
                "workspace_dir": str(tmp_path),
            }
        )
    )

    run_prompt = _FakeAgent.run_prompt
    assert isinstance(run_prompt, list)
    assert run_prompt[0] == "STABLE BASE"
    assert isinstance(run_prompt[1], CachePoint)
    assert run_prompt[1].ttl == "5m"
    assert run_prompt[2] == "ROUND 2 DELTA"
    model_settings = _FakeAgent.init_kwargs["model_settings"]
    assert model_settings == {"max_tokens": 123}
    assert result["model"] == "kunavo-opus5"
    assert result["provider"] == "kunavo"
    assert result["finish_reason"] == "stop"
    assert result["provider_finish_reason"] == "end_turn"
    assert result["truncated"] is False


def test_peer_review_marks_length_finish_as_truncated(monkeypatch, tmp_path) -> None:
    sentinel_model = object()
    monkeypatch.setattr(bare_module, "Agent", _FakeAgent)
    monkeypatch.setattr(bare_module, "build_model", lambda alias: sentinel_model)
    original_response = _FakeResult.response
    _FakeResult.response = SimpleNamespace(
        finish_reason="length", provider_details={"finish_reason": "max_tokens"}
    )
    try:
        result = asyncio.run(
            bare_module._run_worker(
                {
                    "model": "kunavo-opus5",
                    "prompt": "STABLE" + bare_module._PEER_CACHE_BREAK + "DELTA",
                    "output_tokens_limit": 20_000,
                    "peer_review": True,
                    "workspace_dir": str(tmp_path),
                }
            )
        )
    finally:
        _FakeResult.response = original_response

    assert result["ok"] is False
    assert result["finish_reason"] == "length"
    assert result["provider_finish_reason"] == "max_tokens"
    assert result["truncated"] is True
