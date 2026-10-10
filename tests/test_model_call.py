from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest
from pydantic_ai import Agent, CachePoint, UsageLimits
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import CodeMode, FileSystem

import gpt_dive.model_call as model_call_module


class _FakeResult:
    output = "BARE_WORKER_OK"
    usage = SimpleNamespace(requests=1, input_tokens=7, output_tokens=5)
    response = SimpleNamespace(
        finish_reason="stop", provider_details={"finish_reason": "end_turn"}
    )


class _FakeAgent:
    init_args: ClassVar[tuple[object, ...]] = ()
    init_kwargs: ClassVar[dict[str, object]] = {}
    run_prompt: ClassVar[object] = ""
    run_kwargs: ClassVar[dict[str, object]] = {}

    def __init__(self, *args, **kwargs) -> None:
        type(self).init_args = args
        type(self).init_kwargs = kwargs

    async def run(self, prompt: str, **kwargs):
        type(self).run_prompt = prompt
        type(self).run_kwargs = kwargs
        return _FakeResult()


def test_credentialed_workers_keep_launch_and_response_contract(monkeypatch) -> None:
    from gpt_dive import subagent_runtime
    from gpt_dive.worker_subprocess import WorkerOutcome

    observed = []

    async def fake_worker(command, *, stdin_payload, env, timeout, log_label):
        observed.append((command, json.loads(stdin_payload), env, timeout, log_label))
        return WorkerOutcome(0, '{"ok": true}', "worker diagnostics", False, True)

    monkeypatch.setattr(model_call_module, "run_bounded_worker", fake_worker)
    monkeypatch.setattr(subagent_runtime, "run_bounded_worker", fake_worker)

    peer = asyncio.run(
        model_call_module.invoke_model_call(
            alias="terra5", prompt="review", timeout=12.0, peer_review=True
        )
    )
    subagent = asyncio.run(
        subagent_runtime.invoke_subagent(alias="terra5", task="code", timeout=12.0)
    )
    assert peer["worker_stderr"] == subagent["worker_stderr"] == "worker diagnostics"
    assert [call[4] for call in observed] == ["MODEL_CALL", "SUBAGENT"]
    assert [
        call[1]["model"] if "model" in call[1] else call[1]["model_name"]
        for call in observed
    ] == [
        "gpt-5.6-terra",
        "gpt-5.6-terra",
    ]
    for command, _, env, timeout, _ in observed:
        assert command[1:4] == ["run", "ai", "--"]
        assert command[command.index("-m") + 1].startswith("gpt_dive.")
        assert env["PATH"]
        assert timeout == 12.0
    assert observed[0][0][-1] == "--worker"


def test_model_call_worker_builds_agent_without_tools_or_capabilities(
    monkeypatch,
) -> None:
    sentinel_model = object()
    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(model_call_module, "get_model", lambda alias: sentinel_model)

    result = asyncio.run(
        model_call_module._run_worker(
            {
                "model": "opus-5-micu",
                "prompt": "review this",
                "output_tokens_limit": 123,
            }
        )
    )

    assert _FakeAgent.init_args == (sentinel_model,)
    assert _FakeAgent.init_kwargs == {}
    assert _FakeAgent.run_prompt == "review this"
    usage_limits = cast(UsageLimits, _FakeAgent.run_kwargs["usage_limits"])
    assert usage_limits.output_tokens_limit == 123
    assert result["ok"] is True
    assert result["model"] == "opus-5-micu"
    assert result["output"] == "BARE_WORKER_OK"
    assert result["mode"] == "model-call"


def test_model_call_worker_can_disable_anthropic_thinking(monkeypatch) -> None:
    sentinel_model = object()
    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(model_call_module, "get_model", lambda alias: sentinel_model)

    result = asyncio.run(
        model_call_module._run_worker(
            {
                "model": "m3",
                "prompt": "return JSON",
                "output_tokens_limit": 123,
                "anthropic_thinking": "disabled",
            }
        )
    )

    assert _FakeAgent.init_args == (sentinel_model,)
    assert _FakeAgent.init_kwargs["model_settings"] == {
        "anthropic_thinking": {"type": "disabled"}
    }
    assert result["ok"] is True


