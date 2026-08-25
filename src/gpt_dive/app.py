from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp_types import CallToolResult, TextContent
from pydantic import Field

from .code_capabilities import build_code_registry, code_runtime
from .command_runtime import run_command as _run_command
from .execution_manager import ExecutionManager
from .runtime_diagnostics import request_lifecycle_middleware
from .task_runtime import CODE_MODE_WORKER_PROTOCOL, TaskRuntime
from .task_runtime import ack_task as runtime_ack_task
from .task_runtime import cancel_task as runtime_cancel_task
from .task_runtime import (
    cleanup_code_mode_request as _runtime_cleanup_code_mode_request,
)
from .task_runtime import code_mode_request_dir as _runtime_code_mode_request_dir
from .task_runtime import code_mode_request_ref as _runtime_code_mode_request_ref
from .task_runtime import collect_task as runtime_collect_task
from .task_runtime import list_projected_tasks as _runtime_list_projected_tasks
from .task_runtime import read_execution_result as _runtime_read_execution_result
from .task_runtime import render_tracked_tasks as runtime_render_tracked_tasks
from .task_store import TaskStore
from .tasks_extension import TasksExtension

executions = ExecutionManager()
task_store = TaskStore()
tasks_extension = TasksExtension(executions)

mcp = MCPServer(
    name="gpt-dive",
    title="GPT Dive",
    description=(
        "Direct ChatGPT Web -> WSL2 runtime. Call bootstrap first. Use code_mode as the "
        "default programmable root for normal local work: compose registered capabilities in "
        "Monty/Python, prefer direct capabilities over shell reimplementation, and use the "
        "Pydantic run_command capability for foreground shell execution. Every MCP code_mode call requires "
        "string payload; use payload='' when there is no data. Never guess capability names, "
        "arguments, or return shapes: inspect the live contract first. On tool errors, inspect "
        "the live contract and local evidence before retrying; use Web Search when the missing "
        "fact is external and current."
    ),
    instructions=(
        "GPT Dive operates the user's local WSL2 environment. Treat its filesystem, "
        "processes, network state, and command results as belonging to the user's local "
        "machine, not as a separate hosted or ChatGPT sandbox. In a fresh ChatGPT Web "
        "session, call bootstrap first. After bootstrap, use code_mode as the default programmable "
        "root for normal local work. Write Monty/Python orchestration, prefer registered capabilities "
        "that directly match the operation, await dependencies sequentially, and use asyncio.gather "
        "for independent work. Use Pydantic run_command only when shell execution is actually required; "
        "do not rebuild file/search/edit operations in shell. Every Web MCP code_mode call must explicitly "
        "provide payload as a string; use payload='' when there is no payload or for lifecycle calls. "
        "Never pass an object/list as payload; serialize structured payloads to text and parse them "
        "inside Code Mode if needed. Never invent capability names, parameter names, optional arguments, "
        "or return shapes from memory. Inspect the live MCP schema/CAPABILITIES contract first whenever "
        "uncertain. On tool errors or assistant mistakes, report them immediately and inspect the live "
        "contract plus local state before retrying. Use Web Search only when the missing evidence is "
        "external and current. Use /grill-me only when deeper "
        "diagnosis is still useful after that evidence pass. Use wsl2_sync only for transport/smoke, "
        "explicit user requests, exceptional WSL/Win11 maintenance, or cases where Code Mode is genuinely inapplicable; use "
        "wsl2_async for durable background execution "
        "lifecycle operations. Background executions survive MCP server restarts and completed execution "
        "logs are retained for 5 days. When the client negotiates "
        "io.modelcontextprotocol/tasks, wsl2_async start can use the standard MCP Tasks "
        "lifecycle."
    ),
    extensions=[tasks_extension],
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
        tasks = await asyncio.to_thread(_task_list, limit=8)
        if not tasks:
            return result
        text = _render_tracked_tasks(tasks)
    except Exception:
        text = "TrackedTasks unavailable"

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


_DIRECT_WSL_PERMISSION = "for-special-such-as-exceptional-wsl-win11-maintenance; no-stupid-blind-broad-recursive-search"


@mcp.tool(
    title="Synchronous WSL2",
    description=(
        "Execute a short shell command synchronously inside the user's local WSL2 and return "
        "its result immediately. This is an exceptional direct-shell path for transport/smoke or "
        "special WSL/Win11 maintenance; use code_mode for normal local work and wsl2_async for "
        "durable background executions. Keep timeout only slightly above the expected runtime."
    ),
)
def wsl2_sync(
    command: Annotated[
        str,
        Field(description="Shell command to run via /bin/bash -lc."),
    ],
    permission: Annotated[
        str,
        Field(
            description=(
                "Required exact harness declaration for direct WSL execution: "
                f"{_DIRECT_WSL_PERMISSION}"
            )
        ),
    ],
    cwd: Annotated[
        str | None,
        Field(description="Optional WSL2 working directory."),
    ] = None,
    timeout: Annotated[
        float,
        Field(
            gt=0,
            description="Maximum runtime in seconds (default: 600).",
        ),
    ] = 600.0,
) -> dict[str, Any]:
    """Run a short explicitly authorized shell command in the user's local WSL2."""
    if permission != _DIRECT_WSL_PERMISSION:
        raise ValueError(
            "wsl2_sync permission mismatch; use the exact harness declaration from the live schema"
        )
    return _run_command(command, cwd, timeout)


def _code_mode_request_dir() -> Path:
    path = _runtime_code_mode_request_dir(executions)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _code_mode_request_ref(execution_id: str) -> Path:
    return _runtime_code_mode_request_ref(executions, execution_id)


def _cleanup_code_mode_request(execution_id: str) -> None:
    _runtime_cleanup_code_mode_request(executions, execution_id)


def _task_runtime() -> TaskRuntime:
    """Assemble the pair at call time so tests can swap either half."""
    return TaskRuntime(executions, task_store)


def _task_list(*, limit: int | None = None) -> list[dict[str, Any]]:
    return _runtime_list_projected_tasks(_task_runtime(), limit=limit)


def _render_tracked_tasks(tasks: list[dict[str, Any]], *, limit: int = 8) -> str:
    return runtime_render_tracked_tasks(tasks, limit=limit)


def _task_collect(task_id: str) -> dict[str, Any]:
    return runtime_collect_task(_task_runtime(), task_id)


def _task_cancel(task_id: str) -> dict[str, Any]:
    return runtime_cancel_task(_task_runtime(), task_id)


def _task_ack(task_id: str) -> dict[str, Any]:
    return runtime_ack_task(_task_runtime(), task_id)


def _start_background_code_mode(
    code: str,
    cwd: str | None,
    payload: str | None,
    label: str | None,
    status_cmd: str | None,
    status: str | None,
) -> dict[str, Any]:
    request = {
        "v": CODE_MODE_WORKER_PROTOCOL,
        "code": code,
        "cwd": cwd,
        "payload": payload,
    }
    request_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="code-mode-",
            dir=_code_mode_request_dir(),
            delete=False,
        ) as fh:
            json.dump(request, fh, ensure_ascii=False, allow_nan=False)
            fh.write("\n")
            request_path = Path(fh.name)

        request_arg = shlex.quote(str(request_path))
        command = (
            f"{shlex.quote(sys.executable)} -m gpt_dive.code_mode_worker {request_arg}"
        )
        started = executions.start(command, cwd, 600.0)
        execution_id = str(started["execution_id"])
        try:
            _code_mode_request_ref(execution_id).write_text(str(request_path) + "\n")
        except OSError:
            executions.cancel(execution_id)
            request_path.unlink(missing_ok=True)
            raise
        if label is None:
            return started
        try:
            task = task_store.create(
                execution_id=execution_id,
                label=label,
                status_cmd=status_cmd,
                status=status,
            )
        except Exception:
            _cleanup_code_mode_request(execution_id)
            executions.cancel(execution_id)
            raise
        return {
            "task_id": task["task_id"],
            "execution_id": task["execution_id"],
            "label": task["label"],
            "state": task["state"],
        }
    except Exception:
        if request_path is not None:
            request_path.unlink(missing_ok=True)
        raise


