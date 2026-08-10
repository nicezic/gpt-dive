from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_monty import AsyncMonty, CollectString, MontyComplete, MountDir


class CallableRegistry:
    """Small registry of host callables exposed inside Monty code."""

    def __init__(self) -> None:
        self._callables: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        if not name.isidentifier():
            raise ValueError(f"callable name must be a Python identifier: {name!r}")
        if name in self._callables:
            raise ValueError(f"callable already registered: {name}")
        self._callables[name] = fn

    def as_external_lookup(self) -> dict[str, Callable[..., Any]]:
        return dict(self._callables)

    def describe(self) -> dict[str, dict[str, str]]:
        """Return compact runtime metadata for capabilities available to Monty code."""
        return {
            name: {
                "signature": str(inspect.signature(fn)),
                "description": inspect.getdoc(fn) or "",
            }
            for name, fn in self._callables.items()
        }


class MontyCodeRuntime:
    """Execute one stateless Monty program against a registry of host callables."""

    async def run(
        self,
        code: str,
        registry: CallableRegistry,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        if not code.strip():
            raise ValueError("code must not be empty")

        run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else str(Path.home())
        capture = CollectString()
        mount = MountDir(host_path="/", virtual_path="/", mode="read-write")

        async with AsyncMonty() as monty, monty.checkout(type_check=False) as session:
            state = await session.feed_start(
                code,
                inputs={"CWD": run_cwd, "CAPABILITIES": registry.describe()},
                external_lookup=registry.as_external_lookup(),
                print_callback=capture,
                mount=mount,
                skip_type_check=True,
            )
            while not isinstance(state, MontyComplete):
                state = await state.resume_auto()

        result: dict[str, Any] = {"result": state.output}
        if capture.output:
            result["stdout"] = capture.output
        return result
