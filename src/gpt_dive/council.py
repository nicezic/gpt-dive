from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def emit_sol_response(council_dir: str, message: str) -> dict[str, Any]:
    """Append one SOL response to a Council transcript and commit that event."""
    repo = Path(council_dir).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError(f"council_dir is not a directory: {repo}")
    if not (repo / ".git").exists():
        raise ValueError(f"council_dir is not a Git repository: {repo}")

    text = message.strip()
    if not text:
        raise ValueError("message must not be empty")

    chat = repo / "chat.md"
    if not chat.is_file():
        raise ValueError(f"chat.md does not exist: {chat}")

    before_head = _git(repo, "rev-parse", "HEAD")
    existing = chat.read_text(encoding="utf-8")
    separator = "" if not existing or existing.endswith("\n") else "\n"
    block = f"{separator}# SOL\n\n{text}\n\n---\n"
    with chat.open("a", encoding="utf-8") as handle:
        handle.write(block)

    _git(repo, "add", "--", "chat.md")
    _git(repo, "commit", "-m", "council: SOL response", "--", "chat.md")
    after_head = _git(repo, "rev-parse", "HEAD")

    return {
        "ok": True,
        "council_dir": str(repo),
        "chat_path": str(chat),
        "before_head": before_head,
        "commit": after_head,
    }
