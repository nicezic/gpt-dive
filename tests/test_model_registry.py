from __future__ import annotations

import asyncio

import pytest

from gpt_dive.model_registry import get_model, resolve_model, verify_provider_model


def test_registered_aliases_resolve_to_valid_providers() -> None:
    from gpt_dive.model_registry import MODEL_ALIASES, PROVIDER_ROUTES

    # User-selected aliases and exact models are the contract, not inferred names.
    expected = {
        "astra6": ("openai-codex", "gpt-6-astra"),
        "sol6": ("openai-codex", "gpt-6.1-sol"),
        "terra5": ("openai-codex", "gpt-5.6-terra"),
        "luna6": ("openai-codex", "gpt-6-luna"),
        "opus-5-micu": ("micu", "claude-opus-5"),
        "ds": ("micu-ds", "deepseek-v4-pro-0813"),
        "kimi": ("micu-kimi", "kimi-k3"),
        "glm": ("micu-glm", "glm-5.3"),
        "grok": ("micu-grok", "grok-4.6"),
        "vip4": ("micu-vip4", "deepseek-v4-pro-0813"),
        "m3": ("minimax", "MiniMax-M3"),
        "muse-free": ("opencode-zen", "muse-spark-1.3-contributor-free"),
    }
    assert expected == MODEL_ALIASES
    assert PROVIDER_ROUTES["micu"] == PROVIDER_ROUTES["micu-opus"]
    for alias, (provider, model_name) in expected.items():
        assert resolve_model(alias) == (provider, model_name)
        assert provider in PROVIDER_ROUTES


def test_resolve_model_falls_back_to_provider_default_model() -> None:
    from gpt_dive.model_registry import PROVIDER_ROUTES, resolve_model

    assert resolve_model("micu") == (
        "micu",
        PROVIDER_ROUTES["micu"].default_model,
    )
    assert resolve_model("m3") == ("minimax", "MiniMax-M3")


def test_unknown_model_rejected_before_process_launch() -> None:
    from gpt_dive.subagent_runtime import invoke_subagent

    with pytest.raises(ValueError, match="unknown model alias"):
        asyncio.run(invoke_subagent(alias="nope", task="x", timeout=30.0))


def test_codex_aliases_use_upstream_pydantic_model() -> None:
    from pydantic_ai.models.openai_codex import OpenAICodexModel

    for alias in ("astra6", "sol6", "terra5", "luna6"):
        model = get_model(alias)
        assert isinstance(model, OpenAICodexModel)
        assert model.model_name == resolve_model(alias)[1]


def test_verify_provider_model_reports_missing_model(monkeypatch) -> None:
    from types import SimpleNamespace

    import gpt_dive.model_registry as registry

    def _fake_client(ids):
        async def _agen():
            for model_id in ids:
                yield SimpleNamespace(id=model_id)

        class _Models:
            def list(self):
                return _agen()

        class _Client:
            def __init__(self) -> None:
                self.models = _Models()

        return _Client()

    monkeypatch.setattr(
        registry,
        "_async_client_for_route",
        lambda route: _fake_client(["claude-opus-5", "claude-haiku-4-5-20251001"]),
    )

    present = asyncio.run(registry.verify_provider_model("micu", "claude-opus-5"))
    assert present == {
        "checked": True,
        "exists": True,
        "available": ["claude-opus-5", "claude-haiku-4-5-20251001"],
    }

    missing = asyncio.run(registry.verify_provider_model("micu", "nope-1"))
    assert missing["checked"] is True
    assert missing["exists"] is False


def test_verify_provider_model_soft_skips_on_listing_failure(monkeypatch) -> None:
    import gpt_dive.model_registry as registry

    def _broken_client(_route):
        raise RuntimeError("endpoint unsupported")

    monkeypatch.setattr(registry, "_async_client_for_route", _broken_client)
    result = asyncio.run(registry.verify_provider_model("micu", "claude-opus-5"))
    assert result == {"checked": False, "exists": False, "available": []}


def test_verify_provider_model_skips_unsupported_providers() -> None:
    for provider, name in (("not-a-provider", "x"), ("openai-codex", "gpt-6-astra")):
        result = asyncio.run(verify_provider_model(provider, name))
        assert result == {"checked": False, "exists": False, "available": []}


def test_opencode_zen_free_alias_uses_native_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.models.openai import OpenAIResponsesModel

    from gpt_dive.model_registry import PROVIDER_ROUTES

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-opencode-key")

    muse = get_model("muse-free")

    assert isinstance(muse, OpenAIResponsesModel)
    assert muse.model_name == "muse-spark-1.3-contributor-free"
    assert PROVIDER_ROUTES["opencode-zen"].base_url == "https://opencode.ai/zen/v1"
    assert "opencode-go" not in PROVIDER_ROUTES
