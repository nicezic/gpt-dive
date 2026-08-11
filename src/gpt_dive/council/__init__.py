from __future__ import annotations

from pathlib import Path
from typing import Any

from .opus import run_opus_turn
from .repo import (
    CouncilProtocolError,
    advance_context,
    append_turn,
    chat_at,
    context_commit,
    head,
    initialize_council,
    transcript_suffix,
    unread_transcript,
)


def emit_sol_response(council_dir: str | Path, message: str) -> dict[str, Any]:
    """Persist one SOL response event; transport orchestration advances its cursor later."""
    result = append_turn(council_dir, "SOL", message)
    return {"ok": True, **result}


__all__ = [
    "CouncilProtocolError",
    "advance_context",
    "append_turn",
    "chat_at",
    "context_commit",
    "emit_sol_response",
    "head",
    "initialize_council",
    "run_opus_turn",
    "transcript_suffix",
    "unread_transcript",
]
