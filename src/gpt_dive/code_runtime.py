from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic_monty import AsyncMonty, CollectString, MontyComplete

from .filesystem_policy import HostFileSystemOS


class CallableRegistry:
    """Small registry of host callables exposed inside Monty code."""

    def __init__(self) -> None:
        self._callables: dict[str, Callable[..., Any]] = {}
        self._async_cleanups: list[Callable[[], Awaitable[None]]] = []

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        if not name.isidentifier():
            raise ValueError(f"callable name must be a Python identifier: {name!r}")
        if name in self._callables:
            raise ValueError(f"callable already registered: {name}")
        self._callables[name] = fn

    def add_async_cleanup(self, cleanup: Callable[[], Awaitable[None]]) -> None:
        self._async_cleanups.append(cleanup)

    async def aclose(self) -> None:
        for cleanup in reversed(self._async_cleanups):
            await cleanup()
        self._async_cleanups.clear()

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

    def type_check_stubs(self, *, include_input: bool = False) -> str:
        """Render runtime globals and live callables as Monty type-check stubs."""
        parts = [
            "from typing import Any",
            "CWD: str",
            "CAPABILITIES: dict[str, dict[str, str]]",
        ]
        if include_input:
            parts.append("INPUT: str")
        for name, fn in self._callables.items():
            prefix = "async def" if inspect.iscoroutinefunction(fn) else "def"
            parts.append(
                f"{prefix} {name}{inspect.signature(fn)}:\n    raise NotImplementedError()"
            )
        return "\n\n".join(parts)


class MontyCodeRuntime:
    """Execute one stateless Monty program against a registry of host callables."""

    async def run(
        self,
        code: str,
        registry: CallableRegistry,
        cwd: str | None = None,
        input: str | None = None,
    ) -> dict[str, Any]:
        if not code.strip():
            raise ValueError("code must not be empty")

        runtime_code = f"import asyncio\n{code}"
        run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else str(Path.home())
        capture = CollectString()
        host_os = HostFileSystemOS(cwd=run_cwd, home=Path.home())
        inputs: dict[str, Any] = {
            "CWD": run_cwd,
            "CAPABILITIES": registry.describe(),
        }
        if input is not None:
            inputs["INPUT"] = input

        try:
            async with (
                AsyncMonty() as monty,
                monty.checkout(
                    type_check=True,
                    type_check_stubs=registry.type_check_stubs(
                        include_input=input is not None
                    ),
                ) as session,
            ):
                state = await session.feed_start(
                    runtime_code,
                    inputs=inputs,
                    external_lookup=registry.as_external_lookup(),
                    print_callback=capture,
                    os=host_os,
                    skip_type_check=False,
                )
                while not isinstance(state, MontyComplete):
                    state = await state.resume_auto()

            result: dict[str, Any] = {"result": state.output}
            if capture.output:
                result["stdout"] = capture.output
            return result
        finally:
            await registry.aclose()
