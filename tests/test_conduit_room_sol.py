from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gpt_dive.conduit.room import (
    CouncilProtocolError,
    append_turn,
    context_commit,
    emit_sol_response,
    initialize_council,
    retry_sol_turn,
    run_sol_turn,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class EmittingBridge:
    def __init__(self, repo: Path, output: str = "SOL answer") -> None:
        self.repo = repo
        self.output = output
        self.messages: list[tuple[str, str]] = []

    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        self.messages.append((url, message))
        expected = _git(self.repo, "rev-parse", "HEAD")
        emit_sol_response(self.repo, self.output, expected_head=expected)
        return {"ok": True, "url": url}


class FailingBridge:
    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        raise RuntimeError("bridge unavailable")


class SilentBridge:
    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        return {"ok": True, "url": url}


class MustNotSendBridge:
    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        raise AssertionError("late-response recovery must not resend browser input")


def test_sol_success_sends_only_unread_context_and_advances_sol_cursor(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")
    append_turn(repo, "OPUS", "Intervening OPUS view")
    bridge = EmittingBridge(repo)

    result = asyncio.run(
        run_sol_turn(
            repo,
            "Question for SOL",
            url="https://chatgpt.com/c/test",
            bridge=bridge,
            response_timeout=1,
            poll_interval=0.001,
        )
    )

    assert result["ok"] is True
    assert context_commit(repo, "SOL") == result["response_commit"]
    assert context_commit(repo, "OPUS") == initialized["initial_commit"]
    assert (
        _git(repo, "rev-list", "--count", f"{initialized['initial_commit']}..HEAD")
        == "3"
    )
    _, payload = bridge.messages[0]
    unread = payload.split("## New unread Council transcript\n", maxsplit=1)[1]
    assert "Intervening OPUS view" in unread
    assert "Question for SOL" in unread
    assert "expected_head=" in payload
    assert (
        (repo / "chat.md")
        .read_text(encoding="utf-8")
        .endswith("# SOL\n\nSOL answer\n\n---\n")
    )


def test_sol_input_failure_keeps_user_commit_and_cursor_for_retry(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")

    failed = asyncio.run(
        run_sol_turn(
            repo,
            "One user turn",
            url="https://chatgpt.com/c/test",
            bridge=FailingBridge(),
            response_timeout=1,
        )
    )

    assert failed["ok"] is False
    assert "bridge unavailable" in failed["error"]
    assert context_commit(repo, "SOL") == initialized["initial_commit"]
    assert _git(repo, "rev-parse", "HEAD") == failed["user_commit"]

    recovered = asyncio.run(
        retry_sol_turn(
            repo,
            url="https://chatgpt.com/c/test",
            bridge=EmittingBridge(repo, "Recovered"),
            response_timeout=1,
            poll_interval=0.001,
        )
    )

    assert recovered["ok"] is True
    assert (
        _git(repo, "rev-list", "--count", f"{initialized['initial_commit']}..HEAD")
        == "2"
    )
    assert (repo / "chat.md").read_text(encoding="utf-8") == (
        "# USER\n\nOne user turn\n\n---\n# SOL\n\nRecovered\n\n---\n"
    )


def test_sol_timeout_keeps_cursor_and_late_response_is_reconciled_without_resend(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")

    failed = asyncio.run(
        run_sol_turn(
            repo,
            "Slow turn",
            url="https://chatgpt.com/c/test",
            bridge=SilentBridge(),
            response_timeout=0.01,
            poll_interval=0.001,
        )
    )

    assert failed["ok"] is False
    assert "did not commit" in failed["error"]
    assert context_commit(repo, "SOL") == initialized["initial_commit"]
    emit_sol_response(repo, "Late answer", expected_head=failed["user_commit"])

    recovered = asyncio.run(
        retry_sol_turn(
            repo,
            url="https://chatgpt.com/c/test",
            bridge=MustNotSendBridge(),
        )
    )

    assert recovered["ok"] is True
    assert recovered["recovered_late_response"] is True
    assert context_commit(repo, "SOL") == recovered["response_commit"]


def test_council_emit_expected_head_rejects_stale_or_duplicate_sol_response(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    user = append_turn(repo, "USER", "Question")

    first = emit_sol_response(repo, "First answer", expected_head=user["commit"])

    with pytest.raises(CouncilProtocolError, match="HEAD changed"):
        emit_sol_response(repo, "Duplicate answer", expected_head=user["commit"])

    assert _git(repo, "rev-parse", "HEAD") == first["commit"]
    assert (repo / "chat.md").read_text(encoding="utf-8").count("# SOL\n") == 1
