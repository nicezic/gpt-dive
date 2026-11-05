from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .code_mode_errors import RecoveryAction, category_for, recovery_for
from .code_mode_errors import guidance_for as _code_mode_error_guidance
from .execution_store import EXECUTION_ID_PATTERN

_CODE_MODE_RESULT_MAX_BYTES = 32 * 1024  # result preview, including warnings
_ERROR_DETAIL_MAX_CHARS = 4096

_OUTPUT_WARNING_1 = (
    "🚨🚨🚨 WARNING 1/3 — OUTPUT TRUNCATED (output truncated at 32 KiB) 🚨🚨🚨"
)
_OUTPUT_WARNING_2 = "🚨🚨🚨 WARNING 2/3 — CONTENT OMITTED 🚨🚨🚨"
_OUTPUT_WARNING_3 = "🚨🚨🚨 WARNING 3/3 — STOP BEFORE WRITING 🚨🚨🚨"


def _bound_code_mode_result(result: Any) -> tuple[Any, int | None]:
    if isinstance(result, str):
        serialized = result
    else:
        try:
            serialized = json.dumps(result, ensure_ascii=False)
        except Exception:
            return result, None
    encoded = serialized.encode("utf-8", errors="replace")
    if len(encoded) <= _CODE_MODE_RESULT_MAX_BYTES:
        return result, None

    before = (
        f"{_OUTPUT_WARNING_1}\n"
        "INCOMPLETE RESULT. NEVER USE THIS PREVIEW TO WRITE OR EDIT FILES.\n"
        "HEAD (UP TO 30 KiB) FOLLOWS.\n"
        f"{_OUTPUT_WARNING_1}\n\n"
    )
    middle = (
        f"\n\n{_OUTPUT_WARNING_2}\n"
        "MIDDLE CONTENT IS MISSING. HEAD AND TAIL ARE NOT CONTIGUOUS.\n"
        "TAIL (UP TO 1 KiB) FOLLOWS.\n"
        f"{_OUTPUT_WARNING_2}\n\n"
    )
    after = (
        f"\n\n{_OUTPUT_WARNING_3}\n"
        "RETRIEVE MISSING DATA WITH read_execution_result. NEVER RERUN SIDE EFFECTS.\n"
        f"{_OUTPUT_WARNING_3}"
    )
    overhead = len((before + middle + after).encode("utf-8"))
    tail_budget = 1024
    head_budget = min(30 * 1024, _CODE_MODE_RESULT_MAX_BYTES - overhead - tail_budget)
    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = encoded[-tail_budget:].decode("utf-8", errors="ignore")
    return before + head + middle + tail + after, len(head.encode("utf-8"))


def _truncation_guidance(execution_id: str, next_offset: int) -> str:
    return (
        f"{_OUTPUT_WARNING_1}\n"
        f"{_OUTPUT_WARNING_2}\n"
        f"{_OUTPUT_WARNING_3}\n"
        "The execution completed, but the response is incomplete. "
        "Head and tail are NOT adjacent. NEVER use the preview as full file content "
        "or a write/edit anchor.\n"
        "SAFE READ-ONLY RECOVERY (NEW code_mode call):\n"
        "part = await read_execution_result("
        f"execution_id={execution_id!r}, offset={next_offset})\n"
        "part\n"
        "Continue with part['next_offset'] until it is None. "
        "Use read-only retrieval from offset=0 instead if you cannot verify the exact source head. "
        "Do not rerun side-effecting commands; task(get) has the same limit."
    )


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
    output_truncated: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    output_guidance: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tracked_tasks: list[TrackedTaskView] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tracked_tasks_guidance: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def _limit_public_result(self) -> CodeModeCompleted:
        if self.output_truncated:
            return self
        self.result, next_offset = _bound_code_mode_result(self.result)
        if next_offset is not None:
            self.output_truncated = True
            self.output_guidance = _truncation_guidance(self.execution_id, next_offset)
        return self


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
    # MCP requires outputSchema to declare type=object; every union member is an object.
    model_config = ConfigDict(json_schema_extra={"type": "object"})


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
    # MCP requires outputSchema to declare type=object; every union member is an object.
    model_config = ConfigDict(json_schema_extra={"type": "object"})


def _task_view(value: dict[str, Any]) -> TaskView:
    return TaskView.model_validate(value)
