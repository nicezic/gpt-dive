from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .execution_manager import ExecutionManager
from .execution_store import EXECUTION_ID_PATTERN, generate_execution_id
from .runtime_diagnostics import request_lifecycle_middleware
from .task_runtime import (
    CODE_MODE_WORKER_PROTOCOL,
    TRACKED_TASKS_LIMIT,
)
from .task_runtime import (
    cancel_task as runtime_cancel_task,
)
from .task_runtime import (
    dismiss_task as runtime_dismiss_task,
)
from .task_runtime import (
    get_task as runtime_get_task,
)
from .task_runtime import (
    list_projected_tasks as runtime_list_projected_tasks,
)
from .task_runtime import (
    projection_revision as runtime_projection_revision,
)
from .task_runtime import (
    read_execution_result as runtime_read_execution_result,
)
from .task_runtime import (
    render_tracked_tasks as runtime_render_tracked_tasks,
)

_INLINE_WAIT_SECONDS = 100.0
_INLINE_RESPONSE_DEADLINE_SECONDS = 110.0
_TASK_LIST_LIMIT = 50
_TRACKED_TASKS_REVISION_STATE_KEY = "gpt_dive_tracked_tasks_revision"
_PENDING_RUNTIME_FOLLOWUPS: set[asyncio.Task[None]] = set()

# MCP 2.0.0's generated ArgModelBase otherwise ignores unknown arguments. Closing
# the base before tool registration makes both validation and advertised schemas strict.
ArgModelBase.model_config["extra"] = "forbid"

logger = logging.getLogger("gpt_dive.runtime")

executions = ExecutionManager()

mcp = MCPServer(
    name="gpt-dive",
    title="GPT Dive",
    description=(
        "Direct ChatGPT Web -> WSL2 runtime. Call bootstrap first. Use code_mode as the "
        "default programmable root for normal local work: compose registered capabilities in "
        "Monty/Python, and prefer direct capabilities over shell reimplementation. Every run "
        "requires a short label and starts as one durable Execution; payload is optional. "
        "Never guess capability names, arguments, or return shapes: inspect the live contract first. "
        "On tool errors, inspect the live contract and local evidence before retrying; use Web Search "
        "when the missing fact is external and current."
    ),
    instructions=(
        "GPT Dive operates the user's local WSL2 environment. Treat its filesystem, "
        "processes, network state, and command results as belonging to the user's local "
        "machine, not as a separate hosted or ChatGPT sandbox. In a fresh ChatGPT Web "
        "session, call bootstrap first. After bootstrap, use code_mode as the default programmable "
        "root for normal local work. Write Monty/Python orchestration, prefer registered capabilities "
        "that directly match the operation, await dependencies sequentially, and use asyncio.gather "
        "for independent work. Do not rebuild file/search/edit operations in shell. "
        "Every Web MCP code_mode call must provide a short label. When opaque input is needed, "
        "pass payload as a string; serialize objects/lists to text and parse PAYLOAD inside Code Mode. "
        "Never invent capability names, parameter names, optional arguments, or return shapes from "
        "memory. Inspect the live MCP schema/CAPABILITIES contract first whenever uncertain. "
        "On tool errors or assistant mistakes, report them immediately and inspect the live contract "
        "plus local state before retrying. Use Web Search only when the missing evidence is external "
        "and current. Use /grill-me only when deeper diagnosis is still useful after that evidence pass. "
        "Use mode='task' for immediate Task awareness; otherwise code_mode waits briefly and publishes "
        "the same continuing Execution only when inline delivery ends first. Transport loss never "
        "cancels work. Use the task tool for list/get/cancel/dismiss. Results are retained for 5 days."
    ),
)


def _expand_env_path(value: str) -> Path:
    """Expand shell-style $HOME variables and ~ without invoking a shell."""
    return Path(os.path.expandvars(value)).expanduser()