def _background_code_mode_result(execution_id: str) -> dict[str, Any]:
    result = _runtime_read_execution_result(executions, execution_id)
    if result.get("ready") is False:
        raise RuntimeError(
            f"code_mode background execution {execution_id!r} is still running"
        )
    return result


async def code_mode(
    code: Annotated[
        str | None,
        Field(
            description=(
                "Monty/Python executable orchestration. Prefer registered capabilities that directly "
                "match the operation instead of rebuilding them in shell. Keep multiline/quoted data in "
                "payload and read it as PAYLOAD. Decide dependencies before calling: dependent work stays "
                "sequential; independent awaits may use asyncio.gather(...). Process large results inside "
                "Code Mode and make the final expression compact. CWD is a path string, not process chdir. "
                "BACKGROUND is runtime-injected from the actual outer execution mode. Never guess capability "
                "contracts; inspect CAPABILITIES when uncertain."
            )
        ),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Optional default WSL2 working directory exposed to code as CWD and inherited "
                "by registered capabilities. Does not chdir Monty itself; prefer registered "
                "FileSystem/Shell capabilities for workspace operations."
            )
        ),
    ] = None,
    payload: Annotated[
        str | None,
        Field(
            description=(
                "Optional opaque payload/data exposed to Monty code as PAYLOAD. Prefer payload for "
                "multiline or quoted payloads, including code, shell snippets, JSON, Markdown, "
                "quotes/backticks/$(), instead of embedding them in code. Keep code as executable "
                "logic and PAYLOAD as data to avoid parser/escaping failures."
            )
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(
            description="Detach this Code Mode program as a durable background execution."
        ),
    ] = False,
    label: Annotated[
        str | None,
        Field(
            description="Optional non-empty Task label for a Task-aware background launch (max 80 characters).",
            max_length=80,
        ),
    ] = None,
    status_cmd: Annotated[
        str | None,
        Field(
            description="Optional bounded local command whose stdout decorates a working Task."
        ),
    ] = None,
    status: Annotated[
        str | None,
        Field(
            description="Optional static Task display status used when status_cmd has no usable output."
        ),
    ] = None,
    action: Annotated[
        Literal["status", "result", "cancel"] | None,
        Field(
            description="Lifecycle action for a background Code Mode execution: status, result, or cancel."
        ),
    ] = None,
    execution_id: Annotated[
        str | None,
        Field(description="Background Code Mode execution ID for lifecycle actions."),
    ] = None,
) -> dict[str, Any]:
    """Execute or manage one stateless Monty program."""
    normalized_action = action.strip().lower() if action is not None else None
    has_code = code is not None and bool(code.strip())
    clean_label = label.strip() if label is not None else None
    clean_status_cmd = (
        status_cmd.strip() if status_cmd is not None and status_cmd.strip() else None
    )
    clean_status = status.strip() if status is not None and status.strip() else None
    if label is not None and not clean_label:
        raise ValueError("label must not be empty")
    if clean_label is not None and len(clean_label) > 80:
        raise ValueError("label must be 80 characters or fewer")
    if (
        clean_status_cmd is not None or clean_status is not None
    ) and clean_label is None:
        raise ValueError("status fields require a labeled background Task")

    if normalized_action is None:
        if not has_code:
            raise ValueError(
                "code_mode requires code unless action + execution_id are provided"
            )
        if execution_id is not None:
            raise ValueError("execution_id is only valid with a lifecycle action")
        if background:
            return await asyncio.to_thread(
                _start_background_code_mode,
                str(code),
                cwd,
                payload,
                clean_label,
                clean_status_cmd,
                clean_status,
            )
        if clean_label is not None:
            raise ValueError("label is only valid with background code")
        return await code_runtime.run(
            str(code),
            build_code_registry(
                cwd,
                run_command=_run_command,
                task_list=_task_list,
                task_collect=_task_collect,
                task_cancel=_task_cancel,
                task_ack=_task_ack,
            ),
            cwd=cwd,
            payload=payload,
        )

    if has_code:
        raise ValueError("code and lifecycle action are mutually exclusive")
    if background:
        raise ValueError("background is only valid when launching code")
    if clean_label is not None:
        raise ValueError("label is only valid with background code")
    if clean_status_cmd is not None or clean_status is not None:
        raise ValueError("status fields require a labeled background Task")
    if cwd is not None:
        raise ValueError("cwd is only valid when launching code")
    if payload is not None:
        raise ValueError("payload is only valid when launching code")
    if execution_id is None or not execution_id.strip():
        raise ValueError(
            f"code_mode action={normalized_action!r} requires execution_id"
        )
    if normalized_action == "status":
        state = await asyncio.to_thread(executions.status, execution_id)
        if state.get("status") != "running":
            await asyncio.to_thread(_cleanup_code_mode_request, execution_id)
        return state
    if normalized_action == "result":
        return await asyncio.to_thread(_background_code_mode_result, execution_id)
    if normalized_action == "cancel":
        state = await asyncio.to_thread(executions.cancel, execution_id)
        await asyncio.to_thread(_cleanup_code_mode_request, execution_id)
        return state
    raise ValueError("unsupported code_mode action; choose status, result, or cancel")


