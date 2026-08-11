from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

Participant = Literal["SOL", "OPUS"]
Role = Literal["USER", "SOL", "OPUS"]

_CONTEXT_REFS: dict[Participant, str] = {
    "SOL": "refs/council/context/sol",
    "OPUS": "refs/council/context/opus",
}
_VALID_ROLES = frozenset({"USER", "SOL", "OPUS"})


class CouncilProtocolError(RuntimeError):
    """Raised when the Git-backed Council protocol invariant is violated."""


def _git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CouncilProtocolError(f"git {' '.join(args)} failed: {detail}")
    return completed


def _commit(repo: Path, message: str) -> str:
    completed = _git(
        repo,
        "-c",
        "user.name=GPT Dive Council",
        "-c",
        "user.email=council@gpt-dive.local",
        "commit",
        "-q",
        "-m",
        message,
        "--",
        "chat.md",
    )
    if completed.returncode != 0:  # pragma: no cover - _git raises first
        raise CouncilProtocolError(completed.stderr.strip())
    return head(repo)


def _validate_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise ValueError(f"council_dir is not a directory: {repo}")
    if not (repo / ".git").exists():
        raise ValueError(f"council_dir is not a Git repository: {repo}")
    for name in ("init.md", "chat.md"):
        if not (repo / name).is_file():
            raise ValueError(f"{name} does not exist: {repo / name}")


def _repo_path(council_dir: str | Path) -> Path:
    repo = Path(council_dir).expanduser().resolve()
    _validate_repo(repo)
    return repo


def head(council_dir: str | Path) -> str:
    repo = Path(council_dir).expanduser().resolve()
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def initialize_council(council_dir: str | Path, init_text: str) -> dict[str, str]:
    """Create a new Council Git repository and initialize both participant cursors."""
    repo = Path(council_dir).expanduser().resolve()
    if repo.exists() and any(repo.iterdir()):
        raise ValueError(f"council_dir must be absent or empty: {repo}")
    repo.mkdir(parents=True, exist_ok=True)

    _git(repo, "init", "-q")
    (repo / "init.md").write_text(init_text.rstrip() + "\n", encoding="utf-8")
    (repo / "chat.md").write_text("", encoding="utf-8")
    _git(repo, "add", "--", "init.md", "chat.md")
    _git(
        repo,
        "-c",
        "user.name=GPT Dive Council",
        "-c",
        "user.email=council@gpt-dive.local",
        "commit",
        "-q",
        "-m",
        "council: init",
    )
    initial = head(repo)
    for ref in _CONTEXT_REFS.values():
        _git(repo, "update-ref", ref, initial)

    return {
        "council_dir": str(repo),
        "initial_commit": initial,
        "sol_context": initial,
        "opus_context": initial,
    }


def append_turn(
    council_dir: str | Path, role: Role | str, message: str
) -> dict[str, str]:
    """Append exactly one human-readable speaking block and commit exactly one event."""
    repo = _repo_path(council_dir)
    normalized_role = role.upper()
    if normalized_role not in _VALID_ROLES:
        raise ValueError(f"invalid Council role: {role}")

    text = message.strip()
    if not text:
        raise ValueError("message must not be empty")

    chat = repo / "chat.md"
    before_head = head(repo)
    before_text = chat.read_text(encoding="utf-8")
    committed_text = chat_at(repo, before_head)
    if before_text != committed_text:
        raise CouncilProtocolError(
            "chat.md has uncommitted changes; refusing to mix them into a Council event"
        )
    separator = "" if not before_text or before_text.endswith("\n") else "\n"
    block = f"{separator}# {normalized_role}\n\n{text}\n\n---\n"

    chat.write_text(before_text + block, encoding="utf-8")
    try:
        _git(repo, "add", "--", "chat.md")
        commit = _commit(repo, f"council: {normalized_role} turn")
    except Exception:
        # A speaking event is atomic from the protocol's point of view. Restore the
        # pre-event worktree/index if Git cannot create the event commit.
        chat.write_text(before_text, encoding="utf-8")
        _git(repo, "reset", "-q", "HEAD", "--", "chat.md", check=False)
        raise

    return {
        "council_dir": str(repo),
        "chat_path": str(chat),
        "before_head": before_head,
        "commit": commit,
        "role": normalized_role,
        "block": block,
    }


def context_commit(council_dir: str | Path, participant: Participant | str) -> str:
    repo = _repo_path(council_dir)
    normalized = participant.upper()
    if normalized not in _CONTEXT_REFS:
        raise ValueError(f"invalid Council participant: {participant}")
    return _git(repo, "rev-parse", _CONTEXT_REFS[normalized]).stdout.strip()  # type: ignore[index]


def advance_context(
    council_dir: str | Path,
    participant: Participant | str,
    target_commit: str,
) -> str:
    """Advance one participant cursor forward to an existing descendant commit."""
    repo = _repo_path(council_dir)
    normalized = participant.upper()
    if normalized not in _CONTEXT_REFS:
        raise ValueError(f"invalid Council participant: {participant}")
    ref = _CONTEXT_REFS[normalized]  # type: ignore[index]

    target = _git(
        repo, "rev-parse", "--verify", f"{target_commit}^{{commit}}"
    ).stdout.strip()
    current = _git(repo, "rev-parse", ref).stdout.strip()
    ancestry = _git(repo, "merge-base", "--is-ancestor", current, target, check=False)
    target_on_head = _git(
        repo, "merge-base", "--is-ancestor", target, head(repo), check=False
    )
    if ancestry.returncode != 0 or target_on_head.returncode != 0:
        raise CouncilProtocolError(
            f"ref {ref} cannot move backward or outside current Council history: {current} -> {target}"
        )

    _git(repo, "update-ref", ref, target, current)
    return target


def chat_at(council_dir: str | Path, commit: str) -> str:
    repo = _repo_path(council_dir)
    completed = _git(repo, "show", f"{commit}:chat.md")
    return completed.stdout


def transcript_suffix(
    council_dir: str | Path,
    base_commit: str,
    target_commit: str = "HEAD",
) -> str:
    """Return the pure append-only chat suffix between two Git snapshots."""
    repo = _repo_path(council_dir)
    base_sha = _git(
        repo, "rev-parse", "--verify", f"{base_commit}^{{commit}}"
    ).stdout.strip()
    target_sha = _git(
        repo, "rev-parse", "--verify", f"{target_commit}^{{commit}}"
    ).stdout.strip()
    ancestry = _git(
        repo, "merge-base", "--is-ancestor", base_sha, target_sha, check=False
    )
    if ancestry.returncode != 0:
        raise CouncilProtocolError(
            "base context commit is not an ancestor of target commit"
        )
    base = chat_at(repo, base_sha)
    current = chat_at(repo, target_sha)
    if not current.startswith(base):
        raise CouncilProtocolError(
            "chat.md is not an append-only extension of the participant context snapshot"
        )
    return current[len(base) :]


def unread_transcript(
    council_dir: str | Path,
    participant: Participant | str,
    target_commit: str = "HEAD",
) -> str:
    base = context_commit(council_dir, participant)
    return transcript_suffix(council_dir, base, target_commit)
