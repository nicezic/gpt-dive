from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gpt_dive.conduit.room import (
    CouncilProtocolError,
    advance_context,
    append_turn,
    context_commit,
    emit_sol_response,
    initialize_council,
    transcript_suffix,
    unread_transcript,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit_chat(repo: Path, message: str) -> str:
    _git(repo, "add", "chat.md")
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Council Test",
            "-c",
            "user.email=council-test@example.invalid",
            "commit",
            "-q",
            "-m",
            message,
            "--",
            "chat.md",
        ],
        check=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def test_initialize_council_sets_both_context_refs_to_initial_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "council"

    result = initialize_council(repo, "# Why\n\nShared room")

    initial = result["initial_commit"]
    assert (repo / "init.md").read_text(encoding="utf-8") == "# Why\n\nShared room\n"
    assert (repo / "chat.md").read_text(encoding="utf-8") == ""
    assert context_commit(repo, "SOL") == initial
    assert context_commit(repo, "OPUS") == initial
    assert _git(repo, "status", "--porcelain") == ""


def test_each_turn_appends_one_block_and_one_commit(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    initial = _git(repo, "rev-parse", "HEAD")

    user = append_turn(repo, "USER", "Question")
    sol = append_turn(repo, "SOL", "Answer")
    opus = append_turn(repo, "OPUS", "Challenge")

    assert _git(repo, "rev-list", "--count", f"{initial}..HEAD") == "3"
    assert user["commit"] != sol["commit"] != opus["commit"]
    assert (repo / "chat.md").read_text(encoding="utf-8") == (
        "# USER\n\nQuestion\n\n---\n"
        "# SOL\n\nAnswer\n\n---\n"
        "# OPUS\n\nChallenge\n\n---\n"
    )
    assert _git(repo, "status", "--porcelain") == ""


def test_unread_transcript_returns_pure_chronological_suffix(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")
    user = append_turn(repo, "USER", "First")
    append_turn(repo, "OPUS", "Second")

    assert unread_transcript(repo, "SOL") == (
        "# USER\n\nFirst\n\n---\n# OPUS\n\nSecond\n\n---\n"
    )

    advance_context(repo, "SOL", user["commit"])
    assert unread_transcript(repo, "SOL") == "# OPUS\n\nSecond\n\n---\n"
    assert transcript_suffix(repo, initialized["initial_commit"], "HEAD").startswith(
        "# USER"
    )


def test_append_turn_rejects_dirty_transcript(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    append_turn(repo, "USER", "Committed")
    chat = repo / "chat.md"
    chat.write_text(
        chat.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8"
    )
    before = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(CouncilProtocolError, match="uncommitted changes"):
        append_turn(repo, "SOL", "Must not absorb dirty text")

    assert _git(repo, "rev-parse", "HEAD") == before
    assert chat.read_text(encoding="utf-8").endswith("manual edit\n")


def test_non_append_transcript_mutation_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    first = append_turn(repo, "USER", "Original")
    append_turn(repo, "SOL", "Response")

    chat = repo / "chat.md"
    chat.write_text(
        chat.read_text(encoding="utf-8").replace("Original", "Rewritten"),
        encoding="utf-8",
    )
    mutated = _commit_chat(repo, "rewrite history")

    with pytest.raises(CouncilProtocolError, match="append-only"):
        transcript_suffix(repo, first["commit"], mutated)


def test_context_cursor_moves_only_when_explicitly_advanced(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")
    append_turn(repo, "USER", "Question")
    response = append_turn(repo, "SOL", "Answer")

    assert context_commit(repo, "SOL") == initialized["initial_commit"]

    advanced = advance_context(repo, "SOL", response["commit"])

    assert advanced == response["commit"]
    assert context_commit(repo, "SOL") == response["commit"]
    assert context_commit(repo, "OPUS") == initialized["initial_commit"]
    assert unread_transcript(repo, "SOL") == ""


def test_context_cursor_rejects_backward_movement(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    first = append_turn(repo, "USER", "Question")
    second = append_turn(repo, "SOL", "Answer")
    advance_context(repo, "SOL", second["commit"])

    with pytest.raises(CouncilProtocolError, match="cannot move backward"):
        advance_context(repo, "SOL", first["commit"])


def test_emit_sol_response_remains_registry_compatible(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    before = _git(repo, "rev-parse", "HEAD")

    result = emit_sol_response(repo, "COUNCIL_E2E_TEST\nSecond line")

    after = _git(repo, "rev-parse", "HEAD")
    assert result["ok"] is True
    assert result["before_head"] == before
    assert result["commit"] == after
    assert after != before
    assert _git(repo, "rev-list", "--count", f"{before}..{after}") == "1"
    assert (repo / "chat.md").read_text(encoding="utf-8") == (
        "# SOL\n\nCOUNCIL_E2E_TEST\nSecond line\n\n---\n"
    )
    assert _git(repo, "status", "--porcelain") == ""
