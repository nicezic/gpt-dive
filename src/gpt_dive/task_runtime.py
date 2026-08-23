from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from .command_runtime import run_command
from .job_manager import JobManager, JobNotFoundError
from .task_store import TaskStore

CODE_MODE_WORKER_PROTOCOL = 2
_TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}


def _code_mode_request_dir(jobs: JobManager) -> Path:
    return jobs.root.parent / "code-mode-inputs"


def _code_mode_request_ref(jobs: JobManager, execution_id: str) -> Path:
    return jobs.root / execution_id / "code_mode_payload.ref"


def _cleanup_code_mode_request(jobs: JobManager, execution_id: str) -> None:
    ref = _code_mode_request_ref(jobs, execution_id)
    if not ref.is_file():
        return
    try:
        raw = ref.read_text().strip()
        request_path = Path(raw).resolve()
        request_path.relative_to(_code_mode_request_dir(jobs).resolve())
        request_path.unlink(missing_ok=True)
    except OSError, ValueError:
        pass
    finally:
        ref.unlink(missing_ok=True)


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


def _is_code_mode_execution(
    jobs: JobManager,
    execution_id: str,
    envelope: dict[str, Any] | None,
) -> bool:
    if _code_mode_request_ref(jobs, execution_id).is_file() or envelope is not None:
        return True
    meta_path = jobs.root / execution_id / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    command = str(meta.get("command") or "") if isinstance(meta, dict) else ""
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return any(
        parts[index : index + 2] == ["-m", "gpt_dive.code_mode_worker"]
        for index in range(len(parts) - 1)
    )


def _parse_code_mode_envelope(raw: dict[str, Any]) -> dict[str, Any] | None:
    stdout = str(raw.get("stdout") or "").strip()
    if not stdout:
        return None
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("v") != CODE_MODE_WORKER_PROTOCOL or not isinstance(envelope.get("ok"), bool):
        return None
    return envelope


def _normalize_code_mode_result(
    raw: dict[str, Any], execution_id: str, envelope: dict[str, Any]
) -> dict[str, Any]:
    if raw.get("status") == "cancelled":
        return _background_error(
            raw,
            code="background_cancelled",
            message="Background Code Mode job was cancelled.",
        )

    exit_code = raw.get("exit_code")
    if envelope.get("ok") is True and exit_code == 0:
        worker_result = envelope.get("result")
        if not isinstance(worker_result, dict):
            return _background_error(
                raw,
                code="worker_protocol_error",
                message="Background Code Mode success envelope has no object result.",
            )
        return {"job_id": execution_id, **worker_result}

    error = envelope.get("error")
    if isinstance(error, dict):
        error_code = str(error.get("code") or "background_execution_error")
        error_message = str(
            error.get("message") or "Background Code Mode execution failed."
        )
    else:
        error_code = "worker_protocol_error"
        error_message = "Background Code Mode worker exited without a valid error envelope."
    if envelope.get("ok") is True and exit_code != 0:
        error_code = "worker_protocol_error"
        error_message = "Worker reported success but exited with a non-zero status."
    return _background_error(raw, code=error_code, message=error_message)


def read_execution_result(jobs: JobManager, execution_id: str) -> dict[str, Any]:
    raw = jobs.result(execution_id)
    if not raw.get("ready"):
        return raw

    envelope = _parse_code_mode_envelope(raw)
    if not _is_code_mode_execution(jobs, execution_id, envelope):
        return raw

    _cleanup_code_mode_request(jobs, execution_id)
    if raw.get("status") == "cancelled":
        return _background_error(
            raw,
            code="background_cancelled",
            message="Background Code Mode job was cancelled.",
        )
    if envelope is None:
        return _background_error(
            raw,
            code="worker_protocol_error",
            message="Background Code Mode worker produced no valid result envelope.",
        )
    return _normalize_code_mode_result(raw, execution_id, envelope)


def _state_from_result(result: dict[str, Any]) -> str:
    error = result.get("error")
    if isinstance(error, dict):
        return "cancelled" if error.get("code") == "background_cancelled" else "failed"

    status = str(result.get("status") or "")
    if status == "cancelled":
        return "cancelled"
    if status == "failed":
        return "failed"

    exit_code = result.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return "failed"
    return "completed"


