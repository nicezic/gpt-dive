from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .code_mode_errors import RecoveryAction, category_for, recovery_for
from .code_mode_errors import guidance_for as _code_mode_error_guidance
from .execution_store import EXECUTION_ID_PATTERN

_CODE_MODE_RESULT_MAX_BYTES = 128 * 1024  # 128 KiB
_ERROR_DETAIL_MAX_CHARS = 4096


def _bound_code_mode_result(result: Any, execution_id: str | None = None) -> Any:
    if isinstance(result, str):
        encoded = result.encode("utf-8", errors="replace")
        if len(encoded) <= _CODE_MODE_RESULT_MAX_BYTES:
            return result
        prefix = encoded[:_CODE_MODE_RESULT_MAX_BYTES].decode("utf-8", errors="ignore")
        marker = f"\n\n... (output truncated at 128 KiB; execution_id: {execution_id or 'unknown'})"
        return prefix + marker

    try:
        serialized = json.dumps(result, ensure_ascii=False)
    except Exception:
        return result

    encoded = serialized.encode("utf-8", errors="replace")
    if len(encoded) <= _CODE_MODE_RESULT_MAX_BYTES:
        return result

    prefix = encoded[:_CODE_MODE_RESULT_MAX_BYTES].decode("utf-8", errors="ignore")
    marker = f"\n\n... (output truncated at 128 KiB; execution_id: {execution_id or 'unknown'})"
    return prefix + marker


ExecutionState = Literal[
    "accepted", "running", "completed", "failed", "cancelled", "lost"
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrackedTaskView(_ClosedModel):
    execution_id: str
    label: str
    state: ExecutionState
    reason: str | None
    elapsed_seconds: int


class CodeModeCompleted(_ClosedModel):
    status: Literal["completed"] = "completed"
    execution_id: str
    result: Any
    tracked_tasks: list[TrackedTaskView] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tracked_tasks_guidance: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("result", mode="after")
    @classmethod
    def _validate_result(cls, v: Any, info: ValidationInfo) -> Any:
        exec_id = info.data.get("execution_id") if info.data else None
        return _bound_code_mode_result(v, exec_id)


_CODE_MODE_RUNNING_GUIDANCE = (
    "Execution has a published Task. If still running, it continues in background. "
    "Use task(action='get', execution_id=...) to inspect status or retrieve result."
)


class CodeModeRunning(_ClosedModel):
    status: Literal["running"] = "running"
    execution_id: str
    state: ExecutionState = "running"
    elapsed_seconds: int = 0
    guidance: str = _CODE_MODE_RUNNING_GUIDANCE
    tracked_tasks: list[TrackedTaskView] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tracked_tasks_guidance: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


_CODE_MODE_ERROR_GUIDANCE = _code_mode_error_guidance("execution_error")


class CodeModeErrorDetails(_ClosedModel):
    category: str = "unknown"
    code: str
    message: str
    detail: str | None = None

    @field_validator("detail")
    @classmethod
    def _bound_detail(cls, value: str | None) -> str | None:
        if value is not None and len(value) > _ERROR_DETAIL_MAX_CHARS:
            suffix = "... (detail truncated)"
            return value[: _ERROR_DETAIL_MAX_CHARS - len(suffix)] + suffix
        return value

    recovery: RecoveryAction | None = None
    http_status: int | None = Field(
        default=None, ge=100, le=599, exclude_if=lambda value: value is None
    )
    diagnostics: list[dict[str, Any]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    diagnostics_total: int | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="before")
    @classmethod
    def _default_error_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("category", category_for(str(value.get("code", ""))))
            value.setdefault("recovery", recovery_for(str(value.get("code", ""))))
        return value

    @field_validator("diagnostics")
    @classmethod
    def _bound_diagnostics(
        cls, value: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        if value is None:
            return None
        return [
            {
                "code": item.get("code"),
                "message": str(item.get("message", ""))[:500],
                "location": item.get("location"),
            }
            for item in value[:8]
        ]


class CodeModeFailed(_ClosedModel):
    status: Literal["failed"] = "failed"
    execution_id: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    error: CodeModeErrorDetails
    guidance: str = _CODE_MODE_ERROR_GUIDANCE
    tracked_tasks: list[TrackedTaskView] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tracked_tasks_guidance: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


CodeModeOutput = Annotated[
    CodeModeCompleted | CodeModeRunning | CodeModeFailed,
    Field(discriminator="status"),
]

CodeModeOutcome = CodeModeOutput


class _CodeModePublicOutput(RootModel[CodeModeOutput]):
    pass


class WslExecWorkOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    tracked_tasks: list[TrackedTaskView] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tracked_tasks_guidance: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


_CODE_MODE_OUTPUT_ADAPTER = TypeAdapter(CodeModeOutput)


def _code_mode_output(value: dict[str, Any]) -> CodeModeOutput:
    payload = dict(value)
    if payload.get("status") == "failed" and "guidance" not in payload:
        payload["guidance"] = _code_mode_error_guidance(
            str(payload["error"].get("code", "execution_error"))
        )

    if payload.get("status") == "running" and "guidance" not in payload:
        payload["guidance"] = _CODE_MODE_RUNNING_GUIDANCE

    return _CODE_MODE_OUTPUT_ADAPTER.validate_python(payload)


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


class TaskActionFailed(_ClosedModel):
    status: Literal["failed"] = "failed"
    action: Literal["get", "cancel", "dismiss"]
    execution_id: str
    error: CodeModeErrorDetails
    guidance: str


def _task_action_failure(
    request: TaskGetRequest | TaskCancelRequest | TaskDismissRequest,
    *,
    code: str,
    message: str,
    guidance: str,
) -> TaskActionFailed:
    return TaskActionFailed(
        action=request.action,
        execution_id=request.execution_id,
        error=CodeModeErrorDetails(code=code, message=message),
        guidance=guidance,
    )


class TaskCancelOutput(_ClosedModel):
    action: Literal["cancel"] = "cancel"
    task: TaskView


class TaskDismissOutput(_ClosedModel):
    action: Literal["dismiss"] = "dismiss"
    execution_id: str
    state: ExecutionState
    dismissed: bool


TaskOutcome = (
    TaskListOutput
    | CodeModeOutcome
    | TaskCancelOutput
    | TaskDismissOutput
    | TaskActionFailed
)


class _TaskPublicOutcome(RootModel[TaskOutcome]):
    pass


def _task_view(value: dict[str, Any]) -> TaskView:
    return TaskView.model_validate(value)