def _wiki_path() -> Path:
    """Resolve the trusted wiki path used by Hermes, with ~/wiki fallback."""
    configured = os.environ.get("WIKI_PATH", "").strip()
    if not configured:
        hermes_env = Path.home() / ".hermes" / ".env"
        if hermes_env.is_file():
            for raw_line in hermes_env.read_text(errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "WIKI_PATH":
                    configured = value.strip().strip('"').strip("'")
                    break
    return _expand_env_path(configured or "$HOME/wiki").resolve()


def _parse_preload_files(preload_text: str) -> list[str]:
    """Extract preload file paths from JSON configuration."""
    try:
        data = json.loads(preload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed bootstrap preload JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise TypeError("bootstrap preload JSON must be an object")

    paths = data.get("preload_files")
    if paths is None:
        raise ValueError("bootstrap preload JSON missing 'preload_files' field")
    if not isinstance(paths, list):
        raise TypeError("bootstrap preload JSON 'preload_files' field must be a list")
    if not paths:
        raise ValueError(
            "bootstrap preload JSON 'preload_files' list must not be empty"
        )

    for path in paths:
        if not isinstance(path, str):
            raise TypeError("preload_files entries must be strings")
        if not path.strip():
            raise ValueError("preload_files entries must not be empty strings")

    return paths


def _read_bootstrap_packet() -> dict[str, Any]:
    """Assemble compact fresh-session orientation from the trusted Wiki preload map."""
    wiki = _wiki_path()
    preload = wiki / "bootstrap" / "preload.json"
    if not preload.is_file():
        raise FileNotFoundError(f"bootstrap preload map not found: {preload}")

    preload_text = preload.read_text(errors="replace")
    preload_files = _parse_preload_files(preload_text)
    documents: list[dict[str, str]] = []
    warnings: list[str] = []

    for relative in preload_files:
        candidate = (wiki / relative).resolve()
        try:
            candidate.relative_to(wiki)
        except ValueError as exc:
            raise ValueError(
                f"bootstrap path escapes trusted wiki: {relative}"
            ) from exc

        if not candidate.is_file():
            warnings.append(f"missing preload document: {relative}")
            continue
        documents.append(
            {
                "path": relative,
                "content": candidate.read_text(errors="replace"),
            }
        )

    if not documents:
        raise RuntimeError(
            "bootstrap preload map resolved no readable preload documents"
        )

    preloaded_files = [doc["path"] for doc in documents]
    bootstrap_reminders = _read_reminder_sections(exclude_paths=set(preloaded_files))
    chunks: list[str] = [f"$HOME = {Path.home()}"]
    for doc in documents:
        source = _display_source_path(wiki / doc["path"])
        chunks.append(f"---\n`$ cat {source}`\n\n{doc['content'].rstrip()}")
    if bootstrap_reminders:
        chunks.append(_format_reminder_sections(bootstrap_reminders))

    result: dict[str, Any] = {
        "wiki_path": str(wiki),
        "preload_path": str(preload),
        "preloaded_files": preloaded_files,
        "bootstrap_reminders": [
            {key: value for key, value in item.items() if key != "content"}
            for item in bootstrap_reminders
        ],
        "stdout": "\n\n".join(chunks) + "\n",
    }
    if warnings:
        result["warnings"] = warnings
    return result


_PERIODIC_REMINDER_STATE_KEY = "gpt_dive_periodic_reminder_calls"
_PERIODIC_REMINDER_CONFIG = "bootstrap/reminder.json"


def _parse_reminder_config(
    reminder_text: str,
) -> tuple[int, list[tuple[str, str | None]]]:
    """Parse reminder cadence plus ordered whole-file or Markdown section sources."""
    try:
        data = json.loads(reminder_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed reminder JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("reminder JSON must be an object")

    interval = data.get("interval")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError("reminder interval must be a positive integer")

    raw_files = data.get("reminder_files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("reminder_files must be a non-empty list")

    files: list[tuple[str, str | None]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise TypeError("reminder_files entries must be objects")
        path = item.get("path")
        section = item.get("section")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("reminder file path must be a non-empty string")
        if section is not None and (
            not isinstance(section, str) or not section.strip()
        ):
            raise ValueError(
                "reminder section must be a non-empty string when provided"
            )
        files.append((path, section))
    return interval, files


def _read_periodic_reminder_config() -> tuple[int, list[tuple[str, str | None]]]:
    path = _wiki_path() / _PERIODIC_REMINDER_CONFIG
    return _parse_reminder_config(path.read_text(errors="replace"))


def _read_reminder_sections(
    *, exclude_paths: set[str] | None = None
) -> list[dict[str, str]]:
    """Read reminder sources in config order, optionally skipping whole source files."""
    wiki = _wiki_path()
    _, files = _read_periodic_reminder_config()
    excluded = exclude_paths or set()
    sections: list[dict[str, str]] = []
    for relative, heading in files:
        if relative in excluded:
            continue
        candidate = (wiki / relative).resolve()
        try:
            candidate.relative_to(wiki)
        except ValueError as exc:
            raise ValueError(f"reminder path escapes trusted wiki: {relative}") from exc
        text = candidate.read_text(errors="replace")
        if heading is None:
            sections.append({"path": relative, "content": text.rstrip()})
            continue
        match = re.search(
            rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## \S|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            raise ValueError(f"{relative} missing reminder section: {heading}")
        sections.append(
            {
                "path": relative,
                "section": heading,
                "content": f"## {heading}\n{match.group('body').rstrip()}",
            }
        )
    return sections


def _display_source_path(path: Path) -> str:
    """Render paths under the current home directory with a ~/ prefix."""
    resolved = path.resolve()
    home = Path.home().resolve()
    try:
        return f"~/{resolved.relative_to(home).as_posix()}"
    except ValueError:
        return str(resolved)


def _format_reminder_sections(sections: list[dict[str, str]]) -> str:
    """Format reminder sections with one source-file marker per consecutive file group."""
    wiki = _wiki_path()
    chunks: list[str] = []
    previous_path: str | None = None
    for item in sections:
        if item["path"] != previous_path:
            source = _display_source_path(wiki / item["path"])
            chunks.append(f"---\n`$ cat {source}`")
            previous_path = item["path"]
        chunks.append(item["content"])
    return "\n\n".join(chunks)


def _read_periodic_reminder() -> str:
    """Read every configured whole-file or section reminder in order."""
    return _format_reminder_sections(_read_reminder_sections())


def _periodic_reminder_state(ctx: ServerRequestContext[Any, Any]) -> dict[str, Any]:
    connection = getattr(ctx.session, "_connection", None)
    state = getattr(connection, "state", None)
    if not isinstance(state, dict):
        raise TypeError("MCP connection state is unavailable")
    return state


def _reset_periodic_reminder_counter(ctx: ServerRequestContext[Any, Any]) -> None:
    _periodic_reminder_state(ctx)[_PERIODIC_REMINDER_STATE_KEY] = 0


def _periodic_reminder_due(ctx: ServerRequestContext[Any, Any]) -> int | None:
    interval, _ = _read_periodic_reminder_config()
    state = _periodic_reminder_state(ctx)
    calls = int(state.get(_PERIODIC_REMINDER_STATE_KEY, 0)) + 1
    if calls < interval:
        state[_PERIODIC_REMINDER_STATE_KEY] = calls
        return None
    state[_PERIODIC_REMINDER_STATE_KEY] = 0
    return interval


def _tool_name_from_request(params: Any) -> str | None:
    if isinstance(params, dict):
        name = params.get("name")
    else:
        name = getattr(params, "name", None)
    return name if isinstance(name, str) else None


async def _tracked_tasks_middleware(
    ctx: ServerRequestContext[Any, Any], call_next: CallNext
) -> HandlerResult:
    if ctx.method != "tools/call":
        return await call_next(ctx)

    tool_name = _tool_name_from_request(ctx.params)
    result = await call_next(ctx)
    if (
        tool_name == "bootstrap"
        or not isinstance(result, CallToolResult)
        or result.is_error
    ):
        return result

    try:
        tasks = await asyncio.to_thread(_task_list, limit=TRACKED_TASKS_LIMIT)
        revision = runtime_projection_revision(tasks)
        state = _periodic_reminder_state(ctx)
        previous = state.get(_TRACKED_TASKS_REVISION_STATE_KEY)
        state[_TRACKED_TASKS_REVISION_STATE_KEY] = revision
        if tool_name == "task" or revision == previous:
            return result
        if previous is None and not tasks:
            return result
        text = _render_tracked_tasks(tasks) if tasks else "TrackedTasks\n(none)"
    except Exception:
        logger.exception("TRACKED TASKS PROJECTION FAILED")
        return result

    awareness = TextContent(type="text", text=f"\n\n{text}\n")
    return result.model_copy(update={"content": [*result.content, awareness]})


async def _periodic_reminder_middleware(
    ctx: ServerRequestContext[Any, Any], call_next: CallNext
) -> HandlerResult:
    if ctx.method != "tools/call":
        return await call_next(ctx)

    tool_name = _tool_name_from_request(ctx.params)
    result = await call_next(ctx)

    if tool_name == "bootstrap":
        if isinstance(result, CallToolResult) and not result.is_error:
            _reset_periodic_reminder_counter(ctx)
        return result

    if not isinstance(result, CallToolResult):
        return result
    reminder_interval = _periodic_reminder_due(ctx)
    if reminder_interval is None:
        return result

    refresh = TextContent(
        type="text",
        text=(
            f"\n\n===== PERIODIC DIVE REMINDER: {reminder_interval} tool calls =====\n"
            f"{_read_periodic_reminder()}\n"
            "===== END PERIODIC DIVE REMINDER =====\n"
        ),
    )
    return result.model_copy(update={"content": [*result.content, refresh]})


mcp.middleware.append(request_lifecycle_middleware)
mcp.middleware.append(_periodic_reminder_middleware)
mcp.middleware.append(_tracked_tasks_middleware)


def _task_list(*, limit: int | None = None) -> list[dict[str, Any]]:
    return runtime_list_projected_tasks(executions, limit=limit)


def _render_tracked_tasks(
    tasks: list[dict[str, Any]], *, limit: int = TRACKED_TASKS_LIMIT
) -> str:
    return runtime_render_tracked_tasks(tasks, limit=limit)


def _task_get(execution_id: str) -> dict[str, Any]:
    return runtime_get_task(executions, execution_id)


def _task_cancel(execution_id: str) -> dict[str, Any]:
    return runtime_cancel_task(executions, execution_id)


def _task_dismiss(execution_id: str) -> dict[str, Any]:
    return runtime_dismiss_task(executions, execution_id)


def _start_code_mode_execution(
    *,
    execution_id: str,
    label: str,
    code: str,
    cwd: str | None,
    payload: str | None,
    publish: bool,
) -> dict[str, Any]:
    request = {
        "v": CODE_MODE_WORKER_PROTOCOL,
        "code": code,
        "cwd": cwd,
        "payload": payload,
    }
    request_path = executions.root / execution_id / "input.json"
    command = (
        f"{shlex.quote(sys.executable)} -m gpt_dive.code_mode_worker "
        f"--store={shlex.quote(str(executions.store.path))} "
        f"--execution={shlex.quote(execution_id)} "
        f"--request={shlex.quote(str(request_path))}"
    )
    return executions.start(
        command,
        execution_id=execution_id,
        label=label,
        cwd=cwd,
        kind="code_mode",
        publish=publish,
        input_payload=request,
    )


def _track_runtime_followup(followup: asyncio.Task[None]) -> None:
    _PENDING_RUNTIME_FOLLOWUPS.add(followup)
    followup.add_done_callback(_PENDING_RUNTIME_FOLLOWUPS.discard)


async def _publish_accepted_task(
    manager: ExecutionManager, execution_id: str
) -> dict[str, Any]:
    return await asyncio.to_thread(manager.store.publish, execution_id)


async def _publish_for_transport_loss(
    manager: ExecutionManager, execution_id: str
) -> bool:
    try:
        await asyncio.shield(_publish_accepted_task(manager, execution_id))
    except asyncio.CancelledError, Exception:
        return False
    return True


async def _observe_launch(launch_task: asyncio.Task[dict[str, Any]]) -> None:
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await asyncio.shield(launch_task)


def _defer_launch_observation(
    launch_task: asyncio.Task[dict[str, Any]],
) -> None:
    _track_runtime_followup(asyncio.create_task(_observe_launch(launch_task)))


async def _publish_during_launch(
    manager: ExecutionManager,
    launch_task: asyncio.Task[dict[str, Any]],
    execution_id: str,
) -> None:
    published = False
    while not published and not launch_task.done():
        try:
            await _publish_accepted_task(manager, execution_id)
        except KeyError:
            await asyncio.sleep(0.01)
        except Exception:
            await asyncio.sleep(0.1)
        else:
            published = True
    await _observe_launch(launch_task)
    if not published:
        with contextlib.suppress(Exception):
            await _publish_accepted_task(manager, execution_id)


def _defer_publication_during_launch(
    manager: ExecutionManager,
    launch_task: asyncio.Task[dict[str, Any]],
    execution_id: str,
) -> None:
    _track_runtime_followup(
        asyncio.create_task(_publish_during_launch(manager, launch_task, execution_id))
    )


async def _preserve_interrupted_launch(
    manager: ExecutionManager,
    launch_task: asyncio.Task[dict[str, Any]],
    execution_id: str,
) -> None:
    if await _publish_for_transport_loss(manager, execution_id):
        _defer_launch_observation(launch_task)
        return
    _defer_publication_during_launch(manager, launch_task, execution_id)


async def _publish_execution(manager: ExecutionManager, execution_id: str) -> None:
    with contextlib.suppress(Exception):
        await _publish_accepted_task(manager, execution_id)


def _defer_execution_publication(manager: ExecutionManager, execution_id: str) -> None:
    _track_runtime_followup(
        asyncio.create_task(_publish_execution(manager, execution_id))
    )


async def _wait_for_acceptance(
    manager: ExecutionManager,
    launch_task: asyncio.Task[dict[str, Any]],
    execution_id: str,
    *,
    deadline: float,
) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Code Mode response deadline expired before acceptance"
            ) from None
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(manager.store.get, execution_id),
                timeout=remaining,
            )
        except KeyError:
            if launch_task.done():
                return await launch_task
            await asyncio.sleep(min(0.01, remaining))


def _code_mode_execution_result(execution_id: str) -> dict[str, Any]:
    return runtime_read_execution_result(executions, execution_id)


async def _wait_for_execution(
    execution_id: str, *, wait_deadline: float
) -> dict[str, Any]:
    while True:
        record = await asyncio.to_thread(executions.store.get, execution_id)
        if record["state"] not in {"accepted", "running"}:
            return await asyncio.to_thread(_code_mode_execution_result, execution_id)
        remaining = wait_deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.2, remaining))

    status = await asyncio.to_thread(executions.status, execution_id)
    if status["state"] not in {"accepted", "running"}:
        return await asyncio.to_thread(_code_mode_execution_result, execution_id)
    task = await _publish_accepted_task(executions, execution_id)
    return {
        "kind": "task",
        "execution_id": execution_id,
        "label": task["label"],
        "state": task["state"],
    }


ExecutionState = Literal[
    "accepted", "running", "completed", "failed", "cancelled", "lost"
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodeModeCompleted(_ClosedModel):
    kind: Literal["completed"] = "completed"
    execution_id: str
    label: str
    result: Any


class CodeModeTask(_ClosedModel):
    kind: Literal["task"] = "task"
    execution_id: str
    label: str
    state: ExecutionState


class CodeModeErrorDetail(_ClosedModel):
    code: str
    message: str
    reason: str | None = None
    worker_stderr: str | None = None


class CodeModeError(_ClosedModel):
    kind: Literal["error"] = "error"
    execution_id: str
    label: str
    error: CodeModeErrorDetail


CodeModeOutcome = Annotated[
    CodeModeCompleted | CodeModeTask | CodeModeError,
    Field(discriminator="kind"),
]
_CODE_MODE_OUTCOME_ADAPTER = TypeAdapter(CodeModeOutcome)


def _code_mode_outcome(value: dict[str, Any]) -> CodeModeOutcome:
    return _CODE_MODE_OUTCOME_ADAPTER.validate_python(value)


def _code_mode_delivery_error(
    execution_id: str,
    label: str,
    *,
    code: str,
    message: str,
) -> CodeModeError:
    return CodeModeError(
        execution_id=execution_id,
        label=label,
        error=CodeModeErrorDetail(code=code, message=message),
    )


async def _code_mode_launch_error(
    execution_id: str,
    label: str,
    exc: Exception,
    *,
    response_deadline: float,
) -> CodeModeError:
    remaining = response_deadline - time.monotonic()
    if remaining <= 0:
        raise exc from None
    try:
        record = await asyncio.wait_for(
            asyncio.to_thread(executions.store.get, execution_id),
            timeout=remaining,
        )
    except KeyError:
        raise exc from None
    except TimeoutError:
        raise TimeoutError(
            "Code Mode response deadline expired while shaping launch error"
        ) from None
    return CodeModeError(
        execution_id=execution_id,
        label=label,
        error=CodeModeErrorDetail(
            code="launch_interrupted",
            message=str(exc) or "Code Mode Worker could not be launched.",
            reason=str(record.get("reason") or "launch_interrupted"),
        ),
    )


async def code_mode(
    *,
    label: str,
    code: str,
    payload: str | None = None,
    cwd: str | None = None,
    mode: Literal["auto", "task"] = "auto",
) -> CodeModeOutcome:
    """Launch one always-durable Code Mode Execution."""
    clean_label = label.strip()
    if not clean_label:
        raise ValueError("label must not be empty")
    if len(clean_label) > 80:
        raise ValueError("label must be 80 characters or fewer")
    if not code.strip():
        raise ValueError("code must not be empty")

    execution_id = generate_execution_id()
    started_at = time.monotonic()
    wait_deadline = started_at + _INLINE_WAIT_SECONDS
    response_deadline = started_at + _INLINE_RESPONSE_DEADLINE_SECONDS
    launch_task = asyncio.create_task(
        asyncio.to_thread(
            _start_code_mode_execution,
            execution_id=execution_id,
            label=clean_label,
            code=code,
            cwd=cwd,
            payload=payload,
            publish=mode == "task",
        )
    )

    if mode == "task":
        try:
            task = await _wait_for_acceptance(
                executions,
                launch_task,
                execution_id,
                deadline=response_deadline,
            )
        except asyncio.CancelledError:
            await _preserve_interrupted_launch(executions, launch_task, execution_id)
            raise
        except Exception as exc:
            _defer_publication_during_launch(executions, launch_task, execution_id)
            return await _code_mode_launch_error(
                execution_id,
                clean_label,
                exc,
                response_deadline=response_deadline,
            )
        _defer_launch_observation(launch_task)
        return CodeModeTask(
            execution_id=execution_id,
            label=clean_label,
            state=task["state"],
        )

    try:
        await asyncio.wait_for(
            asyncio.shield(launch_task),
            timeout=max(0.0, wait_deadline - time.monotonic()),
        )
    except asyncio.CancelledError:
        await _preserve_interrupted_launch(executions, launch_task, execution_id)
        raise
    except TimeoutError:
        launch_exception = (
            launch_task.exception()
            if launch_task.done() and not launch_task.cancelled()
            else None
        )
        if isinstance(launch_exception, Exception):
            return await _code_mode_launch_error(
                execution_id,
                clean_label,
                launch_exception,
                response_deadline=response_deadline,
            )
        if not launch_task.done():
            try:
                await _wait_for_acceptance(
                    executions,
                    launch_task,
                    execution_id,
                    deadline=response_deadline,
                )
            except asyncio.CancelledError:
                await _preserve_interrupted_launch(
                    executions, launch_task, execution_id
                )
                raise
            except TimeoutError as exc:
                launch_exception = (
                    launch_task.exception()
                    if launch_task.done() and not launch_task.cancelled()
                    else None
                )
                if isinstance(launch_exception, Exception):
                    return await _code_mode_launch_error(
                        execution_id,
                        clean_label,
                        launch_exception,
                        response_deadline=response_deadline,
                    )
                _defer_publication_during_launch(executions, launch_task, execution_id)
                raise TimeoutError(
                    "Code Mode response deadline expired before acceptance"
                ) from exc
            except Exception as exc:
                return await _code_mode_launch_error(
                    execution_id,
                    clean_label,
                    exc,
                    response_deadline=response_deadline,
                )
            try:
                task = await asyncio.wait_for(
                    _publish_accepted_task(executions, execution_id),
                    timeout=max(0.0, response_deadline - time.monotonic()),
                )
            except asyncio.CancelledError:
                await _preserve_interrupted_launch(
                    executions, launch_task, execution_id
                )
                raise
            except TimeoutError:
                _defer_publication_during_launch(executions, launch_task, execution_id)
                return _code_mode_delivery_error(
                    execution_id,
                    clean_label,
                    code="response_deadline_exceeded",
                    message=(
                        "Code Mode Execution was accepted, but Task publication "
                        "did not finish before the response deadline."
                    ),
                )
            except Exception as exc:
                _defer_publication_during_launch(executions, launch_task, execution_id)
                return _code_mode_delivery_error(
                    execution_id,
                    clean_label,
                    code="task_publication_failed",
                    message=str(exc) or "Task publication failed.",
                )
            _defer_launch_observation(launch_task)
            return CodeModeTask(
                execution_id=execution_id,
                label=clean_label,
                state=task["state"],
            )
    except Exception as exc:
        return await _code_mode_launch_error(
            execution_id,
            clean_label,
            exc,
            response_deadline=response_deadline,
        )

    remaining_response = max(0.0, response_deadline - time.monotonic())
    try:
        raw = await asyncio.wait_for(
            _wait_for_execution(execution_id, wait_deadline=wait_deadline),
            timeout=remaining_response,
        )
    except asyncio.CancelledError:
        if not await _publish_for_transport_loss(executions, execution_id):
            _defer_execution_publication(executions, execution_id)
        raise
    except TimeoutError:
        _defer_execution_publication(executions, execution_id)
        return _code_mode_delivery_error(
            execution_id,
            clean_label,
            code="response_deadline_exceeded",
            message=(
                "Code Mode Execution was accepted, but response shaping did not "
                "finish before the response deadline."
            ),
        )
    return _code_mode_outcome(raw)


@mcp.tool(
    name="code_mode",
    title="Pydantic Monty Code Mode",
    description=(
        "Launch one always-durable Pydantic Monty Execution. label and code are required. "
        "mode='auto' waits up to the bounded inline delivery window and otherwise returns "
        "a Task handle for the same continuing Execution; mode='task' publishes that Task "
        "immediately. Prefer registered capabilities, inspect CAPABILITIES instead of inventing "
        "arguments, use PAYLOAD for data, and use asyncio.gather only for independent work."
    ),
)
async def _mcp_code_mode(
    label: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description="Required short Execution label used by Preview and Task awareness.",
        ),
    ],
    code: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Monty/Python orchestration. Call registered capabilities directly; keep opaque "
                "or multiline data in payload/PAYLOAD and inspect CAPABILITIES when uncertain."
            ),
        ),
    ],
    payload: Annotated[
        str | None,
        Field(description="Optional opaque string exposed to Monty code as PAYLOAD."),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Optional default WSL2 working directory exposed to code as CWD and inherited by "
                "registered capabilities when supported. CWD is a path string, not process chdir."
            )
        ),
    ] = None,
    mode: Annotated[
        Literal["auto", "task"],
        Field(
            description=(
                "auto waits for bounded inline delivery; task publishes awareness immediately. "
                "Both modes run the same always-durable Execution."
            )
        ),
    ] = "auto",
) -> CodeModeOutcome:
    return await code_mode(
        label=label,
        code=code,
        cwd=cwd,
        payload=payload,
        mode=mode,
    )


