from __future__ import annotations

import os
import subprocess
import sys

from gpt_dive.model_registry import build_model
from gpt_dive.openai_codex import OpenAICodexResponsesModel


def test_codex_alias_uses_local_compat_layer() -> None:
    model = build_model("sol")
    assert isinstance(model, OpenAICodexResponsesModel)
    assert model.system == "openai-codex"


def test_registry_import_does_not_load_codex_compat_for_non_codex_paths() -> None:
    env = dict(os.environ)
    env["MINIMAX_API_KEY"] = "test-key"
    code = (
        "import sys; "
        "from gpt_dive.model_registry import build_model; "
        "assert 'gpt_dive.openai_codex' not in sys.modules; "
        "build_model('m3'); "
        "assert 'gpt_dive.openai_codex' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
