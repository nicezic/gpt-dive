from __future__ import annotations

import asyncio
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

from .code_runtime import CallableRegistry, MontyCodeRuntime
from .job_manager import JobManager
from .subagent_runtime import invoke_subagent
from .tasks_extension import TasksExtension


jobs = JobManager()
tasks_extension = TasksExtension(jobs)
code_runtime = MontyCodeRuntime()

mcp = MCPServer(
    name="gpt-dive",
    title="GPT Dive",
    description=(
        "MCP runtime that lets GPT dive into the user's local WSL2 development "
        "environment for direct and asynchronous execution. pls,`bootstrap`, first"
    ),
    instructions=(
        "GPT Dive operates the user's local WSL2 environment. Treat its filesystem, "
        "processes, network state, and command results as belonging to the user's local "
        "machine, not as a separate hosted or ChatGPT sandbox. In a fresh ChatGPT Web "
        "session, call bootstrap first. After bootstrap, prefer code_mode as the primary execution "
        "root for normal work so registered capabilities and harness policy stay in control. "
        "Use wsl2_sync only for short direct commands that need an immediate result, and "
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
) -> dict[str, Any]:
    if not command.strip():
        raise ValueError("command must not be empty")

    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    run_cwd = str(Path(cwd).expanduser()) if cwd else None
    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    pnpm_bin = Path.home() / ".local" / "share" / "pnpm"
    guarded_command = f'export PATH="{guard_bin}:{pnpm_bin}:$PATH"; {command}'

    try:
        completed = subprocess.run(
            ["/bin/bash", "-lc", guarded_command],
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        return {
            "command": command,
            "exit_code": completed.returncode,
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
            "exit_code": 124,
            "stdout": stdout,
            "stderr": (
                f"{stderr}\n"
                f"[wsl2_sync] timed out after {timeout} seconds"
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


def _parse_required_manifest(manifest_text: str) -> list[str]:
    """Extract numbered Markdown paths from the manifest's Required section."""
    match = re.search(
        r"^## Required\s*$\n(?P<body>.*?)(?=^## \S|\Z)",
        manifest_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise ValueError("bootstrap manifest has no '## Required' section")

    paths = re.findall(r"^\s*\d+\.\s+`([^`]+)`\s*$", match.group("body"), re.MULTILINE)
    if not paths:
        raise ValueError("bootstrap manifest Required section contains no document paths")
    return paths


def _read_bootstrap_packet(log_tail_lines: int = 30) -> dict[str, Any]:
    """Assemble fresh-session context from the trusted wiki bootstrap manifest."""
    if log_tail_lines < 0 or log_tail_lines > 200:
        raise ValueError("log_tail_lines must be between 0 and 200")

    wiki = _wiki_path()
    manifest = wiki / "bootstrap" / "manifest.md"
    if not manifest.is_file():
        raise FileNotFoundError(f"bootstrap manifest not found: {manifest}")

    manifest_text = manifest.read_text(errors="replace")
    required = _parse_required_manifest(manifest_text)
    documents: list[dict[str, str]] = []
    warnings: list[str] = []

    for relative in required:
        candidate = (wiki / relative).resolve()
        try:
            candidate.relative_to(wiki)
        except ValueError as exc:
            raise ValueError(f"bootstrap path escapes trusted wiki: {relative}") from exc

        if not candidate.is_file():
            warnings.append(f"missing required document: {relative}")
            continue
        documents.append({
            "path": relative,
            "content": candidate.read_text(errors="replace"),
        })

    if not documents:
        raise RuntimeError("bootstrap manifest resolved no readable required documents")

    log_tail = ""
    log_path = wiki / "log.md"
    if log_tail_lines and log_path.is_file():
        lines = log_path.read_text(errors="replace").splitlines()
        log_tail = "\n".join(lines[-log_tail_lines:])

    chunks = [
        f"# BOOTSTRAP PACKET\nWiki: {wiki}\nManifest: {manifest}\n",
    ]
    for doc in documents:
        chunks.append(
            f"\n\n===== BEGIN {doc['path']} =====\n"
            f"{doc['content'].rstrip()}\n"
            f"===== END {doc['path']} ====="
        )
    if log_tail:
        chunks.append(
            "\n\n===== BEGIN log.md (recent tail) =====\n"
            f"{log_tail}\n"
            "===== END log.md (recent tail) ====="
        )

    return {
        "wiki_path": str(wiki),
        "manifest_path": str(manifest),
        "required_files": [doc["path"] for doc in documents],
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
            description=(
                "Shell command to execute on the user's local machine inside their WSL2 "
                "environment. Runs via /bin/bash -lc."
            )
        ),
    ],
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Optional working directory in the user's local WSL2 filesystem. "
                "Use Linux/WSL paths such as /home/user/project or ~/project."
            )
        ),
    ] = None,
    timeout: Annotated[
        float,
        Field(
            gt=0,
            description=(
                "Maximum command runtime in seconds before the MCP call times out. "
                "Defaults to 600 seconds."
            ),
        ),
    ] = 600.0,
) -> dict[str, Any]:
    """Run a short shell command synchronously in the user's local WSL2 environment."""
    return _run_command(command, cwd, timeout)


