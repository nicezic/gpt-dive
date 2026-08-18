from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from gpt_dive import app as app_module


def _write_test_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "bootstrap").mkdir(parents=True)
    (wiki / "user").mkdir()
    (wiki / "bootstrap" / "preload.json").write_text(
        json.dumps(
            {
                "preload_files": [
                    "bootstrap/intro.md",
                    "user/profile.md",
                    "ERROR_CASE.md",
                ]
            }
        )
    )
    (wiki / "bootstrap" / "intro.md").write_text(
        "INTRO\n\n## Code Mode capability index\nINDEX\n\n"
        "## AI Reminder\nREMINDER\n\n## Dive call preview\nPREVIEW\n"
    )
    (wiki / "user" / "profile.md").write_text("PROFILE")
    (wiki / "ERROR_CASE.md").write_text(
        "# ERROR_CASE\n\n## Tool / command mistakes\n- sample | 1 | 260817-000000\n"
        "\n## 기타 지시사항 이행 오류\n사용자가 추가 요청한 항목만 기록.\n"
    )
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
        "user/profile.md",
        "ERROR_CASE.md",
    ]
    assert "===== BEGIN bootstrap/preload" not in result["stdout"]
    assert "INTRO" in result["stdout"]
    assert "PROFILE" in result["stdout"]
    assert "- sample | 1 | 260817-000000" in result["stdout"]
    assert "RECENT LOG MUST NOT BE PRELOADED" not in result["stdout"]
    assert "LIVE CODE MODE CAPABILITIES" not in result["stdout"]


def test_periodic_reminder_reads_compact_intro_sections_and_error_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = _write_test_wiki(tmp_path)
    monkeypatch.setenv("WIKI_PATH", str(wiki))

    reminder = app_module._read_periodic_reminder()

    assert reminder == (
        "## Code Mode capability index\nINDEX\n\n"
        "## AI Reminder\nREMINDER\n\n"
        "# ERROR_CASE\n\n## Tool / command mistakes\n"
        "- sample | 1 | 260817-000000\n\n"
        "## 기타 지시사항 이행 오류\n사용자가 추가 요청한 항목만 기록."
    )
    assert "PREVIEW" not in reminder
    assert "INTRO" not in reminder


def test_bootstrap_public_function_has_no_log_tail_parameter() -> None:
    assert list(inspect.signature(app_module.bootstrap).parameters) == []
