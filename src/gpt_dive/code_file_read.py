"""Raw reads for Monty Code Mode, separate from Harness's numbered file viewer.

Harness owns the edit/write operations and their hash checks. Its read_file
returns an annotated view intended for an LLM, not a string suitable for
edit_file(old_text=...). Keep this raw view unannotated for exact replacement.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.workspaces import LocalWorkspaceBackend

from .filesystem_policy import is_secret_path

_READ_OUTPUT_BYTES = 256 * 1024
_READ_OUTPUT_RESERVE = 128


def _raw_lines(lines: list[str], offset: int, limit: int | None) -> str:
    if offset < 0:
        raise ValueError(f"Offset {offset} must be non-negative.")
    if offset > len(lines):
        raise ValueError(f"Offset {offset} exceeds file length ({len(lines)} lines).")

    selected = (
        lines[offset:] if limit is None else lines[offset : offset + max(limit, 0)]
    )
    result = "".join(selected)
    result_bytes = result.encode("utf-8")
    if len(result_bytes) <= _READ_OUTPUT_BYTES:
        return result

    # Return complete lines and a paging hint; the notice is not editable file content.
    cut = result_bytes[: _READ_OUTPUT_BYTES - _READ_OUTPUT_RESERVE]
    cut = cut.decode("utf-8", errors="ignore")
    cut = cut[: cut.rfind("\n") + 1]
    if not cut:
        return (
            f"... (line {offset + 1} exceeds the 256 KiB read window; "
            f"use a shell byte range to inspect it.)\n"
        )
    next_line = offset + cut.count("\n")
    return (
        cut + "... (read_file output capped at 256 KiB. "
        f"Use offset={next_line} to continue reading.)\n"
    )


async def read_raw_file(
    *,
    resolved_path: Path,
    requested_path: str,
    home: Path,
    workspace: LocalWorkspaceBackend,
    offset: int = 0,
    limit: int | None = None,
) -> str:
    """Read unannotated text, subject to secret-path policy and output paging.

    The upstream WorkspaceBackend also powers Harness edits. Valid UTF-8
    round-trips exactly; undecodable bytes are replaced for viewing, but cannot
    be used as exact edit_file anchors.
    """
    try:
        if is_secret_path(resolved_path, home=home):
            raise PermissionError(f"Access denied by pattern: {requested_path}")
        if not resolved_path.is_file():
            if resolved_path.is_dir():
                raise FileNotFoundError(
                    f"'{requested_path}' is a directory, not a file."
                )
            raise FileNotFoundError(f"File not found: {requested_path}")

        raw_bytes = await workspace.read_bytes(str(resolved_path))
        if b"\x00" in raw_bytes[:8192]:
            return (
                f"[Binary file: {len(raw_bytes)} bytes. "
                "Use a binary-aware tool to inspect.]"
            )
        lines = raw_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        return _raw_lines(lines, offset, limit)
    except (
        PermissionError,
        FileNotFoundError,
        NotADirectoryError,
        IsADirectoryError,
        ValueError,
    ) as exc:
        raise ModelRetry(str(exc)) from exc
