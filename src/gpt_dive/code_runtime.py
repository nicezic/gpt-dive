from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import TypeAdapter
from pydantic.json_schema import GenerateJsonSchema
from pydantic_ai._function_schema import FunctionSchema, function_schema
from pydantic_ai.function_signature import FunctionSignature
from pydantic_monty import AsyncMonty, MontyComplete

from .filesystem_policy import HostFileSystemOS


@dataclass(frozen=True)
class CapabilityDefinition:
    """One authority for a callable's runtime and model-facing contract."""

    name: str
    fn: Callable[..., Any]
    description: str
    python_signature: inspect.Signature
    function_schema: FunctionSchema
    model_signature: FunctionSignature
    return_adapter: TypeAdapter[Any]
    is_async: bool

    @classmethod
    def from_callable(cls, name: str, fn: Callable[..., Any]) -> CapabilityDefinition:
        schema = function_schema(
            fn,
            GenerateJsonSchema,
            tool_name=name,
            takes_ctx=False,
        )
        return_annotation = get_type_hints(fn, include_extras=True).get("return", Any)
        return cls(
            name=name,
            fn=fn,
            description=inspect.getdoc(fn) or "",
            python_signature=inspect.signature(fn),
            function_schema=schema,
            model_signature=FunctionSignature.from_schema(
                name=name,
                parameters_schema=schema.json_schema,
                return_schema=schema.return_schema,
            ),
            return_adapter=TypeAdapter(return_annotation),
            is_async=inspect.iscoroutinefunction(fn),
        )

    def validate_arguments(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        bound = self.python_signature.bind(*args, **kwargs)
        validated = self.function_schema.validator.validate_python(
            dict(bound.arguments)
        )
        bound.arguments.clear()
        bound.arguments.update(validated)
        return tuple(bound.args), dict(bound.kwargs)

    def validate_return(self, value: Any) -> Any:
        return self.return_adapter.validate_python(value)

    def runtime_stub(self) -> str:
        prefix = "async def" if self.is_async else "def"
        params = self.python_signature.replace(
            return_annotation=inspect.Signature.empty
        )
        return (
            f"{prefix} {self.name}{params} -> {self.model_signature.return_type}:\n"
            "    raise NotImplementedError()"
        )

    def declaration(self, *, conflicting_type_names: frozenset[str]) -> str:
        parts = FunctionSignature.render_type_definitions(
            [self.model_signature], conflicting_type_names
        )
        parts.append(
            self.model_signature.render(
                "...",
                description=self.description,
                is_async=self.is_async,
                conflicting_type_names=conflicting_type_names,
            )
        )
        return "\n\n".join(parts)


class CallableRegistry:
    """Small registry of host callables exposed inside Monty code."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._async_cleanups: list[Callable[[], Awaitable[None]]] = []
        self._active_async_tasks: set[asyncio.Task[Any]] = set()

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        if not name.isidentifier():
            raise ValueError(f"callable name must be a Python identifier: {name!r}")
        if name in self._definitions:
            raise ValueError(f"callable already registered: {name}")
        self._definitions[name] = CapabilityDefinition.from_callable(name, fn)

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

    def _track_async_callable(
        self, definition: CapabilityDefinition
    ) -> Callable[..., Any]:
        @functools.wraps(definition.fn)
        async def tracked(*args: Any, **kwargs: Any) -> Any:
            call_args, call_kwargs = definition.validate_arguments(args, kwargs)
            task = asyncio.current_task()
            if task is not None:
                self._active_async_tasks.add(task)
            try:
                result = await definition.fn(*call_args, **call_kwargs)
                return definition.validate_return(result)
            finally:
                if task is not None:
                    self._active_async_tasks.discard(task)

        return tracked

    @staticmethod
    def _validated_sync_callable(
        definition: CapabilityDefinition,
    ) -> Callable[..., Any]:
        @functools.wraps(definition.fn)
        def validated(*args: Any, **kwargs: Any) -> Any:
            call_args, call_kwargs = definition.validate_arguments(args, kwargs)
            return definition.validate_return(definition.fn(*call_args, **call_kwargs))

        return validated

    def as_external_lookup(self) -> dict[str, Callable[..., Any]]:
        return {
            name: self._track_async_callable(definition)
            if definition.is_async
            else self._validated_sync_callable(definition)
            for name, definition in self._definitions.items()
        }

    def describe(self) -> dict[str, dict[str, str]]:
        """Return compact runtime metadata for capabilities available to Monty code."""
        conflicting = FunctionSignature.get_conflicting_type_names(
            self._model_signatures()
        )
        return {
            name: {
                "signature": str(definition.python_signature),
                "description": definition.description,
                "declaration": definition.declaration(
                    conflicting_type_names=conflicting
                ),
            }
            for name, definition in self._definitions.items()
        }

    def _model_signatures(self) -> list[FunctionSignature]:
        return [definition.model_signature for definition in self._definitions.values()]

    def model_catalog(self) -> str:
        """Render enabled capabilities for the model before it writes Monty code."""
        signatures = self._model_signatures()
        conflicting = FunctionSignature.get_conflicting_type_names(signatures)
        parts = ["from typing import Any, TypedDict, NotRequired, Literal"]
        parts.extend(FunctionSignature.render_type_definitions(signatures, conflicting))
        parts.extend(
            definition.model_signature.render(
                "...",
                description=definition.description,
                is_async=definition.is_async,
                conflicting_type_names=conflicting,
            )
            for definition in self._definitions.values()
        )
        return "\n\n".join(parts)

    def type_check_stubs(self, *, include_payload: bool = False) -> str:
        """Render runtime globals and live callables as Monty type-check stubs."""
        signatures = self._model_signatures()
        conflicting = FunctionSignature.get_conflicting_type_names(signatures)
        parts = [
            "from typing import Any, TypedDict, NotRequired, Literal",
            "CWD: str",
            "CAPABILITIES: dict[str, dict[str, str]]",
        ]
        if include_payload:
            parts.append("PAYLOAD: str")
        parts.extend(FunctionSignature.render_type_definitions(signatures, conflicting))
        parts.extend(
            definition.runtime_stub() for definition in self._definitions.values()
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
