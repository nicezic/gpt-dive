from __future__ import annotations

import asyncio

import pytest

from subagent_runtime import MODEL_SPECS, invoke_subagent, model_catalog


def test_model_catalog_is_sanitized_and_complete() -> None:
    assert set(MODEL_SPECS) == {'opus5', 'm3', 'terra', 'luna'}
    catalog = model_catalog()
    assert catalog['opus5']['provider'] == 'aiapiflow'
    assert catalog['m3']['model'] == 'MiniMax-M3'
    assert catalog['terra']['model'] == 'gpt-5.6-terra'
    assert catalog['luna']['model'] == 'gpt-5.6-luna'
    assert 'key' not in repr(catalog).lower()


def test_unknown_model_rejected_before_process_launch() -> None:
    with pytest.raises(ValueError, match='unknown subagent model alias'):
        asyncio.run(invoke_subagent(model='nope', task='x'))