@mcp.tool(
    name="code_mode",
    title="Pydantic Monty Code Mode",
    description=(
        "Primary programmable execution root for GPT Dive, backed by Pydantic Monty.\n"
        "- Write code as Monty/Python orchestration, not as a shell script.\n"
        "- Prefer registered capabilities directly for file, search, edit, and other matched operations.\n"
        "- Decide dependencies first: await dependent work sequentially; use asyncio.gather(...) for independent work.\n"
        "- Use Pydantic run_command only when shell execution is required; pass multiline shell through PAYLOAD when needed.\n"
        "- Every MCP call requires payload as a string; use payload='' when there is no data.\n"
        "- CAPABILITIES provides the live inner capability signatures + descriptions.\n"
        "- Never invent capability names, arguments, optional fields, or return shapes; inspect the live contract first.\n"
        "- Use PAYLOAD for payload data and CWD as the capability workspace.\n"
        "- BACKGROUND is a runtime-injected bool reflecting the actual outer execution mode.\n"
        "- Use background=True only for detached Code Mode executions."
    ),
)
async def _mcp_code_mode(
    payload: Annotated[
        str,
        Field(
            description=(
                "Required opaque string payload exposed to Monty code as PAYLOAD. Always provide this "
                "field: use payload='' when no data is needed or for lifecycle actions. Never pass "
                "an object/list directly. For structured data, serialize it to text first and parse "
                "inside Code Mode. Payload is data; a shell script belongs here only when the Monty "
                "program intentionally invokes bash for shell semantics."
            )
        ),
    ],
    code: Annotated[
        str | None,
        Field(
            description=(
                "Monty/Python executable orchestration. Call registered capabilities directly and do "
                "not place shell scripts here. Keep payload/data in PAYLOAD. Decide dependencies before "
                "calling: dependent work is sequential and independent work may use asyncio.gather(...). "
                "Do not guess capability contracts; inspect CAPABILITIES/live schema when uncertain."
            )
        ),
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
    background: Annotated[
        bool,
        Field(
            description="Detach this Code Mode program as a durable background execution; the actual mode is exposed inside Monty as BACKGROUND."
        ),
    ] = False,
    label: Annotated[
        str | None,
        Field(
            description="Optional non-empty Task label for a Task-aware background launch (max 80 characters).",
            max_length=80,
        ),
    ] = None,
    status_cmd: Annotated[
        str | None,
        Field(
            description="Optional bounded local command whose stdout decorates a working Task."
        ),
    ] = None,
    status: Annotated[
        str | None,
        Field(
            description="Optional static Task display status used when status_cmd has no usable output."
        ),
    ] = None,
    action: Annotated[
        Literal["status", "result", "cancel"] | None,
        Field(
            description="Lifecycle action for a background Code Mode execution: status, result, or cancel."
        ),
    ] = None,
    execution_id: Annotated[
        str | None,
        Field(description="Background Code Mode execution ID for lifecycle actions."),
    ] = None,
) -> dict[str, Any]:
    """Model-facing Code Mode wrapper with an explicit payload/PAYLOAD contract."""
    if action is not None and payload != "":
        raise ValueError(
            "code_mode lifecycle calls require payload='' because lifecycle actions have no payload"
        )
    return await code_mode(
        code=code,
        cwd=cwd,
        payload=payload if action is None else None,
        background=background,
        label=label,
        status_cmd=status_cmd,
        status=status,
        action=action,
        execution_id=execution_id,
    )


def _required_execution_id(action: str, execution_id: str | None) -> str:
    if execution_id is None or not execution_id.strip():
        raise ValueError(f"wsl2_async action={action!r} requires execution_id")
    return execution_id


@mcp.tool(
    title="Asynchronous WSL2 Executions",
    description=(
        "Operate durable asynchronous WSL2 executions through one stable action-based interface. "
        "Use action='capabilities' to discover the actions supported by the current backend. "
        "Long-running executions survive MCP server restarts; completed logs are retained for 5 days."
    ),
)
def wsl2_async(
    action: Annotated[
        str,
        Field(
            description="Async-execution action; use 'capabilities' to list supported actions."
        ),
    ],
    command: Annotated[
        str | None,
        Field(description="Shell command for start."),
    ] = None,
    permission: Annotated[
        str | None,
        Field(
            description=(
                "Required exact harness declaration for direct WSL execution start: "
                f"{_DIRECT_WSL_PERMISSION}"
            )
        ),
    ] = None,
    execution_id: Annotated[
        str | None,
        Field(description="Execution ID for status/result/cancel."),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(description="Optional WSL2 working directory for start."),
    ] = None,
    timeout: Annotated[
        float,
        Field(
            gt=0,
            description="Maximum runtime in seconds for start (default: 600).",
        ),
    ] = 600.0,
) -> dict[str, Any]:
    """Dispatch a durable WSL2 execution lifecycle action."""
    normalized = action.strip().lower()
    if normalized == "capabilities":
        return {
            "actions": {
                "start": {
                    "requires": ["command", "permission"],
                    "optional": ["cwd", "timeout"],
                },
                "status": {"requires": ["execution_id"]},
                "result": {"requires": ["execution_id"]},
                "cancel": {"requires": ["execution_id"]},
            }
        }
    if normalized == "start":
        if command is None or not command.strip():
            raise ValueError("wsl2_async action='start' requires command")
        if permission != _DIRECT_WSL_PERMISSION:
            raise ValueError(
                "wsl2_async permission mismatch; use the exact harness declaration from the live schema"
            )
        return executions.start(command, cwd, timeout)
    if normalized == "status":
        return executions.status(_required_execution_id(normalized, execution_id))
    if normalized == "result":
        return executions.result(_required_execution_id(normalized, execution_id))
    if normalized == "cancel":
        return executions.cancel(_required_execution_id(normalized, execution_id))
    raise ValueError(
        f"unsupported wsl2_async action: {action!r}; use action='capabilities' to discover actions"
    )


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
