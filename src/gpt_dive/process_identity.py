"""Small Linux ``/proc`` identity primitives shared by execution owners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """The stable observations needed to avoid signaling a reused PID."""

    state: str
    parent_pid: int
    start_ticks: int


def read_process_identity(pid: int) -> ProcessIdentity | None:
    """Return current Linux process identity, or ``None`` when it is unavailable."""
    try:
        text = (Path("/proc") / str(pid) / "stat").read_text()
    except FileNotFoundError, ProcessLookupError, PermissionError:
        return None
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 2 :].split()
    if len(fields) <= 19:
        return None
    try:
        return ProcessIdentity(
            state=fields[0], parent_pid=int(fields[1]), start_ticks=int(fields[19])
        )
    except ValueError:
        return None


def process_start_ticks(pid: int) -> int | None:
    """Return a PID's birth marker, when the process can be observed."""
    identity = read_process_identity(pid)
    return identity.start_ticks if identity is not None else None


def process_matches(pid: int, expected_start_ticks: int | None) -> bool:
    """Whether ``pid`` is live and still denotes the expected process instance."""
    identity = read_process_identity(pid)
    return (
        identity is not None
        and identity.state != "Z"
        and (
            expected_start_ticks is None or identity.start_ticks == expected_start_ticks
        )
    )
