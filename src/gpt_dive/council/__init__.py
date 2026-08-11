from __future__ import annotations

from pathlib import Path
from typing import Any

from .bridge import SolBridge
from .opus import retry_opus_turn, run_opus_turn
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
from .sol import build_sol_transport_message, retry_sol_turn, run_sol_turn


def emit_sol_response(
    council_dir: str | Path,
    message: str,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """Persist one SOL response event, optionally guarding its expected parent commit."""
    if expected_head is not None:
        expected = expected_head.strip()
        if not expected:
            raise ValueError("expected_head must not be empty")
        current = head(council_dir)
        if current != expected:
            raise CouncilProtocolError(
                f"Council HEAD changed before SOL response: expected {expected}, found {current}"
            )
    result = append_turn(council_dir, "SOL", message)
    return {"ok": True, **result}


__all__ = [
    "CouncilProtocolError",
    "SolBridge",
    "advance_context",
    "append_turn",
    "build_sol_transport_message",
    "chat_at",
    "context_commit",
    "emit_sol_response",
    "head",
    "initialize_council",
    "retry_opus_turn",
    "retry_sol_turn",
    "run_opus_turn",
    "run_sol_turn",
    "transcript_suffix",
    "unread_transcript",
]