class TaskListRequest(_ClosedModel):
    action: Literal["list"]


class TaskGetRequest(_ClosedModel):
    action: Literal["get"]
    execution_id: Annotated[str, Field(pattern=EXECUTION_ID_PATTERN)]


class TaskCancelRequest(_ClosedModel):
    action: Literal["cancel"]
    execution_id: Annotated[str, Field(pattern=EXECUTION_ID_PATTERN)]


class TaskDismissRequest(_ClosedModel):
    action: Literal["dismiss"]
    execution_id: Annotated[str, Field(pattern=EXECUTION_ID_PATTERN)]


TaskRequest = Annotated[
    TaskListRequest | TaskGetRequest | TaskCancelRequest | TaskDismissRequest,
    Field(discriminator="action"),
]


class TaskView(_ClosedModel):
    execution_id: str
    label: str
    state: ExecutionState
    reason: str | None
    accepted_at: str
    finished_at: str | None
    published_at: str
    updated_at: str
    elapsed_seconds: int


class TaskListOutput(_ClosedModel):
    action: Literal["list"] = "list"
    tasks: list[TaskView]


class TaskGetOutput(_ClosedModel):
    action: Literal["get"] = "get"
    task: TaskView
    ready: bool
    unavailable: bool = False
    result: Any | None = None


