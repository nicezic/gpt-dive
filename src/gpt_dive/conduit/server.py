from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..job_manager import JobManager
from .events import RedisEventPublisher
from .runtime import ConduitRuntime

jobs = JobManager(Path.home() / ".local" / "state" / "gpt-dive" / "conduit" / "jobs")
runtime = ConduitRuntime(jobs=jobs, publisher=RedisEventPublisher())

mcp = MCPServer(
    name="c",
    title="Conduit",
    description=(
        "Conversation-driven task conduit for ChatGPT Web. Each `c` call performs exactly "
        "one action and always returns a compact snapshot of active Conduit tasks."
    ),
    instructions=(
        "Use start to launch detached work and continue reasoning without waiting. Every call "
        "returns current task status, so normal conversation turns provide task refresh. Use sync "
        "for a short synchronous marker, collect to read a task result non-destructively, and emit "
        "for user-facing conversation output. Do not repeatedly poll a running task."
    ),
)


@mcp.tool(
    title="Conduit",
    description=(
        "Perform one Conduit action. `start` launches detached work and returns immediately; "
        "after it returns, keep reasoning and call `c` again in the same turn when independent "
        "work remains. Every response includes the current compact task snapshot."
    ),
)
def c(
    action: Annotated[
        str,
        Field(description="One action: start, sync, collect, or emit."),
    ],
    *,
    label: Annotated[
        str | None,
        Field(description="Short human-readable task label for start (max 80 chars).", max_length=80),
    ] = None,
    command: Annotated[
        str | None,
        Field(description="Shell command for start."),
    ] = None,
    cwd: Annotated[
        str | None,
        Field(description="Optional WSL2 working directory for start."),
    ] = None,
    timeout: Annotated[
        float,
        Field(description="Maximum runtime in seconds for start."),
    ] = 600.0,
    task_id: Annotated[
        str | None,
        Field(description="Conduit task ID for collect."),
    ] = None,
    text: Annotated[
        str | None,
        Field(description="Text for sync or emit."),
    ] = None,
) -> dict[str, Any]:
    return runtime.call(
        action=action,
        label=label,
        command=command,
        cwd=cwd,
        timeout=timeout,
        task_id=task_id,
        text=text,
    )
