from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import gpt_dive.repo_search as repo_search_module
from gpt_dive.repo_search import _compact_probe_result, search_repo
from gpt_dive.worker_subprocess import WorkerOutcome


def test_compact_probe_result_keeps_only_useful_context(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("def hello(): pass\n")
    data = {
        "results": [
            {
                "file": str(source),
                "lines": [1, 1],
                "code": "def hello(): pass",
                "score": 0.91,
                "owner_qualified_symbol": "hello",
                "language": "python",
                "matches": [{"text": "hello"}],
            }
        ],
        "summary": {"total_tokens": 7},
        "skipped_files": [{"file": "noise.py"}],
    }

    assert _compact_probe_result(data, tmp_path) == {
        "count": 1,
        "total_tokens": 7,
        "results": [
            {
                "file": "src/app.py",
                "lines": [1, 1],
                "code": "def hello(): pass",
                "score": 0.91,
                "symbol": "hello",
                "language": "python",
            }
        ],
    }


def test_search_repo_uses_bounded_worker_and_preserves_timeout_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_worker(command: list[str], **kwargs: object) -> WorkerOutcome:
        captured["command"] = command
        captured.update(kwargs)
        return WorkerOutcome(
            returncode=-15,
            stdout_text="",
            stderr_text="",
            timed_out=True,
            reaped=True,
        )

    monkeypatch.setattr(repo_search_module, "run_bounded_worker", fake_worker)

    result = asyncio.run(search_repo(query="needle", path=str(tmp_path), timeout=3.5))

    assert result == {
        "ok": False,
        "engine": "probe",
        "query": "needle",
        "path": str(tmp_path.resolve()),
        "error": "probe search timed out after 3.5 seconds",
    }
    assert captured["command"][:3] == ["probe", "search", "needle"]
    assert captured["timeout"] == 3.5
    assert captured["grace_seconds"] == 0.0
    assert captured["termination_grace_seconds"] == 2.0
    assert captured["log_label"] == "PROBE SEARCH"


def test_search_repo_reports_unreaped_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_worker(*_args: object, **_kwargs: object) -> WorkerOutcome:
        return WorkerOutcome(None, "", "", timed_out=False, reaped=False)

    monkeypatch.setattr(repo_search_module, "run_bounded_worker", fake_worker)

    result = asyncio.run(search_repo(query="needle", path=str(tmp_path)))

    assert result["ok"] is False
    assert result["error"] == (
        "probe search process group could not be reaped after termination"
    )
