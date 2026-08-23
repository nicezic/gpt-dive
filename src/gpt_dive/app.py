from __future__ import annotations

import asyncio
import base64
import fnmatch
import functools
import gzip
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp_types import CallToolResult, TextContent
from pydantic import Field
from pydantic_ai_harness import FileSystem, Shell
from pydantic_ai_harness._output import truncate_tail
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS

from .agy_worker import DEFAULT_MODEL as DEFAULT_AGY_MODEL
from .agy_worker import invoke_agy_worker
from .bare import invoke_bare
from .code_runtime import CallableRegistry, MontyCodeRuntime
from .council import emit_sol_response
from .filesystem_policy import harness_denied_patterns
from .job_manager import JobManager, JobNotFoundError
from .m3_evidence import invoke_m3_evidence
from .repo_search import search_repo
from .runtime_diagnostics import request_lifecycle_middleware
from .runtime_env import build_runtime_path
from .subagent_runtime import invoke_subagent
from .task_store import TaskStore
from .tasks_extension import TasksExtension

jobs = JobManager()
task_store = TaskStore()
tasks_extension = TasksExtension(jobs)
code_runtime = MontyCodeRuntime()

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
        "wsl2_async for durable background job "
        "lifecycle operations. Background jobs survive MCP server restarts and completed job "
        "logs are retained for 5 days. When the client negotiates "
        "io.modelcontextprotocol/tasks, wsl2_async start can use the standard MCP Tasks "
        "lifecycle."
    ),
    extensions=[tasks_extension],
)


