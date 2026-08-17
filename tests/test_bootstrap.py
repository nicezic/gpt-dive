from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from gpt_dive import app as app_module


def _write_test_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "bootstrap").mkdir(parents=True)
    (wiki / "user").mkdir()
    (wiki / "bootstrap" / "preload.md").write_text(
        """# Preload Map

## Preload files

1. `bootstrap/intro.md`
2. `user/profile.md`
3. `EORROR_CASE.md`

## On demand

- `log.md`
"""
    )
    (wiki / "bootstrap" / "intro.md").write_text(
        "INTRO\n\n## Code Mode capability index\nINDEX\n\n"
        "## AI Reminder\nREMINDER\n\n## Dive call preview\nPREVIEW\n"
    )
    (wiki / "user" / "profile.md").write_text("PROFILE")
    (wiki / "EORROR_CASE.md").write_text(
        "# EORROR_CASE\n\n## Tool / command mistakes\n- sample | 1 | 260817-000000\n"
        "\n## 기타 지시사항 이행 오류\n사용자가 추가 요청한 항목만 기록.\n"
    )
    (wiki / "log.md").write_text("RECENT LOG MUST NOT BE PRELOADED")
    return wiki


def test_parse_preload_files_reads_only_preload_section() -> None:
    text = """## Preload files

1. `a.md`
2. `b.md`

## On demand

1. `c.md`
"""
    assert app_module._parse_preload_files(text) == ["a.md", "b.md"]


def test_read_bootstrap_packet_exposes_map_and_omits_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = _write_test_wiki(tmp_path)
    monkeypatch.setenv("WIKI_PATH", str(wiki))

    result = app_module._read_bootstrap_packet()

    assert result["warnings"] == []
    assert result["preload_path"] == str(wiki / "bootstrap" / "preload.md")
    assert result["preloaded_files"] == [
        "bootstrap/intro.md",
        "user/profile.md",
        "EORROR_CASE.md",
    ]
    assert "===== BEGIN bootstrap/preload.md =====" in result["stdout"]
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
        "# EORROR_CASE\n\n## Tool / command mistakes\n"
        "- sample | 1 | 260817-000000\n\n"
        "## 기타 지시사항 이행 오류\n사용자가 추가 요청한 항목만 기록."
    )
    assert "PREVIEW" not in reminder
    assert "INTRO" not in reminder


def test_bootstrap_public_function_has_no_log_tail_parameter() -> None:
    assert list(inspect.signature(app_module.bootstrap).parameters) == []