def _build_code_registry(default_cwd: str | None) -> CallableRegistry:
    registry = CallableRegistry()

    async def local_exec(
        *,
        command: str,
        cwd: str | None = None,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Run a guarded short local shell command and wait for its result."""
        return await asyncio.to_thread(
            _run_command,
            command,
            cwd if cwd is not None else default_cwd,
            timeout,
        )

    async def local_start(
        *,
        command: str,
        cwd: str | None = None,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Start a durable local background job and return its compact status."""
        return await asyncio.to_thread(
            jobs.start,
            command,
            cwd if cwd is not None else default_cwd,
            timeout,
        )

    async def local_status(*, job_id: str) -> dict[str, Any]:
        """Return compact status for a durable local background job."""
        return await asyncio.to_thread(jobs.status, job_id)

    async def local_result(*, job_id: str) -> dict[str, Any]:
        """Return a durable local job result, including stdout/stderr when ready."""
        return await asyncio.to_thread(jobs.result, job_id)

    async def local_cancel(*, job_id: str) -> dict[str, Any]:
        """Request cancellation of a durable local background job."""
        return await asyncio.to_thread(jobs.cancel, job_id)

    async def subagent_call(
        *,
        model: str,
        task: str,
        timeout: float = 120.0,
        output_tokens_limit: int = 4096,
    ) -> dict[str, Any]:
        """Call a registered subagent model alias: opus5, m3, terra, or luna."""
        return await invoke_subagent(
            model=model,
            task=task,
            timeout=timeout,
            output_tokens_limit=output_tokens_limit,
        )

    registry.register("local_exec", local_exec)
    registry.register("local_start", local_start)
    registry.register("local_status", local_status)
    registry.register("local_result", local_result)
    registry.register("local_cancel", local_cancel)
    registry.register("subagent_call", subagent_call)
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
    except (OSError, ValueError):
        pass
    finally:
        ref.unlink(missing_ok=True)


def _start_background_code_mode(code: str, cwd: str | None) -> dict[str, Any]:
    payload = {"v": CODE_MODE_WORKER_PROTOCOL, "code": code, "cwd": cwd}
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
        command = f"{shlex.quote(sys.executable)} -m gpt_dive.code_mode_worker {payload_arg}"
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
            raw, code="background_cancelled", message="Background Code Mode job was cancelled."
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
        error_message = str(error.get("message") or "Background Code Mode execution failed.")
    else:
        error_code = "worker_protocol_error"
        error_message = "Background Code Mode worker exited without a valid error envelope."
    if envelope.get("ok") is True and exit_code != 0:
        error_code = "worker_protocol_error"
        error_message = "Worker reported success but exited with a non-zero status."
    return _background_error(raw, code=error_code, message=error_message)


@mcp.tool(
    title="Pydantic Monty Code Mode",
    description=(
        "Primary harnessable execution root for GPT Dive, backed by Pydantic Monty and registered "
        "local WSL2 capabilities. Prefer this for normal work so capability policy, composition, "
        "parallel execution, and local preprocessing remain inside the harness. Use background=True "
        "to detach long-running Monty programs, then action='status', 'result', or 'cancel' with the "
        "returned job_id. Combine independent operations and filter/transform/aggregate large "
        "intermediate data before returning only a compact result. The sandbox receives CWD and "
        "CAPABILITIES; inspect CAPABILITIES at runtime instead of relying on a hard-coded capability "
        "list. The local WSL2 filesystem is mounted read-write."
    ),
)
async def code_mode(
    code: Annotated[
        str | None,
        Field(
            description=(
                "Monty Python code to execute. Process large intermediate results inside the "
                "sandbox and make the final expression a compact result."
            )
        ),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Optional default WSL2 working directory exposed to code as CWD and inherited "
                "by registered capabilities when they accept cwd."
            )
        ),
    ] = None,
    background: Annotated[
        bool,
        Field(description="Detach this Code Mode program as a durable background job."),
    ] = False,
    action: Annotated[
        str | None,
        Field(description="Lifecycle action for a background Code Mode job: status, result, or cancel."),
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
            raise ValueError("code_mode requires code unless action + job_id are provided")
        if job_id is not None:
            raise ValueError("job_id is only valid with a lifecycle action")
        if background:
            return await asyncio.to_thread(_start_background_code_mode, str(code), cwd)
        return await code_runtime.run(str(code), _build_code_registry(cwd), cwd=cwd)

    if has_code:
        raise ValueError("code and lifecycle action are mutually exclusive")
    if background:
        raise ValueError("background is only valid when launching code")
    if cwd is not None:
        raise ValueError("cwd is only valid when launching code")
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
            description=(
                "Backend-defined async-job action. Use 'capabilities' to discover supported "
                "actions without requiring MCP schema changes."
            )
        ),
    ],
    command: Annotated[
        str | None,
        Field(description="Shell command for actions that launch a job."),
    ] = None,
    job_id: Annotated[
        str | None,
        Field(description="Durable job ID for actions that operate on an existing job."),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(description="Optional WSL2 working directory for job-launch actions."),
    ] = None,
    timeout: Annotated[
        float,
        Field(gt=0, description="Maximum runtime in seconds for job-launch actions. Defaults to 600."),
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
        "`@dive` tool. It loads fresh-session context from the trusted wiki stored in the "
        "user's local WSL2 environment."
    ),
)
def bootstrap(
    log_tail_lines: Annotated[
        int,
        Field(
            ge=0,
            le=200,
            description=(
                "Number of recent lines to include from the trusted local "
                "WSL2 wiki log.md. Defaults to 30."
            ),
        ),
    ] = 30,
) -> dict[str, Any]:
    """Load fresh-session context from the trusted wiki on the user's local WSL2."""
    return _read_bootstrap_packet(log_tail_lines=log_tail_lines)


if __name__ == "__main__":
    mcp.run()
