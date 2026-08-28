from __future__ import annotations

import asyncio
import sys

import pytest

from gpt_dive.model_registry import build_model


def test_registry_import_does_not_load_codex_compat_for_non_codex_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    had_codex = sys.modules.pop("gpt_dive.openai_codex", None)
    try:
        assert "gpt_dive.openai_codex" not in sys.modules
        build_model("m3")
        assert "gpt_dive.openai_codex" not in sys.modules
    finally:
        if had_codex is not None:
            sys.modules["gpt_dive.openai_codex"] = had_codex


def test_codex_alias_uses_local_compat_layer() -> None:
    from gpt_dive.openai_codex import OpenAICodexResponsesModel

    model = build_model("sol")
    assert isinstance(model, OpenAICodexResponsesModel)
    assert model.system == "openai-codex"


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

    present = asyncio.run(registry.verify_provider_model("aiapiflow", "claude-opus-5"))
    assert present == {
        "checked": True,
        "exists": True,
        "available": ["claude-opus-5", "claude-haiku-4-5-20251001"],
    }

    missing = asyncio.run(registry.verify_provider_model("aiapiflow", "nope-1"))
    assert missing["checked"] is True
    assert missing["exists"] is False


def test_verify_provider_model_soft_skips_on_listing_failure(monkeypatch) -> None:
    import gpt_dive.model_registry as registry

    def _broken_client(_route):
        raise RuntimeError("endpoint unsupported")

    monkeypatch.setattr(registry, "_async_client_for_route", _broken_client)
    result = asyncio.run(registry.verify_provider_model("aiapiflow", "claude-opus-5"))
    assert result == {"checked": False, "exists": False, "available": []}


def test_verify_provider_model_skips_unknown_provider() -> None:
    from gpt_dive.model_registry import verify_provider_model

    result = asyncio.run(verify_provider_model("not-a-provider", "x"))
    assert result == {"checked": False, "exists": False, "available": []}
