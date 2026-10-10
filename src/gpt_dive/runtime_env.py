from __future__ import annotations

import os
from pathlib import Path

from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS

DENIED_MODEL_ENV_PATTERNS = (
    *LLM_API_KEY_ENV_PATTERNS,
    "MINIMAX_*",
    "MICU_*",
    "OPENCODE_*",
)


def build_runtime_path(*prefixes: str | Path, inherited: str | None = None) -> str:
    """Build the stable PATH used by Dive execution surfaces."""
    home = Path.home()
    ordered = [
        *[str(Path(prefix).expanduser()) for prefix in prefixes],
        str(home / ".local" / "share" / "mise" / "shims"),
        str(home / ".local" / "bin"),
        str(home / ".cargo" / "bin"),
    ]
    tail = inherited if inherited is not None else os.environ.get("PATH", "")
    if tail:
        ordered.extend(tail.split(":"))

    return ":".join(dict.fromkeys(path for path in ordered if path))