class TaskCancelOutput(_ClosedModel):
    action: Literal["cancel"] = "cancel"
    task: TaskView


class TaskDismissOutput(_ClosedModel):
    action: Literal["dismiss"] = "dismiss"
    execution_id: str
    state: ExecutionState
    dismissed: bool


TaskOutcome = Annotated[
    TaskListOutput | TaskGetOutput | TaskCancelOutput | TaskDismissOutput,
    Field(discriminator="action"),
]


def _task_view(value: dict[str, Any]) -> TaskView:
    return TaskView.model_validate(value)


@mcp.tool(
    name="task",
    title="GPT Dive Task Lifecycle",
    description=(
        "Operate a published Code Mode Task by its single execution_id. list returns "
        "outstanding awareness, get reads status/result non-destructively, cancel explicitly "
        "cancels running work, and dismiss removes terminal awareness without deleting retention."
    ),
)
async def task(request: TaskRequest) -> TaskOutcome:
    if isinstance(request, TaskListRequest):
        rows = await asyncio.to_thread(_task_list, limit=_TASK_LIST_LIMIT)
        return TaskListOutput(tasks=[_task_view(row) for row in rows])
    if isinstance(request, TaskGetRequest):
        result = await asyncio.to_thread(_task_get, request.execution_id)
        return TaskGetOutput(
            task=_task_view(result["task"]),
            ready=bool(result["ready"]),
            unavailable=bool(result.get("unavailable", False)),
            result=result.get("result"),
        )
    if isinstance(request, TaskCancelRequest):
        result = await asyncio.to_thread(_task_cancel, request.execution_id)
        return TaskCancelOutput(task=_task_view(result["task"]))
    result = await asyncio.to_thread(_task_dismiss, request.execution_id)
    return TaskDismissOutput.model_validate({"action": "dismiss", **result})


@mcp.tool(
    title="Bootstrap from Local WSL2 Wiki",
    description=(
        "Always call `bootstrap` first in a fresh ChatGPT Web session, before using any other "
        "`@dive` tool. It loads the compact, model-visible preload map plus foundational "
        "orientation from the trusted Wiki in the user's local WSL2 environment."
    ),
)
def bootstrap() -> dict[str, Any]:
    """Load compact fresh-session orientation from the trusted local Wiki preload map."""
    return _read_bootstrap_packet()


if __name__ == "__main__":
    mcp.run()