def test_peer_review_uses_provider_and_exact_model(monkeypatch, tmp_path) -> None:
    sentinel_model = object()
    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(
        model_call_module,
        "get_model",
        lambda model, provider=None: sentinel_model,
    )

    result = asyncio.run(
        model_call_module._run_worker(
            {
                "provider": "micu",
                "model": "claude-opus-5",
                "prompt": "review this",
                "peer_review": True,
                "workspace_dir": str(tmp_path),
            }
        )
    )

    assert _FakeAgent.init_args == (sentinel_model,)
    instructions = _FakeAgent.init_kwargs["instructions"]
    assert "independent peer reviewer" in str(instructions)
    assert "host will persist it to peer_answer.md" in str(instructions)
    capabilities = cast(list[object], _FakeAgent.init_kwargs["capabilities"])
    fs = next(cap for cap in capabilities if isinstance(cap, FileSystem))
    assert fs.read_only is False
    assert "**/.env" in fs.denied_patterns
    assert any(isinstance(cap, CodeMode) for cap in capabilities)
    assert "model_settings" not in _FakeAgent.init_kwargs
    assert _FakeAgent.run_kwargs["usage_limits"] is None
    assert _FakeAgent.run_prompt == "review this"
    assert result["ok"] is True
    assert result["mode"] == "peer-review"
    assert result["provider"] == "micu"
    assert result["model_name"] == "claude-opus-5"


