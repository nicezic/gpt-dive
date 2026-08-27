from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["code_mode", "executions", "mcp"]

if TYPE_CHECKING:
    from .app import code_mode, executions, mcp


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
