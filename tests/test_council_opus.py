from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from gpt_dive.council import (
    advance_context,
    append_turn,
    context_commit,
    initialize_council,
    run_opus_turn,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def test_opus_success_commits_response_and_advances_only_opus_cursor(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Why\n\nDecide carefully")
    captured: dict[str, Any] = {}

    async def fake_invoke(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"ok": True, "output": "Independent response", "usage": {"requests": 1}}

    result = asyncio.run(run_opus_turn(repo, "Question", invoke=fake_invoke))

    assert result["ok"] is True
    assert result["output"] == "Independent response"
    assert context_commit(repo, "OPUS") == result["response_commit"]
    assert context_commit(repo, "SOL") == initialized["initial_commit"]
    assert (
        _git(repo, "rev-list", "--count", f"{initialized['initial_commit']}..HEAD")
        == "2"
    )
    assert (repo / "chat.md").read_text(encoding="utf-8") == (
        "# USER\n\nQuestion\n\n---\n# OPUS\n\nIndependent response\n\n---\n"
    )
    assert captured["alias"] == "opus-5-micu"
    assert captured["workspace_dir"] is None
    assert "# USER\n\nQuestion" in captured["task"]
    assert "# Why\n\nDecide carefully" in captured["task"]


def test_opus_failure_keeps_user_commit_and_cursor_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")

    async def fake_invoke(**kwargs: Any) -> dict[str, Any]:
        return {"ok": False, "error": "provider unavailable"}

    result = asyncio.run(run_opus_turn(repo, "Question", invoke=fake_invoke))

    assert result["ok"] is False
    assert result["error"] == "provider unavailable"
    assert context_commit(repo, "OPUS") == initialized["initial_commit"]
    assert _git(repo, "rev-parse", "HEAD") == result["user_commit"]
    assert (repo / "chat.md").read_text(
        encoding="utf-8"
    ) == "# USER\n\nQuestion\n\n---\n"


def test_opus_receives_prior_synchronized_context_plus_only_new_unread_suffix(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    first_user = append_turn(repo, "USER", "First question")
    first_opus = append_turn(repo, "OPUS", "First answer")
    advance_context(repo, "OPUS", first_opus["commit"])
    append_turn(repo, "SOL", "Intervening SOL view")
    captured: dict[str, Any] = {}

    async def fake_invoke(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"ok": True, "output": "Second answer"}

    result = asyncio.run(run_opus_turn(repo, "Second question", invoke=fake_invoke))

    assert result["ok"] is True
    task = str(captured["task"])
    prior, unread = task.split("## New unread Council transcript\n", maxsplit=1)
    assert "First question" in prior
    assert "First answer" in prior
    assert "Intervening SOL view" not in prior
    assert "Intervening SOL view" in unread
    assert "Second question" in unread
    assert "First answer" not in unread
    assert context_commit(repo, "OPUS") == result["response_commit"]
    assert first_user["commit"] != result["user_commit"]


def test_opus_retry_reuses_existing_unread_user_turn(tmp_path: Path) -> None:
    from gpt_dive.council import retry_opus_turn

    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")
    attempts = 0

    async def fake_invoke(**kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"ok": False, "error": "temporary failure"}
        return {"ok": True, "output": "Recovered"}

    failed = asyncio.run(run_opus_turn(repo, "One user turn", invoke=fake_invoke))
    failed_head = _git(repo, "rev-parse", "HEAD")
    retried = asyncio.run(retry_opus_turn(repo, invoke=fake_invoke))

    assert failed["ok"] is False
    assert failed_head == failed["user_commit"]
    assert retried["ok"] is True
    assert (
        _git(repo, "rev-list", "--count", f"{initialized['initial_commit']}..HEAD")
        == "2"
    )
    assert (repo / "chat.md").read_text(encoding="utf-8") == (
        "# USER\n\nOne user turn\n\n---\n# OPUS\n\nRecovered\n\n---\n"
    )
    assert context_commit(repo, "OPUS") == retried["response_commit"]
