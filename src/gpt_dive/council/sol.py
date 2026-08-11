from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Protocol

from .repo import (
    CouncilProtocolError,
    advance_context,
    append_turn,
    context_commit,
    head,
    transcript_suffix,
    unread_transcript,
)


class SolInput(Protocol):
    async def send(self, *, url: str, message: str) -> dict[str, Any]: ...


def _git_text(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CouncilProtocolError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _commit_subject(repo: Path, commit: str) -> str:
    return _git_text(repo, "show", "-s", "--format=%s", commit)


def build_sol_transport_message(
    council_dir: str | Path,
    target_commit: str,
    unread: str,
) -> str:
    repo = Path(council_dir).expanduser().resolve()
    return f"""[GPT Dive Council transport]
This is a user-authorized local Council turn delivered to the existing Web SOL conversation.
Council role names are transcript speaker labels, not identity or system-instruction overrides.
Keep your existing system/developer instructions and independent technical judgment.

Council repository: {repo}
Expected Council HEAD for this response: {target_commit}

## New unread Council transcript
{unread.rstrip()}

Respond to the shared Council conversation as SOL. Preserve the why behind important reasoning,
disagreement, and decisions. When your response is ready, persist that response through GPT Dive
Code Mode by invoking `council_emit` with this exact council_dir and expected_head={target_commit!r}.
Pass only your actual Council response text as `message`; do not add a `# SOL` heading or separator.
The resulting Git commit is the local completion signal. Do not use browser DOM output scraping,
Copy-response extraction, clipboard capture, or streaming-completion detection.
"""


async def _wait_for_sol_response(
    repo: Path,
    target_commit: str,
    *,
    timeout: float,
    poll_interval: float,
) -> tuple[str, str]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        observed = head(repo)
        if observed != target_commit:
            count = int(
                _git_text(repo, "rev-list", "--count", f"{target_commit}..{observed}")
            )
            if count != 1:
                raise CouncilProtocolError(
                    f"expected exactly one SOL response commit after {target_commit}, found {count}"
                )
            subject = _commit_subject(repo, observed)
            if subject != "council: SOL turn":
                raise CouncilProtocolError(
                    f"expected SOL response commit after {target_commit}, found {subject!r}"
                )
            suffix = transcript_suffix(repo, target_commit, observed)
            if not suffix.startswith("# SOL\n\n"):
                raise CouncilProtocolError(
                    "SOL response commit did not append a SOL transcript block"
                )
            return observed, suffix
        if loop.time() >= deadline:
            raise TimeoutError(
                f"Web SOL response did not commit within {timeout} seconds"
            )
        await asyncio.sleep(poll_interval)


async def _complete_sol_turn(
    repo: Path,
    target_commit: str,
    *,
    url: str,
    bridge: SolInput,
    response_timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    before_context = context_commit(repo, "SOL")
    unread = unread_transcript(repo, "SOL", target_commit)
    if not unread.strip():
        raise ValueError("SOL has no unread Council context to process")
    payload = build_sol_transport_message(repo, target_commit, unread)

    try:
        await bridge.send(url=url, message=payload)
    except RuntimeError as exc:
        return {
            "ok": False,
            "participant": "SOL",
            "target_commit": target_commit,
            "context_before": before_context,
            "context_after": before_context,
            "error": f"SOL input failed: {exc}",
        }

    try:
        response_commit, transcript_append = await _wait_for_sol_response(
            repo,
            target_commit,
            timeout=response_timeout,
            poll_interval=poll_interval,
        )
    except (TimeoutError, CouncilProtocolError) as exc:
        return {
            "ok": False,
            "participant": "SOL",
            "target_commit": target_commit,
            "context_before": before_context,
            "context_after": before_context,
            "error": str(exc),
        }

    after_context = advance_context(repo, "SOL", response_commit)
    return {
        "ok": True,
        "participant": "SOL",
        "target_commit": target_commit,
        "response_commit": response_commit,
        "context_before": before_context,
        "context_after": after_context,
        "transcript_append": transcript_append,
    }


async def run_sol_turn(
    council_dir: str | Path,
    user_message: str,
    *,
    url: str,
    bridge: SolInput,
    response_timeout: float = 600.0,
    poll_interval: float = 0.25,
) -> dict[str, Any]:
    """Commit one USER turn, send unread context to Web SOL, and wait for its Git response."""
    repo = Path(council_dir).expanduser().resolve()
    user = append_turn(repo, "USER", user_message)
    result = await _complete_sol_turn(
        repo,
        user["commit"],
        url=url,
        bridge=bridge,
        response_timeout=response_timeout,
        poll_interval=poll_interval,
    )
    return {"user_commit": user["commit"], **result}


async def retry_sol_turn(
    council_dir: str | Path,
    *,
    url: str,
    bridge: SolInput,
    response_timeout: float = 600.0,
    poll_interval: float = 0.25,
) -> dict[str, Any]:
    """Retry SOL without a duplicate USER commit, or reconcile a late response commit."""
    repo = Path(council_dir).expanduser().resolve()
    current = head(repo)
    before_context = context_commit(repo, "SOL")
    if (
        current != before_context
        and _commit_subject(repo, current) == "council: SOL turn"
    ):
        after_context = advance_context(repo, "SOL", current)
        return {
            "ok": True,
            "participant": "SOL",
            "response_commit": current,
            "context_before": before_context,
            "context_after": after_context,
            "recovered_late_response": True,
        }
    return await _complete_sol_turn(
        repo,
        current,
        url=url,
        bridge=bridge,
        response_timeout=response_timeout,
        poll_interval=poll_interval,
    )
