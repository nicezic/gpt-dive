from __future__ import annotations

import asyncio
import base64
import functools
import gzip
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field
from pydantic_ai_harness import FileSystem, Shell
from pydantic_ai_harness._output import truncate_tail
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS

from .agy_worker import DEFAULT_MODEL as DEFAULT_AGY_MODEL
from .agy_worker import invoke_agy_worker
from .bare import invoke_bare
from .code_runtime import CallableRegistry, MontyCodeRuntime
from .council import emit_sol_response
from .job_manager import JobManager
from .repo_search import search_repo
from .runtime_env import build_runtime_path
from .subagent_runtime import invoke_subagent
from .tasks_extension import TasksExtension

jobs = JobManager()
tasks_extension = TasksExtension(jobs)
code_runtime = MontyCodeRuntime()

mcp = MCPServer(
    name="gpt-dive",
    title="GPT Dive",
    description=(
        "Direct ChatGPT Web -> WSL2 runtime. Call bootstrap first. Prefer code_mode for "
        "multi-step, parallel, preprocessing, or quote-heavy work; wsl2_sync for simple "
        "one-shot shell; wsl2_async for durable jobs. On error/mistake, report immediately "
        "and use /grill-me."
    ),
    instructions=(
        "GPT Dive operates the user's local WSL2 environment. Treat its filesystem, "
        "processes, network state, and command results as belonging to the user's local "
        "machine, not as a separate hosted or ChatGPT sandbox. In a fresh ChatGPT Web "
        "session, call bootstrap first. After bootstrap, prefer code_mode as the primary execution "
        "root for normal work: it composes capabilities, runs independent work in parallel, "
        "preprocesses large results locally, and accepts opaque input separately from Monty source. "
        "On any tool error or assistant mistake, report it to the user immediately and use /grill-me "
        "to examine cause and response. Use wsl2_sync only for short direct commands "
        "that need an immediate result, and "
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
                f"{stderr}\n[wsl2_sync] timed out after {timeout} seconds"
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
    """Extract numbered Markdown paths from the preload map's Preload files section."""
    match = re.search(
        r"^## Preload files\s*$\n(?P<body>.*?)(?=^## \S|\Z)",
        preload_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise ValueError("bootstrap preload map has no '## Preload files' section")

    paths = re.findall(r"^\s*\d+\.\s+`([^`]+)`\s*$", match.group("body"), re.MULTILINE)
    if not paths:
        raise ValueError(
            "bootstrap preload map Preload files section contains no document paths"
        )
    return paths


def _read_bootstrap_packet() -> dict[str, Any]:
    """Assemble compact fresh-session orientation from the trusted Wiki preload map."""
    wiki = _wiki_path()
    preload = wiki / "bootstrap" / "preload.md"
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

    chunks = [
        f"# BOOTSTRAP PACKET\nWiki: {wiki}\nPreload: {preload}\n",
        (
            "\n\n===== BEGIN bootstrap/preload.md =====\n"
            f"{preload_text.rstrip()}\n"
            "===== END bootstrap/preload.md ====="
        ),
    ]
    for doc in documents:
        chunks.append(
            f"\n\n===== BEGIN {doc['path']} =====\n"
            f"{doc['content'].rstrip()}\n"
            f"===== END {doc['path']} ====="
        )

    live_capabilities = _build_code_registry(None).describe()
    capability_sections = []
    for name, metadata in live_capabilities.items():
        description = metadata["description"].strip() or "(no description)"
        capability_sections.append(f"{name}{metadata['signature']}\n{description}")
    chunks.append(
        "\n\n===== BEGIN LIVE CODE MODE CAPABILITIES =====\n"
        "Fresh-session live inner `--help`: use these signatures and descriptions as the "
        "current Code Mode call contract.\n\n"
        + "\n\n".join(capability_sections)
        + "\n===== END LIVE CODE MODE CAPABILITIES ====="
    )

    return {
        "wiki_path": str(wiki),
        "preload_path": str(preload),
        "preloaded_files": [doc["path"] for doc in documents],
        "warnings": warnings,
        "stdout": "".join(chunks) + "\n",
    }


@mcp.tool(
    title="Synchronous WSL2",
    description=(
        "Execute a short shell command synchronously inside the user's local WSL2 and return "
        "its result immediately. Use code_mode for programmable multi-step work and wsl2_async "
        "for durable background jobs. Keep timeout only slightly above the expected runtime."
    ),
)
def wsl2_sync(
    command: Annotated[
        str,
        Field(
            description="Shell command to run via /bin/bash -lc."
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
    """Run a short shell command synchronously in the user's local WSL2 environment."""
    return _run_command(command, cwd, timeout)


_CODE_MODE_TRUSTED_HOME_READ_DIRS = (
    "ref",
    "wiki",
    "gpt-dive",
    "gbrain",
    "monsoon",
    "labs",
)
_CODE_MODE_TRUSTED_SYSTEM_READ_ROOTS = (Path("/tmp"),)
_CODE_MODE_TRUSTED_SYSTEM_WRITE_ROOTS = (Path("/tmp"),)


def _code_mode_trusted_read_roots() -> tuple[Path, ...]:
    """Return existing trusted trees that Code Mode may read outside its cwd."""
    home = Path.home().resolve()
    candidates = (
        *(home / name for name in _CODE_MODE_TRUSTED_HOME_READ_DIRS),
        *_CODE_MODE_TRUSTED_SYSTEM_READ_ROOTS,
    )
    return tuple(root.resolve() for root in candidates if root.is_dir())


def _code_mode_trusted_write_roots() -> tuple[Path, ...]:
    """Return existing trusted trees that Code Mode may write outside its cwd."""
    return tuple(
        root.resolve()
        for root in _CODE_MODE_TRUSTED_SYSTEM_WRITE_ROOTS
        if root.is_dir()
    )


def _build_code_registry(default_cwd: str | None) -> CallableRegistry:
    registry = CallableRegistry()
    workspace = (
        Path(default_cwd).expanduser().resolve()
        if default_cwd is not None
        else Path.home().resolve()
    )

    filesystem_toolset = FileSystem(root_dir=workspace).get_toolset()
    trusted_read_toolsets = [
        (root, FileSystem(root_dir=root).get_toolset())
        for root in _code_mode_trusted_read_roots()
        if root != workspace
    ]
    trusted_write_toolsets = [
        (root, FileSystem(root_dir=root).get_toolset())
        for root in _code_mode_trusted_write_roots()
        if root != workspace
    ]

    def select_read_toolset(path: str) -> tuple[Any, str]:
        expanded = Path(path).expanduser()
        if not expanded.is_absolute():
            return filesystem_toolset, path

        lexical = Path(os.path.abspath(str(expanded)))
        candidates = [(workspace, filesystem_toolset), *trusted_read_toolsets]
        candidates.sort(key=lambda item: len(item[0].parts), reverse=True)
        for root, toolset in candidates:
            try:
                relative = lexical.relative_to(root)
            except ValueError:
                continue
            return toolset, str(relative)

        allowed = ", ".join(str(root) for root, _ in candidates)
        raise PermissionError(
            f"Path {path!r} is outside the Code Mode workspace and trusted read roots: {allowed}"
        )

    def select_write_toolset(path: str) -> tuple[Any, str]:
        expanded = Path(path).expanduser()
        if not expanded.is_absolute():
            return filesystem_toolset, path

        lexical = Path(os.path.abspath(str(expanded)))
        candidates = [(workspace, filesystem_toolset), *trusted_write_toolsets]
        candidates.sort(key=lambda item: len(item[0].parts), reverse=True)
        for root, toolset in candidates:
            try:
                relative = lexical.relative_to(root)
            except ValueError:
                continue
            return toolset, str(relative)

        allowed = ", ".join(str(root) for root, _ in candidates)
        raise PermissionError(
            f"Path {path!r} is outside the Code Mode workspace and trusted write roots: {allowed}"
        )

    async def read_file(path: str, *, offset: int = 0, limit: int | None = None) -> str:
        """Read a text file with line numbers. Relative paths use cwd; explicit absolute/~/ paths are allowed only under trusted read roots."""
        toolset, relative = select_read_toolset(path)
        return await toolset.read_file(relative, offset=offset, limit=limit)

    async def list_directory(path: str = ".") -> str:
        """List the contents of a directory. Relative paths use cwd; explicit absolute/~/ paths are allowed only under trusted read roots."""
        toolset, relative = select_read_toolset(path)
        return await toolset.list_directory(relative)

    async def search_files(
        pattern: str, *, path: str = ".", include_glob: str | None = None
    ) -> str:
        """Search file contents using the regular expression passed as `pattern`. Relative paths use cwd; explicit absolute/~/ paths are allowed only under trusted read roots."""
        toolset, relative = select_read_toolset(path)
        return await toolset.search_files(
            pattern, path=relative, include_glob=include_glob
        )

    async def find_files(pattern: str, *, path: str = ".") -> str:
        """Find files by glob pattern (name matching, not content search). Relative paths use cwd; explicit absolute/~/ paths are allowed only under trusted read roots."""
        toolset, relative = select_read_toolset(path)
        return await toolset.find_files(pattern, path=relative)

    async def file_info(path: str) -> str:
        """Get metadata about a file or directory. Relative paths use cwd; explicit absolute/~/ paths are allowed only under trusted read roots."""
        toolset, relative = select_read_toolset(path)
        return await toolset.file_info(relative)

    async def write_file(
        path: str, content: str, *, expected_hash: str | None = None
    ) -> str:
        """Create or overwrite a file with conflict detection. Relative paths use cwd; explicit absolute paths are allowed only under trusted write roots."""
        toolset, relative = select_write_toolset(path)
        return await toolset.write_file(relative, content, expected_hash=expected_hash)

    async def edit_file(
        path: str,
        old_text: str,
        new_text: str,
        *,
        expected_hash: str | None = None,
    ) -> str:
        """Edit a file by exact string replacement with conflict detection. Relative paths use cwd; explicit absolute paths are allowed only under trusted write roots."""
        toolset, relative = select_write_toolset(path)
        return await toolset.edit_file(
            relative, old_text, new_text, expected_hash=expected_hash
        )

    async def create_directory(path: str) -> str:
        """Create a directory and any missing parents. Relative paths use cwd; explicit absolute paths are allowed only under trusted write roots."""
        toolset, relative = select_write_toolset(path)
        return await toolset.create_directory(relative)

    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    shell_env = os.environ.copy()
    shell_env["PATH"] = build_runtime_path(guard_bin, inherited=shell_env.get("PATH"))
    shell_max_output_chars = 50_000
    shell_toolset = Shell(
        cwd=workspace,
        env=shell_env,
        denied_env_patterns=[
            *LLM_API_KEY_ENV_PATTERNS,
            "MINIMAX_*",
            "AIAPIFLOW_*",
        ],
        default_timeout=60.0,
        max_output_chars=shell_max_output_chars,
    ).get_toolset()

    async def local_exec(
        *,
        command: str,
        cwd: str | None = None,
        timeout: float = 600.0,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """Run a guarded short local shell command and wait for its result.

        Returns a dict; read r["stdout"], r["stderr"], and r["returncode"].
        Pass payload data through stdin instead of embedding it in the shell command.
        """
        return await asyncio.to_thread(
            _run_command,
            command,
            cwd if cwd is not None else default_cwd,
            timeout,
            stdin,
        )

    async def agy_worker(
        *,
        task: str,
        model: str = DEFAULT_AGY_MODEL,
        timeout: float = 120.0,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Run a read-only Antigravity worker through the official agy CLI.

        Defaults to Gemini 3.7 Flash High. Google authentication and entitlement stay
        inside agy. The worker runs in plan mode and does not auto-approve permissions.
        """
        return await invoke_agy_worker(
            task=task,
            model=model,
            timeout=timeout,
            workspace_dir=cwd if cwd is not None else default_cwd,
        )

    async def subagent_call(
        *,
        model: str,
        task: str,
        timeout: float = 120.0,
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
        model: str,
        prompt: str,
        timeout: float = 120.0,
        output_tokens_limit: int = 4096,
    ) -> dict[str, Any]:
        """Call a model with no tools, filesystem, shell, workspace, or extra instructions."""
        return await invoke_bare(
            model=model,
            prompt=prompt,
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
        search_path = Path(path).expanduser() if path is not None else workspace
        if not search_path.is_absolute():
            search_path = workspace / search_path
        return await search_repo(
            query=query,
            path=str(search_path.resolve()),
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
        """Decode Base64+gzip UTF-8 command text and execute it locally. Slow path: do not use for normal commands; use only when quote/payload transport or filtering issues make plain local_exec unsuitable."""
        compressed = base64.b64decode(payload, validate=True)
        command = gzip.decompress(compressed).decode("utf-8")
        return await asyncio.to_thread(_run_command, command, default_cwd, 600.0)

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
    registry.register("local_exec", local_exec)
    registry.register("agy_worker", agy_worker)
    registry.register("subagent_call", subagent_call)
    registry.register("bare", bare)
    registry.register("repo_search", repo_search)
    registry.register("council_emit", council_emit)
    registry.register("gz64", gz64)
    return registry


CODE_MODE_WORKER_PROTOCOL = 1


def _code_mode_payload_dir() -> Path:
    path = jobs.root.parent / "code-mode-inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _code_mode_payload_ref(job_id: str) -> Path:
    return jobs.root / job_id / "code_mode_payload.ref"


def _cleanup_code_mode_payload(job_id: str) -> None:
    ref = _code_mode_payload_ref(job_id)
    if not ref.is_file():
        return
    try:
        raw = ref.read_text().strip()
        payload = Path(raw).resolve()
        payload.relative_to(_code_mode_payload_dir().resolve())
        payload.unlink(missing_ok=True)
    except OSError, ValueError:
        pass
    finally:
        ref.unlink(missing_ok=True)


def _start_background_code_mode(
    code: str,
    cwd: str | None,
    input: str | None,
) -> dict[str, Any]:
    payload = {
        "v": CODE_MODE_WORKER_PROTOCOL,
        "code": code,
        "cwd": cwd,
        "input": input,
    }
    payload_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="code-mode-",
            dir=_code_mode_payload_dir(),
            delete=False,
        ) as fh:
            json.dump(payload, fh, ensure_ascii=False, allow_nan=False)
            fh.write("\n")
            payload_path = Path(fh.name)

        payload_arg = shlex.quote(str(payload_path))
        command = (
            f"{shlex.quote(sys.executable)} -m gpt_dive.code_mode_worker {payload_arg}"
        )
        started = jobs.start(command, cwd, 600.0)
        job_id = str(started["job_id"])
        try:
            _code_mode_payload_ref(job_id).write_text(str(payload_path) + "\n")
        except OSError:
            jobs.cancel(job_id)
            payload_path.unlink(missing_ok=True)
            raise
        return started
    except Exception:
        if payload_path is not None:
            payload_path.unlink(missing_ok=True)
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
    _cleanup_code_mode_payload(job_id)
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
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return _background_error(
                raw,
                code="worker_protocol_error",
                message="Background Code Mode success envelope has no object payload.",
            )
        return {"job_id": job_id, **payload}

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


@mcp.tool(
    title="Pydantic Monty Code Mode",
    description=(
        "Primary programmable execution root for GPT Dive, backed by Pydantic Monty.\n"
        "- CAPABILITIES provides the live inner capability signatures + descriptions.\n"
        "- Call registered capabilities directly with await name(...).\n"
        "- asyncio is pre-imported; use await asyncio.gather(...) for independent work.\n"
        "- Prefer Harness FileSystem/Shell capabilities for normal filesystem and command work.\n"
        "- Use INPUT for complex payloads and CWD as the capability workspace.\n"
        "- Use background=True only for detached Code Mode jobs."
    ),
)
async def code_mode(
    code: Annotated[
        str | None,
        Field(
            description=(
                "Monty Python executable logic. Keep code simple; do not embed complex payload "
                "strings here. Use the input parameter and read it as INPUT for multiline text, code, shell "
                "snippets, JSON, Markdown, or payloads containing quotes/backticks/$(). Process large "
                "results inside the sandbox and make the final expression a compact result. CWD is a "
                "path string, not process chdir; prefer registered FileSystem capabilities for workspace file access instead of assuming CPython path helpers exist inside Monty. Capability "
                "results are dicts, e.g. r['stdout']. Ultra-simple safe example: set input to "
                'a quoted/multiline payload, then code=\'r = await local_exec(command="cat", '
                'stdin=INPUT); r["stdout"]\'.'
            )
        ),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Optional default WSL2 working directory exposed to code as CWD and inherited "
                "by registered capabilities when they accept cwd. Does not chdir Monty itself; "
                "prefer registered FileSystem/Shell capabilities for workspace operations and pass "
                "cwd=CWD to capabilities such as local_exec when needed."
            )
        ),
    ] = None,
    input: Annotated[
        str | None,
        Field(
            description=(
                "Optional opaque payload/data exposed to Monty code as INPUT. Prefer input for "
                "multiline or quoted payloads, including code, shell snippets, JSON, Markdown, "
                "quotes/backticks/$(), instead of embedding them in code. Keep code as executable "
                "logic and INPUT as data to avoid parser/escaping failures."
            )
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(description="Detach this Code Mode program as a durable background job."),
    ] = False,
    action: Annotated[
        str | None,
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

    if normalized_action is None:
        if not has_code:
            raise ValueError(
                "code_mode requires code unless action + job_id are provided"
            )
        if job_id is not None:
            raise ValueError("job_id is only valid with a lifecycle action")
        if background:
            return await asyncio.to_thread(
                _start_background_code_mode, str(code), cwd, input
            )
        return await code_runtime.run(
            str(code), _build_code_registry(cwd), cwd=cwd, input=input
        )

    if has_code:
        raise ValueError("code and lifecycle action are mutually exclusive")
    if background:
        raise ValueError("background is only valid when launching code")
    if cwd is not None:
        raise ValueError("cwd is only valid when launching code")
    if input is not None:
        raise ValueError("input is only valid when launching code")
    if job_id is None or not job_id.strip():
        raise ValueError(f"code_mode action={normalized_action!r} requires job_id")
    if normalized_action == "status":
        state = await asyncio.to_thread(jobs.status, job_id)
        if state.get("status") != "running":
            await asyncio.to_thread(_cleanup_code_mode_payload, job_id)
        return state
    if normalized_action == "result":
        return await asyncio.to_thread(_background_code_mode_result, job_id)
    if normalized_action == "cancel":
        state = await asyncio.to_thread(jobs.cancel, job_id)
        await asyncio.to_thread(_cleanup_code_mode_payload, job_id)
        return state
    raise ValueError("unsupported code_mode action; choose status, result, or cancel")


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
                "start": {"requires": ["command"], "optional": ["cwd", "timeout"]},
                "status": {"requires": ["job_id"]},
                "result": {"requires": ["job_id"]},
                "cancel": {"requires": ["job_id"]},
            }
        }
    if normalized == "start":
        if command is None or not command.strip():
            raise ValueError("wsl2_async action='start' requires command")
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
