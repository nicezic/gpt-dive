from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic_monty import AsyncMonty, MontyComplete

from .filesystem_policy import HostFileSystemOS


class CallableRegistry:
    """Small registry of host callables exposed inside Monty code."""

    def __init__(self) -> None:
        self._callables: dict[str, Callable[..., Any]] = {}
        self._async_cleanups: list[Callable[[], Awaitable[None]]] = []
        self._active_async_tasks: set[asyncio.Task[Any]] = set()

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        if not name.isidentifier():
            raise ValueError(f"callable name must be a Python identifier: {name!r}")
        if name in self._callables:
            raise ValueError(f"callable already registered: {name}")
        self._callables[name] = fn

    def add_async_cleanup(self, cleanup: Callable[[], Awaitable[None]]) -> None:
        self._async_cleanups.append(cleanup)

    async def aclose(self) -> None:
        current = asyncio.current_task()
        active = [
            task
            for task in self._active_async_tasks
            if task is not current and not task.done()
        ]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self._active_async_tasks.clear()

        for cleanup in reversed(self._async_cleanups):
            await cleanup()
        self._async_cleanups.clear()

    def _track_async_callable(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def tracked(*args: Any, **kwargs: Any) -> Any:
            task = asyncio.current_task()
            if task is not None:
                self._active_async_tasks.add(task)
            try:
                return await fn(*args, **kwargs)
            finally:
                if task is not None:
                    self._active_async_tasks.discard(task)

        return tracked

    def as_external_lookup(self) -> dict[str, Callable[..., Any]]:
        return {
            name: self._track_async_callable(fn)
            if inspect.iscoroutinefunction(fn)
            else fn
            for name, fn in self._callables.items()
        }

    def describe(self) -> dict[str, dict[str, str]]:
        """Return compact runtime metadata for capabilities available to Monty code."""
        return {
            name: {
                "signature": str(inspect.signature(fn)),
                "description": inspect.getdoc(fn) or "",
            }
            for name, fn in self._callables.items()
        }

    def type_check_stubs(self, *, include_payload: bool = False) -> str:
        """Render runtime globals and live callables as Monty type-check stubs."""
        parts = [
            "from typing import Any",
            "CWD: str",
            "CAPABILITIES: dict[str, dict[str, str]]",
        ]
        if include_payload:
            parts.append("PAYLOAD: str")
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
        payload: str | None = None,
    ) -> Any:
        if not code.strip():
            raise ValueError("code must not be empty")

        runtime_code = f"import asyncio\n{code}"
        run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else str(Path.home())
        host_os = HostFileSystemOS(cwd=run_cwd, home=Path.home())
        inputs: dict[str, Any] = {
            "CWD": run_cwd,
            "CAPABILITIES": registry.describe(),
        }
        if payload is not None:
            inputs["PAYLOAD"] = payload

        try:
            async with (
                AsyncMonty() as monty,
                monty.checkout(
                    type_check=True,
                    type_check_stubs=registry.type_check_stubs(
                        include_payload=payload is not None
                    ),
                ) as session,
            ):
                state = await session.feed_start(
                    runtime_code,
                    inputs=inputs,
                    external_lookup=registry.as_external_lookup(),
                    print_callback=lambda _stream, _text: None,
                    os=host_os,
                    skip_type_check=False,
                )
                while not isinstance(state, MontyComplete):
                    state = await state.resume_auto()

            return state.output
        finally:
            await registry.aclose()
