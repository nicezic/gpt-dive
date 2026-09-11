from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import sqlite3
import sys
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp_types import CallToolResult, TextContent
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_serializer,
)

from .code_capabilities import code_mode_capability_catalog
from .code_mode_protocol import CODE_MODE_WORKER_PROTOCOL
from .command_runtime import WSL_EXEC_TIMEOUT_SECONDS, run_wsl_command
from .execution_manager import ExecutionManager
from .execution_store import EXECUTION_ID_PATTERN, generate_execution_id
from .runtime_diagnostics import (
    normalize_tool_error_middleware,
    request_lifecycle_middleware,
)

_INLINE_WAIT_SECONDS = 100.0
_INLINE_RESPONSE_DEADLINE_SECONDS = 110.0
_TASK_LIST_LIMIT = 50
_RUNTIME_FOLLOWUPS: set[asyncio.Task[None]] = set()
TRACKED_TASKS_LIMIT = 8
TRACKED_TASKS_MAX_BYTES = 4096
_RUN_COMMAND_STDERR_PREVIEW_CHARS = 4000
_ERROR_DETAIL_MAX_CHARS = 4096
_CODE_MODE_CAPABILITY_CATALOG = code_mode_capability_catalog()

# MCP 2.0.0's generated ArgModelBase otherwise ignores unknown arguments. Closing
# the base before tool registration makes both validation and advertised schemas strict.
ArgModelBase.model_config["extra"] = "forbid"

logger = logging.getLogger("gpt_dive.runtime")

executions = ExecutionManager()

