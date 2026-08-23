from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server.context import HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CallToolRequestParams,
    RequestParams,
)
from pydantic import Field

from .execution_manager import (
    TERMINAL_EXECUTION_STATUSES,
    ExecutionManager,
    ExecutionNotFoundError,
)

EXTENSION_ID = "io.modelcontextprotocol/tasks"


class GetTaskParams(RequestParams):
    task_id: str = Field(alias="taskId")


class UpdateTaskParams(RequestParams):
    task_id: str = Field(alias="taskId")
    input_responses: dict[str, Any] = Field(
        default_factory=dict, alias="inputResponses"
    )


class CancelTaskParams(RequestParams):
    task_id: str = Field(alias="taskId")


class TasksExtension(Extension):
    """SEP-2663 Tasks extension backed by the durable WSL2 ExecutionManager."""

    identifier = EXTENSION_ID

    def __init__(self, executions: ExecutionManager) -> None:
        self.executions = executions

    def methods(self):
        versions = frozenset({"2026-07-28"})
        return (
            MethodBinding(
                "tasks/get", GetTaskParams, self._get, protocol_versions=versions
            ),
            MethodBinding(
                "tasks/update",
                UpdateTaskParams,
                self._update,
                protocol_versions=versions,
            ),
            MethodBinding(
                "tasks/cancel",
                CancelTaskParams,
                self._cancel,
                protocol_versions=versions,
            ),
        )

    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next,
    ) -> HandlerResult:
        if (
            params.name != "wsl2_async"
            or str((params.arguments or {}).get("action", "")).strip().lower()
            != "start"
            or ctx.protocol_version != "2026-07-28"
            or not self._client_supports_tasks(ctx)
        ):
            return await call_next(ctx)

        args = params.arguments or {}
        execution = self.executions.start(
            command=str(args.get("command", "")),
            cwd=args.get("cwd"),
            timeout=float(args.get("timeout", 600.0)),
        )
        return self._create_task(execution)

    async def _get(
        self, ctx: ServerRequestContext[Any, Any], params: GetTaskParams
    ) -> HandlerResult:
        self._require_tasks(ctx)
        try:
            execution = self.executions.status(params.task_id)
        except ExecutionNotFoundError as exc:
            self._unknown(params.task_id, exc)
        return self._detailed_task(execution)

    async def _update(
        self, ctx: ServerRequestContext[Any, Any], params: UpdateTaskParams
    ) -> HandlerResult:
        self._require_tasks(ctx)
        try:
            self.executions.status(params.task_id)
        except ExecutionNotFoundError as exc:
            self._unknown(params.task_id, exc)
        # Shell executions never enter input_required. Per SEP-2663, unknown/already-satisfied
        # inputResponse keys are ignored; an empty complete ack is sufficient here.
        return {"resultType": "complete"}

    async def _cancel(
        self, ctx: ServerRequestContext[Any, Any], params: CancelTaskParams
    ) -> HandlerResult:
        self._require_tasks(ctx)
        try:
            self.executions.cancel(params.task_id)
        except ExecutionNotFoundError as exc:
            self._unknown(params.task_id, exc)
        return {"resultType": "complete"}

    @staticmethod
    def _client_supports_tasks(ctx: ServerRequestContext[Any, Any]) -> bool:
        caps = ctx.session.client_capabilities
        return bool(caps and caps.extensions and EXTENSION_ID in caps.extensions)

    def _require_tasks(self, ctx: ServerRequestContext[Any, Any]) -> None:
        if not self._client_supports_tasks(ctx):
            from mcp.shared.exceptions import MCPError

            raise MCPError(
                code=-32021,
                message="Missing required client capability",
                data={"requiredCapabilities": {"extensions": {EXTENSION_ID: {}}}},
            )

    @staticmethod
    def _unknown(task_id: str, exc: Exception) -> None:
        from mcp.shared.exceptions import MCPError

        raise MCPError(code=INVALID_PARAMS, message=f"Unknown task: {task_id}") from exc

    def _create_task(self, execution: dict[str, Any]) -> dict[str, Any]:
        task = self._task_base(execution)
        task["resultType"] = "task"
        return task

    def _detailed_task(self, execution: dict[str, Any]) -> dict[str, Any]:
        task = self._task_base(execution)
        task["resultType"] = "complete"
        status = execution["status"]
        if status == "completed":
            result = self.executions.result(execution["execution_id"])
            shell_result = {
                "command": self._read_command(execution["execution_id"]),
                "exit_code": result.get("exit_code"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
            }
            task["result"] = {
                "resultType": "complete",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(shell_result, ensure_ascii=False),
                    }
                ],
                "structuredContent": shell_result,
                "isError": bool(result.get("exit_code")),
            }
        elif status == "failed":
            task["error"] = {
                "code": INTERNAL_ERROR,
                "message": execution.get("status_message") or "Background task failed",
            }
        return task

    def _task_base(self, execution: dict[str, Any]) -> dict[str, Any]:
        status_map = {
            "running": "working",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        status = status_map[execution["status"]]
        payload: dict[str, Any] = {
            "taskId": execution["execution_id"],
            "status": status,
            "statusMessage": execution.get("status_message"),
            "createdAt": execution["created_at"],
            "lastUpdatedAt": execution["updated_at"],
            "ttlMs": self._ttl_ms(execution),
            "pollIntervalMs": execution.get("poll_interval_ms", 1000),
        }
        return payload

    def _ttl_ms(self, execution: dict[str, Any]) -> int | None:
        if execution["status"] not in TERMINAL_EXECUTION_STATUSES:
            return None
        created = datetime.fromisoformat(execution["created_at"])
        updated = datetime.fromisoformat(execution["updated_at"])
        age_ms = max(0, int((updated - created).total_seconds() * 1000))
        return age_ms + self.executions.retention_days * 24 * 60 * 60 * 1000

    def _read_command(self, execution_id: str) -> str:
        execution_dir = self.executions.root / execution_id
        try:
            meta = json.loads((execution_dir / "meta.json").read_text())
        except OSError, json.JSONDecodeError:
            return ""
        return str(meta.get("command", ""))
