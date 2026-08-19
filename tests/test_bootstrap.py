from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from gpt_dive import app as app_module


def _write_test_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "bootstrap").mkdir(parents=True)
    (wiki / "workflow" / "pydantic-ai").mkdir(parents=True)
    (wiki / "skills").mkdir()
    (wiki / "bootstrap" / "preload.json").write_text(
        json.dumps(
            {
                "preload_files": [
                    "bootstrap/intro.md",
                    "USER_RULES.md",
                    "workflow/pydantic-ai/README.md",
                    "workflow/pydantic-ai/code-mode.md",
                    "skills/INDEX.md",
                ]
            }
        )
    )
    (wiki / "bootstrap" / "reminder.json").write_text(
        json.dumps(
            {
                "interval": 3,
                "reminder_files": [
                    {"path": "USER_RULES.md", "section": "Reminder"}
                ],
            }
        )
    )
    (wiki / "bootstrap" / "intro.md").write_text("INTRO\nPREVIEW\n")
    (wiki / "USER_RULES.md").write_text(
        "# USER_RULES\n\n## Work\nFULL RULES\n\n## Reminder\nROUTE\nPREVIEW FIRST\n"
    )
    (wiki / "workflow" / "pydantic-ai" / "README.md").write_text("PYDANTIC")
    (wiki / "workflow" / "pydantic-ai" / "code-mode.md").write_text("CODE MODE")
    (wiki / "skills" / "INDEX.md").write_text("SKILLS")
    (wiki / "ERROR_CASE.md").write_text("# ERROR_CASE\nSHOULD NOT BE PRELOADED\n")
    (wiki / "log.md").write_text("RECENT LOG MUST NOT BE PRELOADED")
    return wiki


def test_parse_preload_files_valid() -> None:
    text = '{"preload_files": ["a.md", "b.md"]}'
    assert app_module._parse_preload_files(text) == ["a.md", "b.md"]


def test_parse_preload_files_validation_errors() -> None:
    with pytest.raises(ValueError, match="malformed bootstrap preload JSON"):
        app_module._parse_preload_files("invalid json")

    with pytest.raises(TypeError, match="must be an object"):
        app_module._parse_preload_files('["a.md"]')

    with pytest.raises(ValueError, match="missing 'preload_files' field"):
        app_module._parse_preload_files('{}')

    with pytest.raises(TypeError, match="must be a list"):
        app_module._parse_preload_files('{"preload_files": "a.md"}')

    with pytest.raises(ValueError, match="must not be empty"):
        app_module._parse_preload_files('{"preload_files": []}')

    with pytest.raises(TypeError, match="entries must be strings"):
        app_module._parse_preload_files('{"preload_files": [123]}')

    with pytest.raises(ValueError, match="must not be empty strings"):
        app_module._parse_preload_files('{"preload_files": [""]}')


def test_parse_reminder_config_valid() -> None:
    text = json.dumps(
        {
            "interval": 3,
            "reminder_files": [{"path": "USER_RULES.md", "section": "Reminder"}],
        }
    )
    assert app_module._parse_reminder_config(text) == (
        3,
        [("USER_RULES.md", "Reminder")],
    )


def test_parse_reminder_config_validation_errors() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        app_module._parse_reminder_config('{"interval": 0, "reminder_files": [{}]}')
    with pytest.raises(ValueError, match="non-empty list"):
        app_module._parse_reminder_config('{"interval": 3, "reminder_files": []}')
    with pytest.raises(ValueError, match="file path"):
        app_module._parse_reminder_config(
            '{"interval": 3, "reminder_files": [{"path": "", "section": "Reminder"}]}'
        )


def test_read_bootstrap_packet_exposes_map_and_omits_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = _write_test_wiki(tmp_path)
    monkeypatch.setenv("WIKI_PATH", str(wiki))

    result = app_module._read_bootstrap_packet()

    assert result["warnings"] == []
    assert result["preload_path"] == str(wiki / "bootstrap" / "preload.json")
    assert result["preloaded_files"] == [
        "bootstrap/intro.md",
        "USER_RULES.md",
        "workflow/pydantic-ai/README.md",
        "workflow/pydantic-ai/code-mode.md",
        "skills/INDEX.md",
    ]
    assert "===== BEGIN bootstrap/preload" not in result["stdout"]
    assert "INTRO" in result["stdout"]
    assert "FULL RULES" in result["stdout"]
    assert "PYDANTIC" in result["stdout"]
    assert "CODE MODE" in result["stdout"]
    assert "SKILLS" in result["stdout"]
    assert "SHOULD NOT BE PRELOADED" not in result["stdout"]
    assert "RECENT LOG MUST NOT BE PRELOADED" not in result["stdout"]
    assert "LIVE CODE MODE CAPABILITIES" not in result["stdout"]


def test_periodic_reminder_reads_only_user_rules_reminder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = _write_test_wiki(tmp_path)
    monkeypatch.setenv("WIKI_PATH", str(wiki))

    reminder = app_module._read_periodic_reminder()

    assert reminder == "## Reminder\nROUTE\nPREVIEW FIRST"
    assert "FULL RULES" not in reminder
    assert "ERROR_CASE" not in reminder
    assert "INTRO" not in reminder


def test_bootstrap_public_function_has_no_log_tail_parameter() -> None:
    assert list(inspect.signature(app_module.bootstrap).parameters) == []