mcp = MCPServer(
    name="gpt-dive",
    title="GPT Dive",
    description=(
        "Direct ChatGPT Web -> WSL2 runtime. wsl_exec has a default-deny caller assertion guard; "
        "it does not prove user-origin authorization. code_mode launches durable Executions and task "
        "manages their lifecycle. Never guess "
        "capability names, arguments, or return shapes: inspect the live contract first."
    ),
    instructions=(
        "GPT Dive operates the user's local WSL2 environment. Treat its filesystem, "
        "processes, network state, and command results as belonging to the user's local "
        "machine, not as a separate hosted or ChatGPT sandbox. Use bootstrap before structured "
        "code_mode work in a fresh session. code_mode is the durable Monty/Python orchestration "
        "path: prefer registered capabilities "
        "that directly match the operation, await dependencies sequentially, and use asyncio.gather "
        "for independent work. Every Web MCP code_mode call must provide a short label. When opaque "
        "input is needed, pass payload as a string; serialize objects/lists to text and parse PAYLOAD "
        "inside Code Mode. Never invent capability names, parameter names, optional arguments, or "
        "return shapes from memory. Inspect the live MCP schema/CAPABILITIES contract first whenever "
        "uncertain. On tool errors or assistant mistakes, report them immediately and inspect the "
        "live contract plus local state before retrying. When an error carries a machine code or "
        "boundary, preserve its machine code and boundary verbatim. MCP.SERVER.UNHANDLED means the "
        "MCP server observed an unexpected tool failure; a top-level transport/502 with no "
        "CodeModeFailed payload is outside the Code Mode application error contract. Use Web Search "
        "only when the missing evidence is external and current. Use delivery='task' for immediate "
        "Task awareness; otherwise code_mode "
        "waits briefly and publishes the same continuing Execution only when inline delivery ends "
        "first. Transport loss never cancels work. Every successful ordinary work result includes "
        "tracked_tasks as compact passive awareness with elapsed_seconds, so background completion "
        "is rediscovered without remembered polling. task(list) is explicit detailed inspection, "
        "not polling; task(get) is non-destructive result pickup, and task(dismiss) removes terminal "
        "awareness. Program output semantics stay separate from Task awareness. Results are retained "
        "for 5 days."
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


def _format_byte_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _bounded_stderr_preview(data: bytes) -> str:
    text = data.decode(errors="replace")
    if len(text) <= _RUN_COMMAND_STDERR_PREVIEW_CHARS:
        return text
    marker = "\n… stderr truncated …\n"
    head = _RUN_COMMAND_STDERR_PREVIEW_CHARS // 2
    tail = _RUN_COMMAND_STDERR_PREVIEW_CHARS - head - len(marker)
    return text[:head] + marker + text[-tail:]


_CODE_MODE_RESULT_MAX_BYTES = 128 * 1024  # 128 KiB


def _bound_code_mode_result(result: Any, execution_id: str | None = None) -> Any:
    if isinstance(result, str):
        encoded = result.encode("utf-8", errors="replace")
        if len(encoded) <= _CODE_MODE_RESULT_MAX_BYTES:
            return result
        prefix = encoded[:_CODE_MODE_RESULT_MAX_BYTES].decode("utf-8", errors="ignore")
        marker = (
            f"\n\n... (output truncated at 128 KiB; execution_id: {execution_id or 'unknown'})"
        )
        return prefix + marker

    try:
        serialized = json.dumps(result, ensure_ascii=False)
    except Exception:
        return result

    encoded = serialized.encode("utf-8", errors="replace")
    if len(encoded) <= _CODE_MODE_RESULT_MAX_BYTES:
        return result

    prefix = encoded[:_CODE_MODE_RESULT_MAX_BYTES].decode("utf-8", errors="ignore")
    marker = (
        f"\n\n... (output truncated at 128 KiB; execution_id: {execution_id or 'unknown'})"
    )
    return prefix + marker


def _processed_output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False, indent=2)


def _render_code_mode_completed_result(execution_id: str, result: Any) -> Any:
    try:
        evidence_rows = executions.store.list_run_command_evidence(execution_id)
    except KeyError, sqlite3.Error:
        return _bound_code_mode_result(result, execution_id)
    if not evidence_rows or any(
        row.get("exit_code") is None or row.get("duration_ms") is None
        for row in evidence_rows
    ):
        return _bound_code_mode_result(result, execution_id)

    lines = [f"id: {execution_id}", ""]
    for row in evidence_rows:
        index = int(row["run_ordinal"]) - 1
        size = len(row["stdout"]) + len(row["stderr"])
        line = (
            f"[{index}] {int(row['exit_code'])}, {int(row['duration_ms'])} ms, "
            f"{_format_byte_size(size)}"
        )
        stderr = bytes(row["stderr"])
        if stderr:
            lines.extend([line + ", stderr ↓", _bounded_stderr_preview(stderr)])
        else:
            lines.append(line)
    lines.extend(["", "----", _processed_output_text(result)])
    return _bound_code_mode_result("\n".join(lines), execution_id)


_render_code_mode_completed_output = _render_code_mode_completed_result


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
mcp.middleware.append(normalize_tool_error_middleware)
mcp.middleware.append(_periodic_reminder_middleware)


def _task_list(*, limit: int | None = None) -> list[dict[str, Any]]:
    return executions.tasks(limit=limit)


def _task_get(execution_id: str) -> dict[str, Any]:
    return executions.task_with_result(execution_id)


def _task_cancel(execution_id: str) -> dict[str, Any]:
    return executions.cancel_task(execution_id)


def _task_dismiss(execution_id: str) -> dict[str, Any]:
    return executions.dismiss_task(execution_id)


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


def _spawn_followup(coro: Coroutine[Any, Any, None]) -> None:
    followup = asyncio.create_task(coro)
    _RUNTIME_FOLLOWUPS.add(followup)
    followup.add_done_callback(_RUNTIME_FOLLOWUPS.discard)


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


async def _preserve_interrupted_launch(
    manager: ExecutionManager,
    launch_task: asyncio.Task[dict[str, Any]],
    execution_id: str,
) -> None:
    if await _publish_for_transport_loss(manager, execution_id):
        _spawn_followup(_observe_launch(launch_task))
        return
    _spawn_followup(_publish_during_launch(manager, launch_task, execution_id))


async def _publish_execution(manager: ExecutionManager, execution_id: str) -> None:
    with contextlib.suppress(Exception):
        await _publish_accepted_task(manager, execution_id)


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
    return executions.result(execution_id)


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
        "status": "running",
        "execution_id": execution_id,
        "state": task["state"],
        "elapsed_seconds": task.get("elapsed_seconds", 0),
    }


