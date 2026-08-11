from __future__ import annotations

import subprocess
from pathlib import Path

from gpt_dive.council import emit_sol_response


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Council Test")
    _git(repo, "config", "user.email", "council-test@example.invalid")
    (repo / "init.md").write_text("# Council\n", encoding="utf-8")
    (repo / "chat.md").write_text("", encoding="utf-8")
    _git(repo, "add", "init.md", "chat.md")
    _git(repo, "commit", "-q", "-m", "council: init")


def test_emit_sol_response_appends_exactly_one_block_and_commit(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    _init_repo(repo)
    before = _git(repo, "rev-parse", "HEAD")

    result = emit_sol_response(str(repo), "COUNCIL_E2E_TEST\nSecond line")

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
