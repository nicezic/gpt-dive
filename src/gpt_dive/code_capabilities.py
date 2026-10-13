from __future__ import annotations

import asyncio
import base64
import functools
import gzip
from pathlib import Path
from typing import Any, TypedDict, cast

from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import FileSystem

from .agy_worker import DEFAULT_MODEL as DEFAULT_AGY_MODEL
from .agy_worker import invoke_agy_worker
from .code_file_read import read_raw_file
from .code_runtime import CallableRegistry, MontyCodeRuntime
from .command_runtime import (
    RuntimeRecord,
    child_budget,
    remaining_seconds,
)
from .command_runtime import (
    run_command as run_runtime_command,
)
from .conduit.room import emit_sol_response
from .filesystem_policy import harness_denied_patterns
from .model_call import invoke_model_call
from .subagent_runtime import invoke_subagent

code_runtime = MontyCodeRuntime()

_AGY_WORKER_POLICY_SECONDS = 360.0
_SUBAGENT_POLICY_SECONDS = 600.0
_PEER_REVIEW_POLICY_SECONDS = 600.0


class RunCommandResult(TypedDict):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool


def code_mode_home_root() -> Path:
    """Return the user home used only for credential/secret path policy."""
    return Path.home().resolve()


_BROAD_SEARCH_ROOTS = {"/", "/mnt/c"}


def reject_broad_search_root(path: Path, *, operation: str) -> None:
    resolved = str(path.resolve())
    if resolved in _BROAD_SEARCH_ROOTS:
        raise ValueError(
            f"{operation} refuses broad recursive search rooted at {resolved}; "
            "narrow to a specific subdirectory first"
        )