ExecutionState = Literal[
    "accepted", "running", "completed", "failed", "cancelled", "lost"
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_serializer(mode="wrap")
    def _serialize_omit_none(self, handler: Any) -> Any:
        dump = handler(self)
        if isinstance(dump, dict):
            return {
                k: v
                for k, v in dump.items()
                if not (k in {"tracked_tasks", "tracked_tasks_guidance"} and v is None)
            }
        return dump


class TrackedTaskView(_ClosedModel):
    execution_id: str
    label: str
    state: ExecutionState
    reason: str | None
    elapsed_seconds: int


_TRACKED_TASKS_GUIDANCE = (
    "Passive background HUD. Continue current turn without polling. "
    "When ready or completed, retrieve via task(action='get', execution_id=...) and dismiss."
)


class CodeModeCompleted(_ClosedModel):
    status: Literal["completed"] = "completed"
    execution_id: str
    result: Any
    tracked_tasks: list[TrackedTaskView] | None = None
    tracked_tasks_guidance: str | None = None

    @field_validator("result", mode="after")
    @classmethod
    def _validate_result(cls, v: Any, info: ValidationInfo) -> Any:
        exec_id = info.data.get("execution_id") if info.data else None
        return _bound_code_mode_result(v, exec_id)


_CODE_MODE_RUNNING_GUIDANCE = (
    "Execution continues in background. "
    "Use task(action='get', execution_id=...) to inspect status or retrieve result."
)


class CodeModeRunning(_ClosedModel):
    status: Literal["running"] = "running"
    execution_id: str
    state: ExecutionState = "running"
    elapsed_seconds: int = 0
    guidance: str = _CODE_MODE_RUNNING_GUIDANCE
    tracked_tasks: list[TrackedTaskView] | None = None
    tracked_tasks_guidance: str | None = None


_CODE_MODE_ERROR_GUIDANCE = (
    "Treat error.code as the stable category, error.message as the summary, and "
    "error.detail as the concrete cause. DO NOT invent fallbacks or assume tools are broken. "
    "Follow ~/wiki/ERROR_CASE.md: stop and report the failure to the user with [FIX PREVIEW], "
    "inspect error detail and live contract, and retry only a corrected call on the canonical path. "
    "A top-level tool or transport failure with no CodeModeFailed payload is outside this "
    "application error contract; do not label it a Code Mode failure without tunnel evidence."
)


class CodeModeErrorDetails(_ClosedModel):
    code: str
    message: str
    detail: str | None = None

    @field_validator("detail")
    @classmethod
    def _bound_detail(cls, value: str | None) -> str | None:
        if value is not None and len(value) > _ERROR_DETAIL_MAX_CHARS:
            return value[: _ERROR_DETAIL_MAX_CHARS - 3] + "..."
        return value


class CodeModeFailed(_ClosedModel):
    status: Literal["failed"] = "failed"
    execution_id: str
    error: CodeModeErrorDetails
    guidance: str = _CODE_MODE_ERROR_GUIDANCE
    tracked_tasks: list[TrackedTaskView] | None = None
    tracked_tasks_guidance: str | None = None


CodeModeOutput = Annotated[
    CodeModeCompleted | CodeModeRunning | CodeModeFailed,
    Field(discriminator="status"),
]

# Backward compatibility aliases
CodeModeTask = CodeModeRunning
CodeModeError = CodeModeFailed
CodeModeOutcome = CodeModeOutput
CodeModeWorkOutcome = CodeModeOutput


class _CodeModePublicOutput(RootModel[CodeModeOutput]):
    pass


class WslExecWorkOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    tracked_tasks: list[TrackedTaskView] | None = None
    tracked_tasks_guidance: str | None = None

    @model_serializer(mode="wrap")
    def _serialize_omit_none(self, handler: Any) -> Any:
        dump = handler(self)
        if isinstance(dump, dict):
            return {
                k: v
                for k, v in dump.items()
                if not (k in {"tracked_tasks", "tracked_tasks_guidance"} and v is None)
            }
        return dump


_CODE_MODE_OUTPUT_ADAPTER = TypeAdapter(CodeModeOutput)
_CODE_MODE_OUTCOME_ADAPTER = _CODE_MODE_OUTPUT_ADAPTER
_CODE_MODE_WORK_OUTCOME_ADAPTER = _CODE_MODE_OUTPUT_ADAPTER


def _code_mode_output(value: dict[str, Any]) -> CodeModeOutput:
    payload = dict(value)
    if "status" not in payload and "kind" in payload:
        kind = payload.pop("kind")
        if kind == "error":
            payload["status"] = "failed"
        elif kind == "task":
            payload["status"] = "running"
        elif kind == "completed":
            payload["status"] = "completed"

    if payload.get("status") == "failed":
        if "error" not in payload:
            err = {
                "code": payload.pop(
                    "error_code", payload.pop("code", "execution_error")
                ),
                "message": payload.pop("message", "Code Mode Execution failed."),
            }
            if "detail" in payload:
                err["detail"] = payload.pop("detail")
            payload["error"] = err
        if "guidance" not in payload:
            payload["guidance"] = _CODE_MODE_ERROR_GUIDANCE

    if (
        payload.get("status") == "completed"
        and "result" not in payload
        and "output" in payload
    ):
        payload["result"] = payload.pop("output")

    if payload.get("status") == "running" and "guidance" not in payload:
        payload["guidance"] = _CODE_MODE_RUNNING_GUIDANCE

    return _CODE_MODE_OUTPUT_ADAPTER.validate_python(payload)


_code_mode_outcome = _code_mode_output


_SESSION_TASKS_STATE_KEY = "published_task_ids"


def _session_state(
    ctx: Context | ServerRequestContext[Any, Any] | None,
) -> dict[str, Any] | None:
    if ctx is None:
        return None
    session = getattr(ctx, "session", None)
    if session is None and hasattr(ctx, "request_context"):
        session = getattr(ctx.request_context, "session", None)
    if session is None:
        return None
    connection = getattr(session, "_connection", None)
    state = getattr(connection, "state", None)
    if isinstance(state, dict):
        return state
    return None


def _session_published_task_ids(
    ctx: Context | ServerRequestContext[Any, Any] | None,
) -> set[str] | None:
    state = _session_state(ctx)
    if state is None:
        return None
    ids = state.get(_SESSION_TASKS_STATE_KEY)
    if not isinstance(ids, set):
        ids = set()
        state[_SESSION_TASKS_STATE_KEY] = ids
    return ids


def _record_session_task(
    ctx: Context | ServerRequestContext[Any, Any] | None, execution_id: str
) -> None:
    task_ids = _session_published_task_ids(ctx)
    if task_ids is not None:
        task_ids.add(execution_id)


def _discard_session_task(
    ctx: Context | ServerRequestContext[Any, Any] | None, execution_id: str
) -> None:
    task_ids = _session_published_task_ids(ctx)
    if task_ids is not None:
        task_ids.discard(execution_id)


async def _tracked_tasks_snapshot(
    ctx: Context | ServerRequestContext[Any, Any] | None = None,
) -> list[TrackedTaskView]:
    rows = await asyncio.to_thread(_task_list, limit=TRACKED_TASKS_LIMIT)
    session_ids = _session_published_task_ids(ctx)
    if session_ids is not None:
        rows = [row for row in rows if str(row.get("execution_id")) in session_ids]
    return [
        TrackedTaskView.model_validate(
            {
                "execution_id": row["execution_id"],
                "label": row["label"],
                "state": row["state"],
                "reason": row.get("reason"),
                "elapsed_seconds": row["elapsed_seconds"],
            }
        )
        for row in rows
    ]


def _code_mode_work_outcome(
    primary: CodeModeOutput, tracked_tasks: list[TrackedTaskView]
) -> CodeModeOutput:
    if not tracked_tasks:
        return primary
    return primary.model_copy(
        update={
            "tracked_tasks": tracked_tasks,
            "tracked_tasks_guidance": _TRACKED_TASKS_GUIDANCE,
        }
    )


def _exception_detail(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc).strip()
    return f"{name}: {text}" if text else name


def _code_mode_error(
    execution_id: str,
    *,
    code: str,
    message: str,
    detail: str | None = None,
) -> CodeModeFailed:
    return CodeModeFailed(
        execution_id=execution_id,
        error=CodeModeErrorDetails(code=code, message=message, detail=detail),
        guidance=_CODE_MODE_ERROR_GUIDANCE,
    )


async def _code_mode_launch_error(
    execution_id: str,
    exc: Exception,
    *,
    response_deadline: float,
) -> CodeModeFailed:
    detail = _exception_detail(exc)
    remaining = response_deadline - time.monotonic()
    if remaining <= 0:
        return _code_mode_error(
            execution_id,
            code="response_deadline_exceeded",
            message=(
                "Code Mode launch failed, and error shaping exceeded the response "
                "deadline."
            ),
            detail=detail,
        )
    try:
        await asyncio.wait_for(
            asyncio.to_thread(executions.store.get, execution_id),
            timeout=remaining,
        )
    except KeyError:
        return _code_mode_error(
            execution_id,
            code="launch_unobserved",
            message=(
                "Code Mode Worker launch failed before an Execution record became "
                "observable."
            ),
            detail=detail,
        )
    except TimeoutError as shaping_exc:
        return _code_mode_error(
            execution_id,
            code="response_deadline_exceeded",
            message=(
                "Code Mode launch failed, and error shaping exceeded the response "
                "deadline."
            ),
            detail=f"{detail}; error_shaping={_exception_detail(shaping_exc)}",
        )
    return _code_mode_error(
        execution_id,
        code="launch_interrupted",
        message="Code Mode Worker could not be launched.",
        detail=detail,
    )


async def code_mode(
    *,
    label: str,
    code: str,
    payload: str | None = None,
    cwd: str | None = None,
    delivery: Literal["auto", "task"] | None = None,
    mode: Literal["auto", "task"] | None = None,
) -> CodeModeOutput:
    """Launch one always-durable Code Mode Execution."""
    chosen_delivery = delivery or mode or "auto"
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
            publish=chosen_delivery == "task",
        )
    )

    if chosen_delivery == "task":
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
            _spawn_followup(
                _publish_during_launch(executions, launch_task, execution_id)
            )
            return await _code_mode_launch_error(
                execution_id,
                exc,
                response_deadline=response_deadline,
            )
        _spawn_followup(_observe_launch(launch_task))
        return CodeModeRunning(
            execution_id=execution_id,
            state=task["state"],
            elapsed_seconds=task.get("elapsed_seconds", 0),
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
                        launch_exception,
                        response_deadline=response_deadline,
                    )
                _spawn_followup(
                    _publish_during_launch(executions, launch_task, execution_id)
                )
                return _code_mode_error(
                    execution_id,
                    code="response_deadline_exceeded",
                    message=(
                        "Code Mode Execution was not accepted before the response "
                        "deadline."
                    ),
                    detail=_exception_detail(exc),
                )
            except Exception as exc:
                return await _code_mode_launch_error(
                    execution_id,
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
                _spawn_followup(
                    _publish_during_launch(executions, launch_task, execution_id)
                )
                return _code_mode_error(
                    execution_id,
                    code="response_deadline_exceeded",
                    message=(
                        "Code Mode Execution was accepted, but Task publication "
                        "did not finish before the response deadline."
                    ),
                )
            except Exception as exc:
                logger.exception(
                    "TASK PUBLICATION FAILED execution_id=%s", execution_id
                )
                _spawn_followup(
                    _publish_during_launch(executions, launch_task, execution_id)
                )
                return _code_mode_error(
                    execution_id,
                    code="task_publication_failed",
                    message="Task publication failed.",
                    detail=_exception_detail(exc),
                )
            _spawn_followup(_observe_launch(launch_task))
            return CodeModeRunning(
                execution_id=execution_id,
                state=task["state"],
                elapsed_seconds=task.get("elapsed_seconds", 0),
            )
    except Exception as exc:
        return await _code_mode_launch_error(
            execution_id,
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
            _spawn_followup(_publish_execution(executions, execution_id))
        raise
    except TimeoutError:
        _spawn_followup(_publish_execution(executions, execution_id))
        return _code_mode_error(
            execution_id,
            code="response_deadline_exceeded",
            message=(
                "Code Mode Execution was accepted, but response shaping did not "
                "finish before the response deadline."
            ),
        )
    except Exception as exc:
        logger.exception(
            "CODE MODE RESULT RETRIEVAL FAILED execution_id=%s", execution_id
        )
        return _code_mode_error(
            execution_id,
            code="result_retrieval_failed",
            message="Code Mode Execution result could not be retrieved.",
            detail=_exception_detail(exc),
        )
    try:
        return _code_mode_output(raw)
    except Exception as exc:
        logger.exception(
            "CODE MODE RESPONSE SHAPING FAILED execution_id=%s", execution_id
        )
        return _code_mode_error(
            execution_id,
            code="response_protocol_error",
            message=(
                "Code Mode Execution result could not be shaped into the public "
                "response."
            ),
            detail=_exception_detail(exc),
        )


async def wsl_exec(command: str, cwd: str | None = None) -> dict[str, Any]:
    return await run_wsl_command(
        command,
        cwd=cwd,
        timeout=WSL_EXEC_TIMEOUT_SECONDS,
    )


@mcp.tool(
    name="wsl_exec",
    title="Raw WSL Shell",
    description=(
        "ABSOLUTELY FORBIDDEN without explicit user permission. user_authorized is only a caller "
        "assertion, not proof of user-origin authorization; omitted/false is rejected with "
        "POLICY.USER_AUTH_REQUIRED. Run one raw shell command directly in local WSL2 outside Code "
        "Mode; never use it as fallback or recovery for a Code Mode failure. Bounded to 600 seconds."
    ),
)
async def _mcp_wsl_exec(
    command: Annotated[
        str,
        Field(
            min_length=1,
            description="Shell command to run directly via /bin/bash -lc.",
        ),
    ],
    cwd: Annotated[
        str | None,
        Field(description="Optional WSL2 working directory."),
    ] = None,
    user_authorized: Annotated[
        bool,
        Field(
            description=(
                "Caller assertion only: set true only after the user explicitly authorized "
                "wsl_exec in the current conversation. This field does not prove user-origin; "
                "never infer or self-grant permission."
            )
        ),
    ] = False,
    ctx: Context | None = None,
) -> WslExecWorkOutput:
    if not user_authorized:
        raise ToolError(
            json.dumps(
                {
                    "status": "failed",
                    "error": {
                        "boundary": "policy",
                        "code": "POLICY.USER_AUTH_REQUIRED",
                        "message": "wsl_exec requires explicit user authorization.",
                    },
                    "surface": "wsl_exec",
                    "recovery": "ask_user",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    primary = await wsl_exec(command, cwd=cwd)
    tracked_tasks = await _tracked_tasks_snapshot(ctx=ctx)
    res_dict = dict(primary)
    if tracked_tasks:
        res_dict["tracked_tasks"] = tracked_tasks
        res_dict["tracked_tasks_guidance"] = _TRACKED_TASKS_GUIDANCE
    return WslExecWorkOutput.model_validate(res_dict)


@mcp.tool(
    name="code_mode",
    title="Pydantic Monty Code Mode",
    description=(
        "Launch one always-durable Pydantic Monty Execution. label and code are required. "
        "delivery='auto' waits up to the bounded inline delivery window and otherwise returns "
        "a running status for the same continuing Execution; delivery='task' publishes that Task "
        "immediately. Returns status ('completed' | 'running' | 'failed') and result. On "
        "status='failed', preserve and report error.code, error.message, and error.detail; "
        "execution_id is the diagnostic correlation handle. Ongoing background work appears "
        "in tracked_tasks as passive HUD without need for polling. "
        "Prefer registered capabilities, inspect CAPABILITIES instead of inventing "
        "arguments. The generated declarations below are the first-call capability contract; "
        "CAPABILITIES is runtime reflection/fallback. Use PAYLOAD for data, and use asyncio.gather "
        "only for independent work.\n\n"
        "Available Monty capabilities (generated from the live callable contract):\n```python\n"
        + _CODE_MODE_CAPABILITY_CATALOG
        + "\n```"
    ),
)
async def _mcp_code_mode(
    label: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            description="Required short Execution label used by Execution and Task awareness.",
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
    delivery: Annotated[
        Literal["auto", "task"],
        Field(
            description=(
                "auto waits for bounded inline delivery; task publishes awareness immediately. "
                "Both choices run the same always-durable Execution."
            )
        ),
    ] = "auto",
    ctx: Context | None = None,
) -> _CodeModePublicOutput:
    primary = await code_mode(
        label=label,
        code=code,
        cwd=cwd,
        payload=payload,
        delivery=delivery,
    )
    if isinstance(primary, CodeModeRunning):
        _record_session_task(ctx, primary.execution_id)

    if isinstance(primary, CodeModeCompleted):
        primary = primary.model_copy(
            update={
                "result": _render_code_mode_completed_result(
                    primary.execution_id, primary.result
                )
            }
        )
    tracked_tasks = await _tracked_tasks_snapshot(ctx=ctx)
    if tracked_tasks:
        primary = primary.model_copy(
            update={
                "tracked_tasks": tracked_tasks,
                "tracked_tasks_guidance": _TRACKED_TASKS_GUIDANCE,
            }
        )
    return _CodeModePublicOutput(root=primary)


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


class TaskCancelOutput(_ClosedModel):
    action: Literal["cancel"] = "cancel"
    task: TaskView


class TaskDismissOutput(_ClosedModel):
    action: Literal["dismiss"] = "dismiss"
    execution_id: str
    state: ExecutionState
    dismissed: bool


TaskOutcome = TaskListOutput | CodeModeOutcome | TaskCancelOutput | TaskDismissOutput


class _TaskPublicOutcome(RootModel[TaskOutcome]):
    pass


def _task_view(value: dict[str, Any]) -> TaskView:
    return TaskView.model_validate(value)


async def task(request: TaskRequest) -> TaskOutcome:
    if isinstance(request, TaskListRequest):
        rows = await asyncio.to_thread(_task_list, limit=_TASK_LIST_LIMIT)
        return TaskListOutput(tasks=[_task_view(row) for row in rows])

    if isinstance(request, TaskGetRequest):
        result = await asyncio.to_thread(_task_get, request.execution_id)
        if bool(result["ready"]):
            return _code_mode_output(result["result"])
        if bool(result.get("unavailable", False)):
            terminal = await asyncio.to_thread(
                _code_mode_execution_result, request.execution_id
            )
            return _code_mode_output(terminal)
        task_view = result["task"]
        return CodeModeRunning(
            execution_id=str(task_view["execution_id"]),
            state=task_view["state"],
            elapsed_seconds=task_view.get("elapsed_seconds", 0),
        )
    if isinstance(request, TaskCancelRequest):
        result = await asyncio.to_thread(_task_cancel, request.execution_id)
        return TaskCancelOutput(task=_task_view(result["task"]))
    result = await asyncio.to_thread(_task_dismiss, request.execution_id)
    return TaskDismissOutput.model_validate({"action": "dismiss", **result})


@mcp.tool(
    name="task",
    title="GPT Dive Task Lifecycle",
    description=(
        "Operate a published Code Mode Task by its single execution_id. list performs explicit "
        "detailed inspection, get is non-destructive status/result pickup, cancel explicitly cancels "
        "running work, and dismiss removes terminal awareness without deleting retention."
    ),
)
async def _mcp_task(
    request: TaskRequest, ctx: Context | None = None
) -> _TaskPublicOutcome:
    outcome = await task(request)
    if (
        isinstance(request, TaskDismissRequest)
        and isinstance(outcome, TaskDismissOutput)
        and outcome.dismissed
    ):
        _discard_session_task(ctx, request.execution_id)

    if isinstance(outcome, CodeModeCompleted):
        outcome = outcome.model_copy(
            update={
                "result": _render_code_mode_completed_result(
                    outcome.execution_id, outcome.result
                )
            }
        )
    return _TaskPublicOutcome(root=outcome)


@mcp.tool(
    title="Bootstrap from Local WSL2 Wiki",
    description=(
        "Call `bootstrap` before `code_mode` in a fresh ChatGPT Web session when using the "
        "structured GPT Dive harness. It loads the compact, model-visible preload map plus "
        "foundational orientation from the trusted local Wiki."
    ),
)
def bootstrap() -> dict[str, Any]:
    """Load compact fresh-session orientation from the trusted local Wiki preload map."""
    return _read_bootstrap_packet()


if __name__ == "__main__":
    mcp.run()
