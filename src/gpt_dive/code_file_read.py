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


def _raw_lines(lines: list[str], offset: int, limit: int | None) -> str:
    if offset < 0:
        raise ValueError(f"Offset {offset} must be non-negative.")
    if offset > len(lines):
        raise ValueError(f"Offset {offset} exceeds file length ({len(lines)} lines).")

    selected = (
        lines[offset:] if limit is None else lines[offset : offset + max(limit, 0)]
    )
    return "".join(selected)


async def read_raw_file(
    *,
    resolved_path: Path,
    requested_path: str,
    home: Path,
    workspace: LocalWorkspaceBackend,
    offset: int = 0,
    limit: int | None = None,
) -> str:
    """Read unannotated text, subject to secret-path policy.

    The upstream WorkspaceBackend also powers Harness edits. Valid UTF-8
    round-trips exactly; binary and invalid UTF-8 files are rejected.
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
        if b"\x00" in raw_bytes:
            raise ValueError(
                f"Binary file cannot be read as text: {requested_path}. "
                "Use a binary-aware tool to inspect it."
            )
        try:
            lines = raw_bytes.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"File is not valid UTF-8: {requested_path}. "
                "Use a binary-aware tool to inspect it."
            ) from exc
        return _raw_lines(lines, offset, limit)
    except (
        PermissionError,
        FileNotFoundError,
        NotADirectoryError,
        IsADirectoryError,
        ValueError,
    ) as exc:
        raise ModelRetry(str(exc)) from exc