def _run_command(
    command: str,
    cwd: str | None = None,
    timeout: float = 600.0,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not command.strip():
        raise ValueError("command must not be empty")

    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    run_cwd = str(Path(cwd).expanduser()) if cwd else None
    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    runtime_path = build_runtime_path(guard_bin)
    guarded_command = f"export PATH={shlex.quote(runtime_path)}; {command}"

    try:
        completed = subprocess.run(
            ["/bin/bash", "-lc", guarded_command],
            cwd=run_cwd,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=timeout,
            check=False,
            env=env,
        )

        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

        return {
            "command": command,
            "returncode": 124,
            "stdout": stdout,
            "stderr": (
                f"{stderr}\n[command] timed out after {timeout} seconds"
            ).lstrip(),
        }


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
        chunks.append(
            f"---\n`$ cat {source}`\n\n"
            f"{doc['content'].rstrip()}"
        )
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


def _parse_reminder_config(reminder_text: str) -> tuple[int, list[tuple[str, str | None]]]:
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
        if section is not None and (not isinstance(section, str) or not section.strip()):
            raise ValueError("reminder section must be a non-empty string when provided")
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
    if tool_name == "bootstrap" or not isinstance(result, CallToolResult) or result.is_error:
        return result

    try:
        tasks = await asyncio.to_thread(_task_list, limit=8)
        if not tasks:
            return result
        text = _render_tracked_tasks(tasks)
    except Exception:  # noqa: BLE001 - awareness must never fail the primary tool result
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
        "durable background jobs. Keep timeout only slightly above the expected runtime."
    ),
)
def wsl2_sync(
    command: Annotated[
        str,
        Field(
            description="Shell command to run via /bin/bash -lc."
        ),
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
        Field(
            description="Optional WSL2 working directory."
        ),
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


def _code_mode_home_root() -> Path:
    """Return the user home used only for credential/secret path policy."""
    return Path.home().resolve()


_BROAD_SEARCH_ROOTS = {"/", "/mnt/c"}


def _reject_broad_search_root(path: Path, *, operation: str) -> None:
    resolved = str(path.resolve())
    if resolved in _BROAD_SEARCH_ROOTS:
        raise ValueError(
            f"{operation} refuses broad recursive search rooted at {resolved}; "
            "narrow to a specific subdirectory first"
        )



def _build_code_registry(default_cwd: str | None) -> CallableRegistry:
    registry = CallableRegistry()
    effective_cwd = (
        Path(default_cwd).expanduser().resolve()
        if default_cwd is not None
        else Path.home().resolve()
    )

    home = _code_mode_home_root()
    denied_patterns = harness_denied_patterns(root=Path("/"), home=home)
    filesystem_toolset: Any = FileSystem(
        root_dir="/",
        denied_patterns=denied_patterns,
        protected_patterns=[],
    ).get_toolset()

    def resolve_path(path: str) -> Path:
        expanded = Path(path).expanduser()
        if expanded.is_absolute():
            return expanded.resolve()
        return (effective_cwd / expanded).resolve()

    async def read_file(path: str, *, offset: int = 0, limit: int | None = None) -> str:
        """Read a text file with line numbers. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        return await filesystem_toolset.read_file(
            str(resolve_path(path)), offset=offset, limit=limit
        )

    async def list_directory(path: str = ".") -> str:
        """List a directory. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        return await filesystem_toolset.list_directory(str(resolve_path(path)))

    async def search_files(
        pattern: str, *, path: str = ".", include_glob: str | None = None
    ) -> str:
        """Search file contents by regex. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        resolved = resolve_path(path)
        _reject_broad_search_root(resolved, operation="search_files")
        return await filesystem_toolset.search_files(
            pattern, path=str(resolved), include_glob=include_glob
        )

    async def find_files(pattern: str, *, path: str = ".") -> str:
        """Find files by glob. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        resolved = resolve_path(path)
        _reject_broad_search_root(resolved, operation="find_files")
        return await filesystem_toolset.find_files(pattern, path=str(resolved))

    async def file_info(path: str) -> str:
        """Get file or directory metadata. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        return await filesystem_toolset.file_info(str(resolve_path(path)))

    async def write_file(
        path: str, content: str, *, expected_hash: str | None = None
    ) -> str:
        """Create or overwrite a file with conflict detection. Host writes are allowed anywhere permitted by the OS except credential/secret paths."""
        return await filesystem_toolset.write_file(
            str(resolve_path(path)), content, expected_hash=expected_hash
        )

    async def edit_file(
        path: str,
        old_text: str,
        new_text: str,
        *,
        expected_hash: str | None = None,
    ) -> str:
        """Edit a file by exact replacement with conflict detection. Host writes are allowed anywhere permitted by the OS except credential/secret paths."""
        return await filesystem_toolset.edit_file(
            str(resolve_path(path)), old_text, new_text, expected_hash=expected_hash
        )

    async def create_directory(path: str) -> str:
        """Create a directory and parents. Host writes are allowed anywhere permitted by the OS except credential/secret paths."""
        return await filesystem_toolset.create_directory(str(resolve_path(path)))

    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    shell_denied_env_patterns = (
        *LLM_API_KEY_ENV_PATTERNS,
        "MINIMAX_*",
        "AIAPIFLOW_*",
    )
    shell_env = {
        name: value
        for name, value in os.environ.items()
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in shell_denied_env_patterns)
    }
    shell_env["PATH"] = build_runtime_path(guard_bin, inherited=shell_env.get("PATH"))
    shell_max_output_chars = 50_000
    shell_toolset = Shell(
        cwd=effective_cwd,
        env=shell_env,
        denied_commands=[],
        denied_env_patterns=shell_denied_env_patterns,
        default_timeout=60.0,
        max_output_chars=shell_max_output_chars,
    ).get_toolset()

    async def agy_worker(
        *,
        task: str,
        model: str = DEFAULT_AGY_MODEL,
        timeout: float,
        cwd: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a read-only Antigravity worker through the official agy CLI.

        Defaults to Gemini 3.7 Flash High. Google authentication and entitlement stay
        inside agy. Pass conversation_id to resume that exact AGY conversation. The worker
        runs in read-only plan mode and auto-approves headless tool permission prompts.
        """
        return await invoke_agy_worker(
            task=task,
            model=model,
            timeout=timeout,
            workspace_dir=cwd if cwd is not None else default_cwd,
            conversation_id=conversation_id,
        )

    async def subagent_call(
        *,
        model: str,
        task: str,
        timeout: float,
        output_tokens_limit: int = 4096,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Call a registered subagent with file tools scoped to cwd.

        If ok is false, preserve the full result including error/stderr diagnostics;
        do not project the failure down to only ok/model/output.
        """
        return await invoke_subagent(
            model=model,
            task=task,
            timeout=timeout,
            output_tokens_limit=output_tokens_limit,
            workspace_dir=cwd if cwd is not None else default_cwd,
        )

    async def bare(
        *,
        provider: str,
        model: str,
        prompt: str,
        timeout: float,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Call an independent peer reviewer using a provider and exact model name."""
        return await invoke_bare(
            provider=provider,
            model=model,
            prompt=prompt,
            timeout=timeout,
            peer_review=True,
            workspace_dir=cwd if cwd is not None else default_cwd,
        )

    async def m3_evidence(
        *,
        question: str,
        evidence: str,
        round_number: int = 1,
        max_rounds: int = 3,
        max_queries: int = 3,
        timeout: float,
        output_tokens_limit: int = 2048,
    ) -> dict[str, Any]:
        """Use tool-less MiniMax-M3 to assess evidence within a bounded research-round budget."""
        return await invoke_m3_evidence(
            question=question,
            evidence=evidence,
            round_number=round_number,
            max_rounds=max_rounds,
            max_queries=max_queries,
            timeout=timeout,
            output_tokens_limit=output_tokens_limit,
        )

    async def repo_search(
        *,
        query: str,
        path: str | None = None,
        max_results: int = 8,
        max_tokens: int = 6000,
        allow_tests: bool = False,
    ) -> dict[str, Any]:
        """Search local code/docs with Probe using BM25 ranking and AST-aware blocks.

        Prefer this for exploring unfamiliar repositories and locating relevant code by concept.
        Relative path values resolve from the Code Mode cwd; absolute/~/ paths remain explicit.
        Use precise technical keywords when possible.
        """
        search_path = Path(path).expanduser() if path is not None else effective_cwd
        if not search_path.is_absolute():
            search_path = effective_cwd / search_path
        search_path = search_path.resolve()
        _reject_broad_search_root(search_path, operation="repo_search")
        return await search_repo(
            query=query,
            path=str(search_path),
            max_results=max_results,
            max_tokens=max_tokens,
            allow_tests=allow_tests,
        )

    async def council_emit(
        *,
        council_dir: str,
        message: str,
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        """Persist one Web SOL Council response as an append-only Git event."""
        return await asyncio.to_thread(
            emit_sol_response, council_dir, message, expected_head
        )

    async def gz64(payload: str) -> dict[str, Any]:
        """Last-resort command transport when normal execution is blocked by the OpenAI tunnel/filtering path."""
        compressed = base64.b64decode(payload, validate=True)
        command = gzip.decompress(compressed).decode("utf-8")
        return await asyncio.to_thread(_run_command, command, default_cwd, 600.0)

    async def task_list() -> dict[str, Any]:
        """Return complete structured outstanding Task records after local refresh."""
        return {"tasks": await asyncio.to_thread(_task_list)}

    async def task_collect(task_id: str) -> dict[str, Any]:
        """Collect retained Task result/evidence without acknowledging it."""
        return await asyncio.to_thread(_task_collect, task_id)

    async def task_cancel(task_id: str) -> dict[str, Any]:
        """Forward cancellation to a working Task's backing execution."""
        return await asyncio.to_thread(_task_cancel, task_id)

    async def task_ack(task_id: str) -> dict[str, Any]:
        """Remove terminal or lost Task awareness after handling."""
        return await asyncio.to_thread(_task_ack, task_id)

    registry.register("read_file", read_file)
    registry.register("write_file", write_file)
    registry.register("edit_file", edit_file)
    registry.register("list_directory", list_directory)
    registry.register("search_files", search_files)
    registry.register("find_files", find_files)
    registry.register("create_directory", create_directory)
    registry.register("file_info", file_info)

    def bounded_shell_method(name: str):
        method = getattr(shell_toolset, name)

        @functools.wraps(method)
        async def invoke(*args: Any, **kwargs: Any) -> str:
            return truncate_tail(await method(*args, **kwargs), shell_max_output_chars)

        return invoke

    for name in ("run_command", "start_command", "check_command", "stop_command"):
        registry.register(name, bounded_shell_method(name))

    registry.add_async_cleanup(shell_toolset.__aexit__)
    registry.register("agy_worker", agy_worker)
    registry.register("subagent_call", subagent_call)
    registry.register("bare", bare)
    registry.register("m3_evidence", m3_evidence)
    registry.register("repo_search", repo_search)
    registry.register("council_emit", council_emit)
    registry.register("gz64", gz64)
    registry.register("task_list", task_list)
    registry.register("task_collect", task_collect)
    registry.register("task_cancel", task_cancel)
    registry.register("task_ack", task_ack)
    return registry


CODE_MODE_WORKER_PROTOCOL = 2


def _code_mode_request_dir() -> Path:
    path = jobs.root.parent / "code-mode-inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _code_mode_request_ref(job_id: str) -> Path:
    return jobs.root / job_id / "code_mode_payload.ref"


def _cleanup_code_mode_request(job_id: str) -> None:
    ref = _code_mode_request_ref(job_id)
    if not ref.is_file():
        return
    try:
        raw = ref.read_text().strip()
        request_path = Path(raw).resolve()
        request_path.relative_to(_code_mode_request_dir().resolve())
        request_path.unlink(missing_ok=True)
    except OSError, ValueError:
        pass
    finally:
        ref.unlink(missing_ok=True)


def _refresh_task(task: dict[str, Any]) -> dict[str, Any]:
    if task["state"] == "lost":
        return task

    task_id = str(task["task_id"])
    execution_id = str(task["execution_id"])
    try:
        execution = jobs.status(execution_id)
    except JobNotFoundError:
        return task_store.update_state(task_id, "lost")

    execution_state = str(execution.get("status") or "")
    if execution_state == "running":
        return task

    try:
        normalized = _background_code_mode_result(execution_id)
    except (JobNotFoundError, FileNotFoundError):
        return task_store.update_state(task_id, "lost")

    error = normalized.get("error")
    if isinstance(error, dict):
        target = "cancelled" if error.get("code") == "background_cancelled" else "failed"
    else:
        target = "completed"
    return task_store.update_state(task_id, target)


def _task_status_label(task: dict[str, Any]) -> str | None:
    if task["state"] != "working":
        return None

    static_status = str(task.get("status") or "").strip()
    status_cmd = str(task.get("status_cmd") or "").strip()
    if status_cmd:
        try:
            probe = _run_command(status_cmd, timeout=1.0)
        except OSError:
            probe = {"returncode": 1, "stdout": ""}
        if probe.get("returncode") == 0:
            stdout = " ".join(str(probe.get("stdout") or "").splitlines()).strip()
            if stdout:
                return stdout[:256]
    return static_status[:256] if static_status else None


def _task_elapsed_seconds(task: dict[str, Any]) -> int:
    created = datetime.fromisoformat(str(task["created_at"]))
    if task["state"] == "working":
        end = datetime.now(UTC)
    else:
        end = datetime.fromisoformat(str(task["updated_at"]))
    return max(0, int((end - created).total_seconds()))


def _decorate_task(task: dict[str, Any]) -> dict[str, Any]:
    decorated = dict(task)
    decorated["status_label"] = _task_status_label(task)
    decorated["elapsed_seconds"] = _task_elapsed_seconds(task)
    return decorated


def _task_list(*, limit: int | None = None) -> list[dict[str, Any]]:
    tasks = task_store.list_tasks()
    if limit is not None:
        tasks = tasks[:limit]
    return [_decorate_task(_refresh_task(task)) for task in tasks]


_TASK_STATE_MARKERS = {
    "working": "🧵",
    "completed": "✅",
    "failed": "❌",
    "cancelled": "⛔",
    "lost": "⚠️",
}


def _format_task_elapsed(seconds: int) -> str:
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}:{secs:02d}"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _render_tracked_tasks(tasks: list[dict[str, Any]], *, limit: int = 8) -> str:
    lines = ["TrackedTasks"]
    for task in tasks[:limit]:
        state = str(task["state"])
        marker = _TASK_STATE_MARKERS.get(state, "•")
        parts = [
            str(task["label"]),
            f"{marker} {state}",
            _format_task_elapsed(int(task["elapsed_seconds"])),
        ]
        status_label = str(task.get("status_label") or "").strip()
        if status_label:
            parts.append(status_label)
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def _task_collect(task_id: str) -> dict[str, Any]:
    task = _refresh_task(task_store.get(task_id))
    if task["state"] == "working":
        return {"task": task, "ready": False}
    if task["state"] == "lost":
        return {"task": task, "ready": False, "unavailable": True}

    execution_id = str(task["execution_id"])
    try:
        result = _background_code_mode_result(execution_id)
    except (JobNotFoundError, FileNotFoundError):
        task = task_store.update_state(str(task["task_id"]), "lost")
        return {"task": task, "ready": False, "unavailable": True}
    return {"task": task, "ready": True, "result": result}


def _task_cancel(task_id: str) -> dict[str, Any]:
    task = _refresh_task(task_store.get(task_id))
    if task["state"] != "working":
        return {"task": task}

    execution_id = str(task["execution_id"])
    try:
        jobs.cancel(execution_id)
    except JobNotFoundError:
        task = task_store.update_state(str(task["task_id"]), "lost")
        return {"task": task}
    _cleanup_code_mode_request(execution_id)
    return {"task": _refresh_task(task_store.get(task_id))}


def _task_ack(task_id: str) -> dict[str, Any]:
    task = _refresh_task(task_store.get(task_id))
    if task["state"] == "working":
        raise ValueError("task_ack requires a terminal or lost Task")
    task_store.delete(task_id)
    return {"task_id": str(task["task_id"]), "state": str(task["state"]), "acked": True}


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
        started = jobs.start(command, cwd, 600.0)
        job_id = str(started["job_id"])
        try:
            _code_mode_request_ref(job_id).write_text(str(request_path) + "\n")
        except OSError:
            jobs.cancel(job_id)
            request_path.unlink(missing_ok=True)
            raise
        if label is None:
            return started
        try:
            task = task_store.create(
                execution_id=job_id,
                label=label,
                status_cmd=status_cmd,
                status=status,
            )
        except Exception:
            _cleanup_code_mode_request(job_id)
            jobs.cancel(job_id)
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


def _background_error(
    raw: dict[str, Any],
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "job_id": raw.get("job_id"),
        "status": raw.get("status"),
        "exit_code": raw.get("exit_code"),
        "error": {"code": code, "message": message},
    }
    stderr = str(raw.get("stderr") or "").strip()
    if stderr:
        result["worker_stderr"] = stderr[-2000:]
    return result


def _background_code_mode_result(job_id: str) -> dict[str, Any]:
    raw = jobs.result(job_id)
    if not raw.get("ready"):
        raise RuntimeError(f"code_mode background job {job_id!r} is still running")
    _cleanup_code_mode_request(job_id)
    if raw.get("status") == "cancelled":
        return _background_error(
            raw,
            code="background_cancelled",
            message="Background Code Mode job was cancelled.",
        )

    stdout = str(raw.get("stdout") or "").strip()
    if not stdout:
        return _background_error(
            raw,
            code="worker_protocol_error",
            message="Background Code Mode worker produced no result envelope.",
        )
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return _background_error(
            raw,
            code="worker_protocol_error",
            message="Background Code Mode worker produced invalid JSON.",
        )
    if not isinstance(envelope, dict) or envelope.get("v") != CODE_MODE_WORKER_PROTOCOL:
        return _background_error(
            raw,
            code="worker_protocol_error",
            message="Background Code Mode worker used an unsupported result envelope.",
        )

    exit_code = raw.get("exit_code")
    if envelope.get("ok") is True and exit_code == 0:
        worker_result = envelope.get("result")
        if not isinstance(worker_result, dict):
            return _background_error(
                raw,
                code="worker_protocol_error",
                message="Background Code Mode success envelope has no object result.",
            )
        return {"job_id": job_id, **worker_result}

    error = envelope.get("error")
    if isinstance(error, dict):
        error_code = str(error.get("code") or "background_execution_error")
        error_message = str(
            error.get("message") or "Background Code Mode execution failed."
        )
    else:
        error_code = "worker_protocol_error"
        error_message = (
            "Background Code Mode worker exited without a valid error envelope."
        )
    if envelope.get("ok") is True and exit_code != 0:
        error_code = "worker_protocol_error"
        error_message = "Worker reported success but exited with a non-zero status."
    return _background_error(raw, code=error_code, message=error_message)


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
        Field(description="Detach this Code Mode program as a durable background job."),
    ] = False,
    label: Annotated[
        str | None,
        Field(description="Optional non-empty Task label for a Task-aware background launch (max 80 characters).", max_length=80),
    ] = None,
    status_cmd: Annotated[
        str | None,
        Field(description="Optional bounded local command whose stdout decorates a working Task."),
    ] = None,
    status: Annotated[
        str | None,
        Field(description="Optional static Task display status used when status_cmd has no usable output."),
    ] = None,
    action: Annotated[
        Literal["status", "result", "cancel"] | None,
        Field(
            description="Lifecycle action for a background Code Mode job: status, result, or cancel."
        ),
    ] = None,
    job_id: Annotated[
        str | None,
        Field(description="Background Code Mode job ID for lifecycle actions."),
    ] = None,
) -> dict[str, Any]:
    """Execute or manage one stateless Monty program."""
    normalized_action = action.strip().lower() if action is not None else None
    has_code = code is not None and bool(code.strip())
    clean_label = label.strip() if label is not None else None
    clean_status_cmd = status_cmd.strip() if status_cmd is not None and status_cmd.strip() else None
    clean_status = status.strip() if status is not None and status.strip() else None
    if label is not None and not clean_label:
        raise ValueError("label must not be empty")
    if clean_label is not None and len(clean_label) > 80:
        raise ValueError("label must be 80 characters or fewer")
    if (clean_status_cmd is not None or clean_status is not None) and clean_label is None:
        raise ValueError("status fields require a labeled background Task")

    if normalized_action is None:
        if not has_code:
            raise ValueError(
                "code_mode requires code unless action + job_id are provided"
            )
        if job_id is not None:
            raise ValueError("job_id is only valid with a lifecycle action")
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
            str(code), _build_code_registry(cwd), cwd=cwd, payload=payload
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
    if job_id is None or not job_id.strip():
        raise ValueError(f"code_mode action={normalized_action!r} requires job_id")
    if normalized_action == "status":
        state = await asyncio.to_thread(jobs.status, job_id)
        if state.get("status") != "running":
            await asyncio.to_thread(_cleanup_code_mode_request, job_id)
        return state
    if normalized_action == "result":
        return await asyncio.to_thread(_background_code_mode_result, job_id)
    if normalized_action == "cancel":
        state = await asyncio.to_thread(jobs.cancel, job_id)
        await asyncio.to_thread(_cleanup_code_mode_request, job_id)
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
        "- Use background=True only for detached Code Mode jobs."
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
        Field(description="Detach this Code Mode program as a durable background job; the actual mode is exposed inside Monty as BACKGROUND."),
    ] = False,
    label: Annotated[
        str | None,
        Field(description="Optional non-empty Task label for a Task-aware background launch (max 80 characters).", max_length=80),
    ] = None,
    status_cmd: Annotated[
        str | None,
        Field(description="Optional bounded local command whose stdout decorates a working Task."),
    ] = None,
    status: Annotated[
        str | None,
        Field(description="Optional static Task display status used when status_cmd has no usable output."),
    ] = None,
    action: Annotated[
        Literal["status", "result", "cancel"] | None,
        Field(description="Lifecycle action for a background Code Mode job: status, result, or cancel."),
    ] = None,
    job_id: Annotated[
        str | None,
        Field(description="Background Code Mode job ID for lifecycle actions."),
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
        job_id=job_id,
    )