def task_status_label(task: dict[str, Any]) -> str | None:
    if task["state"] != "working":
        return None

    static_status = str(task.get("status") or "").strip()
    status_cmd = str(task.get("status_cmd") or "").strip()
    if status_cmd:
        try:
            probe = run_command(status_cmd, timeout=1.0)
        except OSError:
            probe = {"returncode": 1, "stdout": ""}
        if probe.get("returncode") == 0:
            stdout = " ".join(str(probe.get("stdout") or "").splitlines()).strip()
            if stdout:
                return stdout[:256]
    return static_status[:256] if static_status else None


def task_elapsed_seconds(task: dict[str, Any]) -> int:
    from datetime import UTC, datetime

    created = datetime.fromisoformat(str(task["created_at"]))
    if task["state"] == "working":
        end = datetime.now(UTC)
    else:
        end = datetime.fromisoformat(str(task["updated_at"]))
    return max(0, int((end - created).total_seconds()))


def project_task(task: dict[str, Any]) -> dict[str, Any]:
    projected = dict(task)
    projected["status_label"] = task_status_label(task)
    projected["elapsed_seconds"] = task_elapsed_seconds(task)
    return projected


_TASK_STATE_MARKERS = {
    "working": "🧵",
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


def render_tracked_tasks(tasks: list[dict[str, Any]], *, limit: int = 8) -> str:
    lines = ["TrackedTasks"]
    for task in tasks[:limit]:
        state = str(task["state"])
        marker = _TASK_STATE_MARKERS.get(state, "•")
        parts = [
            str(task["label"]),
            f"{marker} {state}",
            format_task_elapsed(int(task["elapsed_seconds"])),
        ]
        status_label = str(task.get("status_label") or "").strip()
        if status_label:
            parts.append(status_label)
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def refresh_task(
    jobs: JobManager, task_store: TaskStore, task: dict[str, Any]
) -> dict[str, Any]:
    if task["state"] == "lost":
        return task

    task_id = str(task["task_id"])
    execution_id = str(task["execution_id"])
    try:
        execution = jobs.status(execution_id)
    except JobNotFoundError:
        return task_store.update_state(task_id, "lost")

    if str(execution.get("status") or "") == "running":
        return task
    if task["state"] in _TERMINAL_TASK_STATES:
        return task

    try:
        result = read_execution_result(jobs, execution_id)
    except (JobNotFoundError, FileNotFoundError):
        return task_store.update_state(task_id, "lost")
    if not result.get("ready", True):
        return task
    return task_store.update_state(task_id, _state_from_result(result))


def collect_task(
    jobs: JobManager, task_store: TaskStore, task_id: str
) -> dict[str, Any]:
    task = refresh_task(jobs, task_store, task_store.get(task_id))
    if task["state"] == "working":
        return {"task": task, "ready": False}
    if task["state"] == "lost":
        return {"task": task, "ready": False, "unavailable": True}

    execution_id = str(task["execution_id"])
    try:
        result = read_execution_result(jobs, execution_id)
    except (JobNotFoundError, FileNotFoundError):
        task = task_store.update_state(str(task["task_id"]), "lost")
        return {"task": task, "ready": False, "unavailable": True}
    return {"task": task, "ready": True, "result": result}


def cancel_task(
    jobs: JobManager, task_store: TaskStore, task_id: str
) -> dict[str, Any]:
    task = refresh_task(jobs, task_store, task_store.get(task_id))
    if task["state"] != "working":
        return {"task": task}

    execution_id = str(task["execution_id"])
    try:
        jobs.cancel(execution_id)
    except JobNotFoundError:
        task = task_store.update_state(str(task["task_id"]), "lost")
        return {"task": task}
    return {"task": refresh_task(jobs, task_store, task_store.get(task_id))}


def ack_task(
    jobs: JobManager, task_store: TaskStore, task_id: str
) -> dict[str, Any]:
    task = refresh_task(jobs, task_store, task_store.get(task_id))
    if task["state"] == "working":
        raise ValueError("task_ack requires a terminal or lost Task")
    task_store.delete(task_id)
    return {"task_id": str(task["task_id"]), "state": str(task["state"]), "acked": True}
