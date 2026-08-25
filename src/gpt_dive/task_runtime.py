from __future__ import annotations

import json
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, NamedTuple

from .command_runtime import run_command
from .execution_manager import ExecutionManager, ExecutionNotFoundError
from .task_store import TaskStore
from .worker_subprocess import stderr_tail

CODE_MODE_WORKER_PROTOCOL = 2
_TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}


class TaskRuntime(NamedTuple):
    """Paired handles for Task-aware execution bookkeeping.

    Every Task-domain operation needs both halves; bundling them removes
    the position where the pair could be split or reordered at call sites.
    """

    executions: ExecutionManager
    task_store: TaskStore


def code_mode_request_dir(executions: ExecutionManager) -> Path:
    return executions.root.parent / "code-mode-inputs"


def code_mode_request_ref(executions: ExecutionManager, execution_id: str) -> Path:
    return executions.root / execution_id / "code_mode_payload.ref"


def cleanup_code_mode_request(executions: ExecutionManager, execution_id: str) -> None:
    ref = code_mode_request_ref(executions, execution_id)
    if not ref.is_file():
        return
    try:
        raw = ref.read_text().strip()
        request_path = Path(raw).resolve()
        request_path.relative_to(code_mode_request_dir(executions).resolve())
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
        "execution_id": raw.get("execution_id"),
        "status": raw.get("status"),
        "exit_code": raw.get("exit_code"),
        "error": {"code": code, "message": message},
    }
    stderr = str(raw.get("stderr") or "").strip()
    if stderr:
        result["worker_stderr"] = stderr_tail(stderr)
    return result


def _is_code_mode_execution(
    executions: ExecutionManager,
    execution_id: str,
    envelope: dict[str, Any] | None,
) -> bool:
    if (
        code_mode_request_ref(executions, execution_id).is_file()
        or envelope is not None
    ):
        return True
    meta_path = executions.root / execution_id / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except OSError, ValueError, json.JSONDecodeError:
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
    if envelope.get("v") != CODE_MODE_WORKER_PROTOCOL or not isinstance(
        envelope.get("ok"), bool
    ):
        return None
    return envelope