def _required_job_id(action: str, job_id: str | None) -> str:
    if job_id is None or not job_id.strip():
        raise ValueError(f"wsl2_async action={action!r} requires job_id")
    return job_id


@mcp.tool(
    title="Asynchronous WSL2 Jobs",
    description=(
        "Operate durable asynchronous WSL2 jobs through one stable action-based interface. "
        "Use action='capabilities' to discover the actions supported by the current backend. "
        "Long-running jobs survive MCP server restarts; completed logs are retained for 5 days."
    ),
)
def wsl2_async(
    action: Annotated[
        str,
        Field(
            description="Async-job action; use 'capabilities' to list supported actions."
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
                "Required exact harness declaration for direct WSL job start: "
                f"{_DIRECT_WSL_PERMISSION}"
            )
        ),
    ] = None,
    job_id: Annotated[
        str | None,
        Field(
            description="Job ID for status/result/cancel."
        ),
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
    """Dispatch a durable WSL2 job lifecycle action."""
    normalized = action.strip().lower()
    if normalized == "capabilities":
        return {
            "actions": {
                "start": {"requires": ["command", "permission"], "optional": ["cwd", "timeout"]},
                "status": {"requires": ["job_id"]},
                "result": {"requires": ["job_id"]},
                "cancel": {"requires": ["job_id"]},
            }
        }
    if normalized == "start":
        if command is None or not command.strip():
            raise ValueError("wsl2_async action='start' requires command")
        if permission != _DIRECT_WSL_PERMISSION:
            raise ValueError(
                "wsl2_async permission mismatch; use the exact harness declaration from the live schema"
            )
        return jobs.start(command, cwd, timeout)
    if normalized == "status":
        return jobs.status(_required_job_id(normalized, job_id))
    if normalized == "result":
        return jobs.result(_required_job_id(normalized, job_id))
    if normalized == "cancel":
        return jobs.cancel(_required_job_id(normalized, job_id))
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
