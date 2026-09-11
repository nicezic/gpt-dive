from __future__ import annotations

import asyncio

import pytest

from gpt_dive.model_registry import build_model, verify_provider_model


def test_codex_alias_uses_upstream_pydantic_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pydantic_ai.models.openai_codex as codex_model

    captured: dict[str, str] = {}

    class _FakeCodexModel:
        def __init__(self, model_name: str) -> None:
            captured["model_name"] = model_name

    monkeypatch.setattr(codex_model, "OpenAICodexModel", _FakeCodexModel)

    build_model("sol")
    assert captured == {"model_name": "gpt-5.6-sol"}


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


def test_verify_provider_model_skips_unknown_provider() -> None:
    from gpt_dive.model_registry import verify_provider_model

    result = asyncio.run(verify_provider_model("not-a-provider", "x"))
    assert result == {"checked": False, "exists": False, "available": []}

def test_verify_provider_model_skips_unlisted_codex_provider() -> None:
    result = asyncio.run(verify_provider_model("openai-codex", "gpt-6-astra"))
    assert result == {"checked": False, "exists": False, "available": []}


def test_opencode_aliases_use_native_openai_interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

    from gpt_dive.model_registry import PROVIDER_ROUTES

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-opencode-key")

    glm = build_model("glm-5.3-flash")
    muse = build_model("muse-free")

    assert isinstance(glm, OpenAIChatModel)
    assert glm.model_name == "glm-5.3-flash"
    assert PROVIDER_ROUTES["opencode-go"].base_url == "https://opencode.ai/zen/go/v1"
    assert isinstance(muse, OpenAIResponsesModel)
    assert muse.model_name == "muse-spark-1.3-contributor-free"
    assert PROVIDER_ROUTES["opencode-zen"].base_url == "https://opencode.ai/zen/v1"
