from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .execution_manager import ExecutionManager, ExecutionNotFoundError
from .execution_store import TERMINAL_EXECUTION_STATES
from .worker_subprocess import stderr_tail

CODE_MODE_WORKER_PROTOCOL = 3
TRACKED_TASKS_LIMIT = 8
TRACKED_TASKS_MAX_BYTES = 4096


def _parse_code_mode_envelope(raw: dict[str, Any]) -> dict[str, Any] | None:
    stdout = str(raw.get("stdout") or "")
    if not stdout:
        return None
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("v") != CODE_MODE_WORKER_PROTOCOL or not isinstance(
        envelope.get("ok"), bool
    ):
        return None
    return envelope


def _error_result(
    raw: dict[str, Any],
    *,
    code: str,
    message: str,
    reason: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if reason:
        error["reason"] = reason
    stderr = str(raw.get("stderr") or "")
    if stderr:
        error["worker_stderr"] = stderr_tail(stderr)
    return {
        "kind": "error",
        "execution_id": str(raw["execution_id"]),
        "label": str(raw["label"]),
        "error": error,
    }


def read_execution_result(
    executions: ExecutionManager, execution_id: str
) -> dict[str, Any]:
    raw = executions.result(execution_id)
    record = executions.store.get(execution_id)
    if record["kind"] != "code_mode":
        return raw

    state = str(raw["state"])
    reason = str(raw.get("reason") or "") or None
    if state in {"accepted", "running"}:
        return raw
    if state == "lost":
        return _error_result(
            raw,
            code="lost",
            message="Code Mode Execution outcome is no longer observable.",
            reason=reason,
        )
    if state == "cancelled":
        return _error_result(
            raw,
            code="cancelled",
            message="Code Mode Execution was cancelled.",
            reason=reason,
        )
    if reason == "deadline_exceeded":
        return _error_result(
            raw,
            code="deadline_exceeded",
            message="Code Mode Execution reached its absolute work deadline.",
            reason=reason,
        )
    if reason == "launch_interrupted":
        return _error_result(
            raw,
            code="launch_interrupted",
            message="Code Mode Worker could not be launched.",
            reason=reason,
        )

    envelope = _parse_code_mode_envelope(raw)
    if envelope is None:
        return _error_result(
            raw,
            code="worker_protocol_error",
            message="Code Mode Worker produced no valid result envelope.",
            reason=reason,
        )
    if envelope["ok"] is True and state == "completed":
        return {
            "kind": "completed",
            "execution_id": execution_id,
            "label": str(raw["label"]),
            "result": envelope.get("result"),
        }

    error = envelope.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "execution_failed")
        message = str(error.get("message") or "Code Mode Execution failed.")
    else:
        code = "worker_protocol_error"
        message = "Code Mode Worker exited without a valid error envelope."
    return _error_result(raw, code=code, message=message, reason=reason)


def task_elapsed_seconds(task: dict[str, Any]) -> int:
    accepted = datetime.fromisoformat(str(task["accepted_at"]))
    finished_at = task.get("finished_at")
    end = datetime.fromisoformat(str(finished_at)) if finished_at else datetime.now(UTC)
    return max(0, int((end - accepted).total_seconds()))


def project_task(task: dict[str, Any]) -> dict[str, Any]:
    return {**task, "elapsed_seconds": task_elapsed_seconds(task)}


def list_projected_tasks(
    executions: ExecutionManager, *, limit: int | None = None
) -> list[dict[str, Any]]:
    return [project_task(task) for task in executions.tasks(limit=limit)]


_TASK_STATE_MARKERS = {
    "accepted": "◌",
    "running": "🧵",
    "completed": "✅",
    "failed": "❌",
    "cancelled": "⛔",
    "lost": "⚠️",
}


def format_task_elapsed(seconds: int) -> str:
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}:{secs:02d}"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def render_tracked_tasks(
    tasks: list[dict[str, Any]],
    *,
    limit: int = TRACKED_TASKS_LIMIT,
    max_bytes: int = TRACKED_TASKS_MAX_BYTES,
) -> str:
    lines = ["TrackedTasks"]
    for task in tasks[:limit]:
        state = str(task["state"])
        marker = _TASK_STATE_MARKERS.get(state, "•")
        parts = [
            str(task["label"]),
            f"{marker} {state}",
            format_task_elapsed(int(task["elapsed_seconds"])),
            str(task["execution_id"]),
        ]
        reason = str(task.get("reason") or "").strip()
        if reason:
            parts.append(reason)
        candidate = "\n".join([*lines, " · ".join(parts)])
        if len(candidate.encode()) > max_bytes:
            lines.append("…")
            break
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def projection_revision(tasks: list[dict[str, Any]]) -> str:
    visible = [
        {
            "execution_id": task["execution_id"],
            "label": task["label"],
            "state": task["state"],
            "reason": task.get("reason"),
            "finished_at": task.get("finished_at"),
        }
        for task in tasks
    ]
    encoded = json.dumps(
        visible,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def get_task(executions: ExecutionManager, execution_id: str) -> dict[str, Any]:
    task = project_task(executions.task(execution_id))
    state = str(task["state"])
    if state in {"accepted", "running"}:
        return {"task": task, "ready": False}
    if state == "lost":
        return {"task": task, "ready": False, "unavailable": True}
    try:
        result = read_execution_result(executions, execution_id)
    except ExecutionNotFoundError, FileNotFoundError:
        executions.store.mark_lost(execution_id, reason="retained_result_missing")
        task = project_task(executions.task(execution_id))
        return {"task": task, "ready": False, "unavailable": True}
    return {"task": task, "ready": True, "result": result}


def cancel_task(executions: ExecutionManager, execution_id: str) -> dict[str, Any]:
    executions.task(execution_id)
    executions.cancel(execution_id)
    return {"task": project_task(executions.task(execution_id))}


def dismiss_task(executions: ExecutionManager, execution_id: str) -> dict[str, Any]:
    task = executions.task(execution_id)
    if task["state"] not in TERMINAL_EXECUTION_STATES:
        raise ValueError("dismiss requires a terminal or lost Task")
    return executions.dismiss(execution_id)
