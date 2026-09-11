from __future__ import annotations

import asyncio

import pytest

from gpt_dive.subagent_runtime import MODEL_SPECS, invoke_subagent, model_catalog


def test_model_catalog_is_sanitized_and_complete() -> None:
    expected_models = {
        "opus5",
        "micu-opus5",
        "ds",
        "kimi",
        "glm",
        "grok",
        "vip4",
        "m3",
        "glm-5.3-flash",
        "muse-free",
        "sol",
        "terra",
        "luna",
        "gpt6",
    }
    assert set(MODEL_SPECS) == expected_models
    catalog = model_catalog()
    assert catalog["opus5"]["provider"] == "micu"
    assert catalog["opus5"]["output_tokens_limit"] == 128_000
    assert catalog["micu-opus5"]["provider"] == "micu"
    assert catalog["ds"]["provider"] == "micu-ds"
    assert catalog["kimi"]["provider"] == "micu-kimi"
    assert catalog["glm"]["provider"] == "micu-glm"
    assert catalog["grok"]["provider"] == "micu-grok"
    assert catalog["vip4"]["provider"] == "micu-vip4"
    assert catalog["m3"]["model"] == "MiniMax-M3"
    assert catalog["sol"]["model"] == "gpt-5.6-sol"
    assert catalog["terra"]["model"] == "gpt-5.6-terra"
    assert catalog["luna"]["model"] == "gpt-5.6-luna"
    assert catalog["gpt6"]["provider"] == "openai-codex"
    assert catalog["gpt6"]["model"] == "gpt-6-astra"
    assert "key" not in repr(catalog).lower()


def test_unknown_model_rejected_before_process_launch() -> None:
    with pytest.raises(ValueError, match="unknown model alias"):
        asyncio.run(invoke_subagent(model="nope", task="x", timeout=30.0))
