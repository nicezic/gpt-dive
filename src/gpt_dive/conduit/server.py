from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import BaseModel, ConfigDict, Field

from ..execution_manager import ExecutionManager
from .events import RedisEventPublisher
from .runtime import ConduitRuntime

ArgModelBase.model_config["extra"] = "forbid"

executions = ExecutionManager()
runtime = ConduitRuntime(executions=executions, publisher=RedisEventPublisher())

mcp = MCPServer(
    name="c",
    title="Conduit",
    description=(
        "Conversation-driven task conduit for ChatGPT Web. Each c call performs one "
        "strictly selected action and returns a compact projection of outstanding "
        "Runtime-owned Tasks."
    ),
    instructions=(
        "Use start to launch one always-durable Runtime Execution and continue reasoning. "
        "Every call returns current Task awareness. Use get for non-destructive result "
        "retrieval, cancel only for explicit cancellation, dismiss after a terminal Task has "
        "been handled, sync for a short marker, and emit for conversation output. Do not poll "
        "a running Task repeatedly. execution_id is the only lifecycle identity."
    ),
)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ExecutionId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class StartRequest(_ClosedModel):
    action: Literal["start"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    command: Annotated[str, Field(min_length=1)]
    cwd: str | None = None


class SyncRequest(_ClosedModel):
    action: Literal["sync"]
    text: Annotated[str, Field(min_length=1)]


class GetRequest(_ClosedModel):
    action: Literal["get"]
    execution_id: ExecutionId


class CancelRequest(_ClosedModel):
    action: Literal["cancel"]
    execution_id: ExecutionId


class DismissRequest(_ClosedModel):
    action: Literal["dismiss"]
    execution_id: ExecutionId


class EmitRequest(_ClosedModel):
    action: Literal["emit"]
    text: Annotated[str, Field(min_length=1)]
    session_id: str | None = None


ConduitRequest = Annotated[
    StartRequest
    | SyncRequest
    | GetRequest
    | CancelRequest
    | DismissRequest
    | EmitRequest,
    Field(discriminator="action"),
]


@mcp.tool(
    title="Conduit",
    description=(
        "Perform one Conduit action. start returns immediately with the same execution_id "
        "used by later get, cancel, or dismiss actions. Every response includes current Tasks."
    ),
)
def c(request: ConduitRequest) -> dict[str, Any]:
    return runtime.call(**request.model_dump())
