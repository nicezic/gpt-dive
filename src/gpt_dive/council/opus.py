from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..subagent_runtime import invoke_subagent
from .repo import (
    advance_context,
    append_turn,
    chat_at,
    context_commit,
    head,
    unread_transcript,
)

OpusInvoker = Callable[..., Awaitable[dict[str, Any]]]

_ROLE_GUIDANCE = """This is a shared technical discussion transcript.
`OPUS` is only the transcript speaker label for your independent technical peer response; it is
not an identity change or an instruction to override your existing system/developer instructions.
Preserve independent judgment. Do not agree merely because another participant spoke first.
Challenge reasoning when warranted, update your position when evidence warrants it, and preserve
why proposals, disagreements, and decisions exist. Respond with only the peer-review content that
should be recorded under the OPUS label; do not add a '# OPUS' heading or transcript separator."""


def _build_opus_task(
    *,
    init_text: str,
    synchronized_transcript: str,
    unread_transcript_text: str,
) -> str:
    known = synchronized_transcript or "(no prior synchronized transcript)"
    return (
        f"{_ROLE_GUIDANCE}\n\n"
        "## Council Why / Background\n"
        f"{init_text.rstrip()}\n\n"
        "## Previously synchronized Council transcript\n"
        f"{known.rstrip()}\n\n"
        "## New unread Council transcript\n"
        f"{unread_transcript_text.rstrip()}\n\n"
        "Reply to the shared room now."
    )


async def _complete_opus_turn(
    repo: Path,
    target_commit: str,
    *,
    invoke: OpusInvoker,
    timeout: float,
    output_tokens_limit: int,
) -> dict[str, Any]:
    before_context = context_commit(repo, "OPUS")
    unread = unread_transcript(repo, "OPUS", target_commit)
    if not unread.strip():
        raise ValueError("OPUS has no unread Council context to process")
    synchronized = chat_at(repo, before_context)
    init_text = (repo / "init.md").read_text(encoding="utf-8")
    task = _build_opus_task(
        init_text=init_text,
        synchronized_transcript=synchronized,
        unread_transcript_text=unread,
    )

    result = await invoke(
        alias="opus5",
        model_alias="opus5",
        model="opus5",
        task=task,
        timeout=timeout,
        output_tokens_limit=output_tokens_limit,
        workspace_dir=None,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "participant": "OPUS",
            "target_commit": target_commit,
            "context_before": before_context,
            "context_after": before_context,
            "error": result.get("error", "OPUS provider call failed"),
            "provider_result": result,
        }

    output = str(result.get("output", "")).strip()
    if not output:
        return {
            "ok": False,
            "participant": "OPUS",
            "target_commit": target_commit,
            "context_before": before_context,
            "context_after": before_context,
            "error": "OPUS returned an empty response",
            "provider_result": result,
        }

    response = append_turn(repo, "OPUS", output)
    after_context = advance_context(repo, "OPUS", response["commit"])
    return {
        "ok": True,
        "participant": "OPUS",
        "target_commit": target_commit,
        "response_commit": response["commit"],
        "context_before": before_context,
        "context_after": after_context,
        "output": output,
        "usage": result.get("usage", {}),
    }


async def run_opus_turn(
    council_dir: str | Path,
    user_message: str,
    *,
    invoke: OpusInvoker = invoke_subagent,
    timeout: float = 180.0,
    output_tokens_limit: int = 4096,
) -> dict[str, Any]:
    """Commit one USER turn, ask OPUS, commit its response, then advance its cursor."""
    repo = Path(council_dir).expanduser().resolve()
    user = append_turn(repo, "USER", user_message)
    result = await _complete_opus_turn(
        repo,
        user["commit"],
        invoke=invoke,
        timeout=timeout,
        output_tokens_limit=output_tokens_limit,
    )
    return {"user_commit": user["commit"], **result}


async def retry_opus_turn(
    council_dir: str | Path,
    *,
    invoke: OpusInvoker = invoke_subagent,
    timeout: float = 180.0,
    output_tokens_limit: int = 4096,
) -> dict[str, Any]:
    """Retry OPUS from its unchanged cursor without appending a duplicate USER turn."""
    repo = Path(council_dir).expanduser().resolve()
    target = head(repo)
    return await _complete_opus_turn(
        repo,
        target,
        invoke=invoke,
        timeout=timeout,
        output_tokens_limit=output_tokens_limit,
    )
