from __future__ import annotations

import io
import json
import sys
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.exceptions import ModelHTTPError

import gpt_dive.model_call_worker as model_call_worker
import gpt_dive.subagent_worker as subagent_worker


@pytest.mark.parametrize(
    ("module", "function"),
    [(model_call_worker, "_run_worker"), (subagent_worker, "_run")],
)
def test_model_http_error_survives_worker_boundary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    module: object, function: str,
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"alias":"test"}'))
    monkeypatch.setattr(
        module, function,
        AsyncMock(side_effect=ModelHTTPError(429, "test-model")),
    )
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"]["category"] == "model"
    assert result["error"]["code"] == "ModelHTTPError"
    assert result["error"]["http_status"] == 429
