from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic_ai_harness import FileSystem

from .agy_worker import DEFAULT_MODEL as DEFAULT_AGY_MODEL
from .agy_worker import invoke_agy_worker
from .code_runtime import CallableRegistry, MontyCodeRuntime
from .command_runtime import run_command as run_runtime_command
from .council import emit_sol_response
from .execution_context import ExecutionContext
from .filesystem_policy import harness_denied_patterns
from .model_call import invoke_model_call
from .repo_search import search_repo
from .subagent_runtime import invoke_subagent

code_runtime = MontyCodeRuntime()

_AGY_WORKER_POLICY_SECONDS = 360.0
_SUBAGENT_POLICY_SECONDS = 600.0
_PEER_REVIEW_POLICY_SECONDS = 600.0


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
    execution_context: ExecutionContext,
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
        reject_broad_search_root(resolved, operation="search_files")
        return await filesystem_toolset.search_files(
            pattern, path=str(resolved), include_glob=include_glob
        )

    async def find_files(pattern: str, *, path: str = ".") -> str:
        """Find files by glob. Relative paths use cwd; host reads are allowed anywhere except credential/secret paths."""
        resolved = resolve_path(path)
        reject_broad_search_root(resolved, operation="find_files")
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

    async def agy_worker(
        *,
        task: str,
        model: str = DEFAULT_AGY_MODEL,
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
            timeout=execution_context.child_budget(_AGY_WORKER_POLICY_SECONDS),
            workspace_dir=cwd if cwd is not None else default_cwd,
            conversation_id=conversation_id,
        )

    async def subagent_call(
        *,
        model: str,
        task: str,
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
            timeout=execution_context.child_budget(_SUBAGENT_POLICY_SECONDS),
            output_tokens_limit=output_tokens_limit,
            workspace_dir=cwd if cwd is not None else default_cwd,
        )

    async def peer_review(
        *,
        provider: str,
        model: str | None = None,
        prompt: str,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Call an independent peer reviewer; omit model to use the provider's default."""
        return await invoke_model_call(
            provider=provider,
            model=model,
            prompt=prompt,
            timeout=execution_context.child_budget(_PEER_REVIEW_POLICY_SECONDS),
            peer_review=True,
            workspace_dir=cwd if cwd is not None else default_cwd,
        )

    async def run_command(command: str) -> dict[str, Any]:
        """Run one awaited local shell command under the owning Execution budget.

        Output is spooled with hard bounds and truncated before entering model context.
        Use an explicit systemd-run --user sibling unit only when intentionally handing
        work outside GPT Dive Runtime and accepting loss of Task/deadline guarantees.
        """
        return await run_runtime_command(
            command,
            cwd=str(effective_cwd),
            context=execution_context,
        )

    def deadline_remaining() -> float:
        """Return the current read-only Execution work budget in seconds."""
        return execution_context.remaining_seconds()

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
        reject_broad_search_root(search_path, operation="repo_search")
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
    registry.register("repo_search", repo_search)
    registry.register("council_emit", council_emit)
    registry.register("run_command", run_command)
    registry.register("deadline_remaining", deadline_remaining)
    return registry
