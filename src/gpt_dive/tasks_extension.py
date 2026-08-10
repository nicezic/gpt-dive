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

from .job_manager import TERMINAL_STATUSES, JobManager, JobNotFoundError

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
    """SEP-2663 Tasks extension backed by the durable WSL2 JobManager."""

    identifier = EXTENSION_ID

    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs

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
        job = self.jobs.start(
            command=str(args.get("command", "")),
            cwd=args.get("cwd"),
            timeout=float(args.get("timeout", 600.0)),
        )
        return self._create_task(job)

    async def _get(
        self, ctx: ServerRequestContext[Any, Any], params: GetTaskParams
    ) -> HandlerResult:
        self._require_tasks(ctx)
        try:
            job = self.jobs.status(params.task_id)
        except JobNotFoundError as exc:
            self._unknown(params.task_id, exc)
        return self._detailed_task(job)

    async def _update(
        self, ctx: ServerRequestContext[Any, Any], params: UpdateTaskParams
    ) -> HandlerResult:
        self._require_tasks(ctx)
        try:
            self.jobs.status(params.task_id)
        except JobNotFoundError as exc:
            self._unknown(params.task_id, exc)
        # Shell jobs never enter input_required. Per SEP-2663, unknown/already-satisfied
        # inputResponse keys are ignored; an empty complete ack is sufficient here.
        return {"resultType": "complete"}

    async def _cancel(
        self, ctx: ServerRequestContext[Any, Any], params: CancelTaskParams
    ) -> HandlerResult:
        self._require_tasks(ctx)
        try:
            self.jobs.cancel(params.task_id)
        except JobNotFoundError as exc:
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

    def _create_task(self, job: dict[str, Any]) -> dict[str, Any]:
        task = self._task_base(job)
        task["resultType"] = "task"
        return task

    def _detailed_task(self, job: dict[str, Any]) -> dict[str, Any]:
        task = self._task_base(job)
        task["resultType"] = "complete"
        status = job["status"]
        if status == "completed":
            result = self.jobs.result(job["job_id"])
            shell_result = {
                "command": self._read_command(job["job_id"]),
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
                "message": job.get("status_message") or "Background task failed",
            }
        return task

    def _task_base(self, job: dict[str, Any]) -> dict[str, Any]:
        status_map = {
            "running": "working",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        status = status_map[job["status"]]
        payload: dict[str, Any] = {
            "taskId": job["job_id"],
            "status": status,
            "statusMessage": job.get("status_message"),
            "createdAt": job["created_at"],
            "lastUpdatedAt": job["updated_at"],
            "ttlMs": self._ttl_ms(job),
            "pollIntervalMs": job.get("poll_interval_ms", 1000),
        }
        return payload

    def _ttl_ms(self, job: dict[str, Any]) -> int | None:
        if job["status"] not in TERMINAL_STATUSES:
            return None
        created = datetime.fromisoformat(job["created_at"])
        updated = datetime.fromisoformat(job["updated_at"])
        age_ms = max(0, int((updated - created).total_seconds() * 1000))
        return age_ms + self.jobs.retention_days * 24 * 60 * 60 * 1000

    def _read_command(self, job_id: str) -> str:
        job_dir = self.jobs.root / job_id
        try:
            meta = json.loads((job_dir / "meta.json").read_text())
        except OSError, json.JSONDecodeError:
            return ""
        return str(meta.get("command", ""))