def test_micu_peer_review_inserts_explicit_cache_point(monkeypatch, tmp_path) -> None:
    sentinel_model = object()
    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(
        model_call_module,
        "get_model",
        lambda model, provider=None: sentinel_model,
    )

    prompt = "STABLE BASE" + model_call_module._PEER_CACHE_BREAK + "ROUND 2 DELTA"
    result = asyncio.run(
        model_call_module._run_worker(
            {
                "provider": "micu",
                "model": "claude-opus-5",
                "prompt": prompt,
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
    assert result["model"] == "claude-opus-5"
    assert result["provider"] == "micu"
    assert result["finish_reason"] == "stop"
    assert result["provider_finish_reason"] == "end_turn"
    assert result["truncated"] is False


def test_peer_review_marks_length_finish_as_truncated(monkeypatch, tmp_path) -> None:
    sentinel_model = object()
    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(
        model_call_module,
        "get_model",
        lambda model, provider=None: sentinel_model,
    )
    original_response = _FakeResult.response
    _FakeResult.response = SimpleNamespace(
        finish_reason="length", provider_details={"finish_reason": "max_tokens"}
    )
    try:
        result = asyncio.run(
            model_call_module._run_worker(
                {
                    "provider": "micu",
                    "model": "claude-opus-5",
                    "prompt": "STABLE" + model_call_module._PEER_CACHE_BREAK + "DELTA",
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


def test_peer_review_worker_rejects_model_missing_from_provider(monkeypatch) -> None:

    def _fail_agent(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Agent must not be built for an unknown model")

    async def _fake_verify(
        provider: str, model_name: str, **_kwargs: object
    ) -> dict[str, object]:
        return {"checked": True, "exists": False, "available": ["claude-opus-5"]}

    monkeypatch.setattr(model_call_module, "Agent", _fail_agent)
    monkeypatch.setattr(model_call_module, "verify_provider_model", _fake_verify)

    result = asyncio.run(
        model_call_module._run_worker(
            {
                "peer_review": True,
                "provider": "micu",
                "model": "nope-1",
                "prompt": "review this",
                "workspace_dir": "/tmp/opencode",
            }
        )
    )

    assert result["ok"] is False
    assert result["mode"] == "peer-review"
    assert "not offered by provider" in result["error"]
    assert result["available_models"] == ["claude-opus-5"]


def test_peer_review_worker_resolves_provider_default_model(
    monkeypatch, tmp_path
) -> None:
    sentinel_model = object()
    listing_calls: list[str] = []

    async def _fail_verify(
        provider: str, model_name: str, **_kwargs: object
    ) -> dict[str, object]:
        listing_calls.append(model_name)
        return {"checked": True, "exists": True, "available": []}

    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(
        model_call_module,
        "get_model",
        lambda model, provider=None: sentinel_model,
    )
    monkeypatch.setattr(model_call_module, "verify_provider_model", _fail_verify)

    result = asyncio.run(
        model_call_module._run_worker(
            {
                "peer_review": True,
                "provider": "micu",
                "model": None,
                "prompt": "review this",
                "workspace_dir": str(tmp_path),
            }
        )
    )

    assert result["ok"] is True
    assert result["model_name"] == "claude-opus-5"
    assert listing_calls == []


def test_peer_review_worker_rejects_unknown_provider(tmp_path) -> None:
    result = asyncio.run(
        model_call_module._run_worker(
            {
                "peer_review": True,
                "provider": "not-a-provider",
                "model": None,
                "prompt": "review this",
                "workspace_dir": str(tmp_path),
            }
        )
    )

    assert result["ok"] is False
    assert "registered providers" in result["error"]


def test_peer_review_supports_openai_codex_exact_model(monkeypatch, tmp_path) -> None:
    from pydantic_ai.models.openai_codex import OpenAICodexModel

    async def _verify(
        provider: str, model: str, **_kwargs: object
    ) -> dict[str, object]:
        assert (provider, model) == ("openai-codex", "gpt-6-astra")
        return {"checked": True, "exists": True, "available": [model]}

    monkeypatch.setattr(model_call_module, "Agent", _FakeAgent)
    monkeypatch.setattr(model_call_module, "verify_provider_model", _verify)

    result = asyncio.run(
        model_call_module._run_worker(
            {
                "peer_review": True,
                "provider": "openai-codex",
                "model": "gpt-6-astra",
                "prompt": "review this",
                "workspace_dir": str(tmp_path),
            }
        )
    )

    model = _FakeAgent.init_args[0]
    assert isinstance(model, OpenAICodexModel)
    assert model.model_name == "gpt-6-astra"
    assert "model_settings" not in _FakeAgent.init_kwargs
    assert _FakeAgent.run_kwargs["usage_limits"] is None
    assert result["ok"] is True


def test_openai_codex_peer_review_requires_exact_model(tmp_path) -> None:
    result = asyncio.run(
        model_call_module._run_worker(
            {
                "peer_review": True,
                "provider": "openai-codex",
                "model": None,
                "prompt": "review this",
                "workspace_dir": str(tmp_path),
            }
        )
    )

    assert result["ok"] is False
    assert "model is required" in result["error"]


def test_peer_review_read_is_bounded_by_output_bytes(tmp_path) -> None:
    (tmp_path / "large.txt").write_text(("x" * 80 + "\n") * 4000)
    capabilities = model_call_module._build_peer_review_capabilities(str(tmp_path))
    filesystem = next(cap for cap in capabilities if isinstance(cap, FileSystem))
    toolset = cast(Any, filesystem.get_toolset())

    result = asyncio.run(
        toolset.read_file("large.txt", workspace=LocalWorkspaceBackend(tmp_path))
    )

    assert "[large.txt | 4000 lines" in result
    assert "to continue reading" in result
    # header + notice ride above the body budget
    assert len(result.encode("utf-8")) <= 256 * 1024 + 1024


def test_peer_review_workspace_attached_for_real_agent(tmp_path) -> None:
    capabilities = model_call_module._build_peer_review_capabilities(str(tmp_path))
    assert isinstance(capabilities[0], LocalWorkspace)
    assert str(capabilities[0].working_dir) == str(tmp_path)
    asyncio.run(
        Agent(TestModel(call_tools=[]), capabilities=capabilities).run("offline")
    )
    (tmp_path / ".env").write_text("secret")
    filesystem = next(cap for cap in capabilities if isinstance(cap, FileSystem))
    toolset = cast(Any, filesystem.get_toolset())
    with pytest.raises(ModelRetry, match="denied by pattern"):
        asyncio.run(
            toolset.read_file(".env", workspace=LocalWorkspaceBackend(tmp_path))
        )
