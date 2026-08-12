from __future__ import annotations

import os
from pathlib import Path


def build_runtime_path(*prefixes: str | Path, inherited: str | None = None) -> str:
    """Build the stable PATH used by Dive execution surfaces."""
    home = Path.home()
    ordered = [
        *[str(Path(prefix).expanduser()) for prefix in prefixes],
        str(home / ".local" / "share" / "pnpm" / "bin"),
        str(home / ".local" / "share" / "pnpm"),
        str(home / ".bun" / "bin"),
        str(home / ".local" / "bin"),
    ]
    tail = inherited if inherited is not None else os.environ.get("PATH", "")
    if tail:
        ordered.extend(tail.split(":"))

    seen: set[str] = set()
    return ":".join(
        path for path in ordered if path and not (path in seen or seen.add(path))
    )