def build_code_registry(
    default_cwd: str | None,
    *,
    record: RuntimeRecord,
) -> CallableRegistry:
    registry = CallableRegistry()
    effective_cwd = (
        Path(default_cwd).expanduser().resolve()
        if default_cwd is not None
        else Path.home().resolve()
    )

    home = code_mode_home_root()
    denied_patterns = harness_denied_patterns(root=Path("/"), home=home)
    filesystem_toolset: Any = FileSystem(
        root_dir="/",
        denied_patterns=denied_patterns,
        read_only_patterns=[],
    ).get_toolset()
    workspace = LocalWorkspaceBackend(effective_cwd)

    def resolve_path(path: str) -> Path:
        expanded = Path(path).expanduser()
        if expanded.is_absolute():
            return expanded.resolve()
        return (effective_cwd / expanded).resolve()

    async def read_file(
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        line_numbers: bool = False,
        raw: bool | None = None,
    ) -> str:
        """Read a text file. Returns exact raw text content by default.

        Raw output is capped at 256 KiB: use offset/limit to obtain exact
        snippets for editing. A truncation notice is not file content.

        Relative paths use cwd; host reads are allowed anywhere except credential/secret paths.
        Set line_numbers=True (or raw=False) to include line numbers and metadata header for visual inspection.
        """
        show_line_numbers = line_numbers if raw is None else (not raw)
        resolved_path = resolve_path(path)
        if show_line_numbers:
            return await filesystem_toolset.read_file(
                str(resolved_path), offset=offset, limit=limit, workspace=workspace
            )
        return await read_raw_file(
            resolved_path=resolved_path,
            requested_path=path,
            home=home,
            workspace=workspace,
            offset=offset,
            limit=limit,
        )

    async def list_directory(path: str = ".") -> str:
        """List a directory. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        return await filesystem_toolset.list_directory(
            str(resolve_path(path)), workspace=workspace
        )

    async def search_files(
        pattern: str, *, path: str = ".", include_glob: str | None = None
    ) -> str:
        """Search file contents by regex. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        resolved = resolve_path(path)
        reject_broad_search_root(resolved, operation="search_files")
        return await filesystem_toolset.search_files(
            pattern, path=str(resolved), include_glob=include_glob, workspace=workspace
        )

    async def find_files(pattern: str, *, path: str = ".") -> str:
        """Find files by glob. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        resolved = resolve_path(path)
        reject_broad_search_root(resolved, operation="find_files")
        return await filesystem_toolset.find_files(
            pattern, path=str(resolved), workspace=workspace
        )

    async def file_info(path: str) -> str:
        """Get file or directory metadata. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        return await filesystem_toolset.file_info(
            str(resolve_path(path)), workspace=workspace
        )

    async def write_file(
        path: str, content: str, *, expected_hash: str | None = None
    ) -> str:
        """Create or overwrite a file with conflict detection. Host writes are allowed anywhere permitted by the OS except credential/secret paths."""
        return await filesystem_toolset.write_file(
            str(resolve_path(path)),
            content,
            expected_hash=expected_hash,
            workspace=workspace,
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
            str(resolve_path(path)),
            old_text,
            new_text,
            expected_hash=expected_hash,
            workspace=workspace,
        )

    async def create_directory(path: str) -> str:
        """Create a directory and parents. Host writes are allowed anywhere permitted by the OS except credential/secret paths."""
        return await filesystem_toolset.create_directory(
            str(resolve_path(path)), workspace=workspace
        )

    async def agy_worker(
        *,
        task: str,
        model: str = DEFAULT_AGY_MODEL,
        cwd: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a read-only Antigravity worker through the official agy CLI.

        Defaults to Gemini 3.8 Flash High. Google authentication and entitlement stay
        inside agy. Pass conversation_id to resume that exact AGY conversation. The worker
        runs in read-only plan mode and auto-approves headless tool permission prompts.
        """
        return await invoke_agy_worker(
            task=task,
            model=model,
            timeout=child_budget(record, _AGY_WORKER_POLICY_SECONDS),
            workspace_dir=cwd if cwd is not None else default_cwd,
            conversation_id=conversation_id,
        )

    async def subagent_call(
        *,
        alias: str,
        task: str,
        output_tokens_limit: int | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Call a registered subagent with file tools scoped to cwd.

        alias selects the model: a registry alias (for example 'terra5') or
        'provider:model'. If ok is false, preserve the full result including
        error/stderr diagnostics; do not project the failure down to only
        ok/model/output.
        """
        return await invoke_subagent(
            alias=alias,
            task=task,
            timeout=child_budget(record, _SUBAGENT_POLICY_SECONDS),
            output_tokens_limit=output_tokens_limit,
            workspace_dir=cwd if cwd is not None else str(effective_cwd),
        )

    async def peer_review(
        *,
        alias: str,
        prompt: str,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Call an independent peer reviewer with file tools scoped to cwd.

        alias selects the reviewer: a registry alias, 'provider:model', or a
        provider name for that provider's default model.
        """
        return await invoke_model_call(
            alias=alias,
            prompt=prompt,
            timeout=child_budget(record, _PEER_REVIEW_POLICY_SECONDS),
            peer_review=True,
            workspace_dir=cwd if cwd is not None else str(effective_cwd),
        )

    async def run_command(command: str) -> RunCommandResult:
        """Run one awaited local shell command under the owning Execution budget.

        Output is spooled with hard bounds and truncated before entering model context.
        Use an explicit systemd-run --user sibling unit only when intentionally handing
        work outside GPT Dive Runtime and accepting loss of Task/deadline guarantees.
        """
        return cast(
            RunCommandResult,
            await run_runtime_command(
                command,
                cwd=str(effective_cwd),
                record=record,
            ),
        )

    async def gz64(*, payload: str, user_permission: str) -> RunCommandResult:
        """USER-RESTRICTED: call only on explicit user request; never self-authorize. user_permission must exactly equal '정말 유저에게 직접적인 수행 허락을 받았습니다.'."""
        if user_permission != "정말 유저에게 직접적인 수행 허락을 받았습니다.":
            raise PermissionError(
                "gz64 requires the exact user_permission confirmation"
            )
        compressed = base64.b64decode(payload.strip().encode("utf-8"), validate=True)
        command = gzip.decompress(compressed).decode("utf-8")
        return await run_command(command=command)

    def deadline_remaining() -> float:
        """Return the current read-only Execution work budget in seconds."""
        return remaining_seconds(record)

    async def council_emit(
        *,
        council_dir: str,
        message: str,
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        """Persist one Conduit room SOL response using the legacy Git room protocol."""
        return await asyncio.to_thread(
            emit_sol_response, council_dir, message, expected_head
        )

    registry.register("read_file", read_file)
    registry.register("write_file", write_file)
    registry.register("edit_file", edit_file)
    registry.register("list_directory", list_directory)
    registry.register("search_files", search_files)
    registry.register("find_files", find_files)
    registry.register("create_directory", create_directory)
    registry.register("file_info", file_info)
    registry.register("agy_worker", agy_worker)
    registry.register("subagent_call", subagent_call)
    registry.register("peer_review", peer_review)
    registry.register("council_emit", council_emit)
    registry.register("run_command", run_command)
    registry.register("gz64", gz64)
    registry.register("deadline_remaining", deadline_remaining)
    return registry


@functools.lru_cache(maxsize=1)
def code_mode_capability_catalog() -> str:
    """Render the model-facing capability catalog without launching an Execution."""
    registry = build_code_registry(None, record=cast(RuntimeRecord, {}))
    return registry.model_catalog()