def _normalize_code_mode_result(
    raw: dict[str, Any], execution_id: str, envelope: dict[str, Any]
) -> dict[str, Any]:
    if raw.get("status") == "cancelled":
        return _background_error(
            raw,
            code="background_cancelled",
            message="Background Code Mode execution was cancelled.",
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
        return {"execution_id": execution_id, **worker_result}

    error = envelope.get("error")
    if isinstance(error, dict):
        error_code = str(error.get("code") or "background_execution_error")
        error_message = str(
            error.get("message") or "Background Code Mode execution failed."
        )
    else:
        error_code = "worker_protocol_error"
        error_message = (
            "Background Code Mode worker exited without a valid error envelope."
        )
    if envelope.get("ok") is True and exit_code != 0:
        error_code = "worker_protocol_error"
        error_message = "Worker reported success but exited with a non-zero status."
    return _background_error(raw, code=error_code, message=error_message)


def read_execution_result(
    executions: ExecutionManager, execution_id: str
) -> dict[str, Any]:
    raw = executions.result(execution_id)
    if not raw.get("ready"):
        return raw

    envelope = _parse_code_mode_envelope(raw)
    if not _is_code_mode_execution(executions, execution_id, envelope):
        return raw

    cleanup_code_mode_request(executions, execution_id)
    if raw.get("status") == "cancelled":
        return _background_error(
            raw,
            code="background_cancelled",
            message="Background Code Mode execution was cancelled.",
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


_UNSET_STATUS_LABEL = object()


def project_task(
    task: dict[str, Any], *, status_label: Any = _UNSET_STATUS_LABEL
) -> dict[str, Any]:
    projected = dict(task)
    projected["status_label"] = (
        task_status_label(task) if status_label is _UNSET_STATUS_LABEL else status_label
    )
    projected["elapsed_seconds"] = task_elapsed_seconds(task)
    return projected


def probe_status_labels(tasks: list[dict[str, Any]]) -> dict[str, str | None]:
    """Run bounded status_cmd probes concurrently so wall time stays near one probe.

    Only working Tasks with a status_cmd need a probe; every other projected
    row keeps its static fallback (or no decoration). Returns a map keyed by
    task_id for tasks that were probed.
    """
    candidates = [task for task in tasks if task["state"] == "working"]
    if not candidates:
        return {}
    pool = _probe_pool()
    futures = {
        str(task["task_id"]): pool.submit(task_status_label, task)
        for task in candidates
    }
    return {task_id: future.result() for task_id, future in futures.items()}


_PROBE_POOL: ThreadPoolExecutor | None = None
_PROBE_POOL_LOCK = threading.Lock()


def _probe_pool() -> ThreadPoolExecutor:
    """Lazily build and reuse one shared probe pool.

    Snapshots run on every task_list / @c call; constructing a fresh
    ThreadPoolExecutor per invocation churned threads for no benefit.
    The pool is shared across concurrent snapshots: probes queue behind
    in-flight ones but stay bounded by the 1s run_command timeout.
    """
    global _PROBE_POOL
    with _PROBE_POOL_LOCK:
        if _PROBE_POOL is None:
            _PROBE_POOL = ThreadPoolExecutor(
                max_workers=8, thread_name_prefix="status-probe"
            )
        return _PROBE_POOL


def list_projected_tasks(
    rt: TaskRuntime,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Refresh every stored Task and return the projected awareness rows."""
    tasks = rt.task_store.list_tasks()
    if limit is not None:
        tasks = tasks[:limit]
    refreshed = [refresh_task(rt, task) for task in tasks]
    labels = probe_status_labels(refreshed)
    return [
        project_task(task, status_label=labels.get(str(task["task_id"])))
        for task in refreshed
    ]


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


def refresh_task(rt: TaskRuntime, task: dict[str, Any]) -> dict[str, Any]:
    if task["state"] == "lost":
        return task

    task_id = str(task["task_id"])
    execution_id = str(task["execution_id"])
    try:
        execution = rt.executions.status(execution_id)
    except ExecutionNotFoundError:
        return rt.task_store.update_state(task_id, "lost")

    if str(execution.get("status") or "") == "running":
        return task
    if task["state"] in _TERMINAL_TASK_STATES:
        return task

    try:
        result = read_execution_result(rt.executions, execution_id)
    except ExecutionNotFoundError, FileNotFoundError:
        return rt.task_store.update_state(task_id, "lost")
    if not result.get("ready", True):
        return task
    return rt.task_store.update_state(task_id, _state_from_result(result))


def collect_task(rt: TaskRuntime, task_id: str) -> dict[str, Any]:
    task = refresh_task(rt, rt.task_store.get(task_id))
    if task["state"] == "working":
        return {"task": task, "ready": False}
    if task["state"] == "lost":
        return {"task": task, "ready": False, "unavailable": True}

    execution_id = str(task["execution_id"])
    try:
        result = read_execution_result(rt.executions, execution_id)
    except ExecutionNotFoundError, FileNotFoundError:
        task = rt.task_store.update_state(str(task["task_id"]), "lost")
        return {"task": task, "ready": False, "unavailable": True}
    return {"task": task, "ready": True, "result": result}


def cancel_task(rt: TaskRuntime, task_id: str) -> dict[str, Any]:
    task = refresh_task(rt, rt.task_store.get(task_id))
    if task["state"] != "working":
        return {"task": task}

    execution_id = str(task["execution_id"])
    try:
        rt.executions.cancel(execution_id)
    except ExecutionNotFoundError:
        task = rt.task_store.update_state(str(task["task_id"]), "lost")
        return {"task": task}
    return {"task": refresh_task(rt, rt.task_store.get(task_id))}


def ack_task(rt: TaskRuntime, task_id: str) -> dict[str, Any]:
    task = refresh_task(rt, rt.task_store.get(task_id))
    if task["state"] == "working":
        raise ValueError("task_ack requires a terminal or lost Task")
    rt.task_store.delete(task_id)
    return {"task_id": str(task["task_id"]), "state": str(task["state"]), "acked": True}
