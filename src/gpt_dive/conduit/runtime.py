from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from ..job_manager import JobManager
from ..task_runtime import ack_task, collect_task, project_task, refresh_task
from ..task_store import TaskStore


class EventPublisher(Protocol):
    def publish(self, event: dict[str, object]) -> str: ...


class ConduitRuntime:
    """Conversation-driven surface over the shared GPT Dive Task registry."""

    def __init__(
        self,
        *,
        jobs: JobManager,
        task_store: TaskStore,
        publisher: EventPublisher,
    ) -> None:
        self.jobs = jobs
        self.task_store = task_store
        self.publisher = publisher

    def call(
        self,
        *,
        action: str,
        label: str | None = None,
        command: str | None = None,
        cwd: str | None = None,
        timeout: float = 600.0,
        task_id: str | None = None,
        session_id: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        action = action.strip().lower()
        if action == "start":
            if not command or not command.strip():
                raise ValueError("start requires command")
            clean_label = (label or "task").strip()
            if not clean_label:
                raise ValueError("start label must not be empty")
            if len(clean_label) > 80:
                raise ValueError("start label must be 80 characters or fewer")
            started = self.jobs.start(command, cwd=cwd, timeout=timeout)
            execution_id = str(started["job_id"])
            try:
                task = self.task_store.create(
                    execution_id=execution_id,
                    label=clean_label,
                )
            except Exception:
                self.jobs.cancel(execution_id)
                raise
            result: dict[str, Any] = {
                "task_id": str(task["task_id"]),
                "execution_id": execution_id,
                "label": clean_label,
                "status": self._map_state(str(task["state"])),
            }
        elif action == "sync":
            if text is None or not text.strip():
                raise ValueError("sync requires text")
            result = {"text": text}
        elif action == "collect":
            if not task_id or not task_id.strip():
                raise ValueError("collect requires task_id")
            result = self._collect(task_id.strip())
        elif action == "ack":
            if not task_id or not task_id.strip():
                raise ValueError("ack requires task_id")
            result = self._ack(task_id.strip())
        elif action == "emit":
            if text is None or not text.strip():
                raise ValueError("emit requires text")
            if session_id is not None:
                session_id = session_id.strip()
                if not session_id:
                    raise ValueError("emit session_id must not be empty")
            result = {"emitted": True}
        else:
            raise ValueError("action must be one of: start, sync, collect, ack, emit")

        tasks = self.snapshot()
        event: dict[str, object] = {
            "v": 1,
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "action": action,
            "result": self._event_result(action, result, text=text),
            "tasks": tasks,
        }
        if action == "emit" and session_id is not None:
            event["session_id"] = session_id
        self.publisher.publish(event)
        return {"result": result, "tasks": tasks}

    def snapshot(self) -> list[dict[str, object]]:
        tasks: list[dict[str, object]] = []
        for stored in self.task_store.list_tasks()[:8]:
            task = project_task(refresh_task(self.jobs, self.task_store, stored))
            row: dict[str, object] = {
                "id": str(task["task_id"]),
                "label": str(task["label"]),
                "status": self._map_state(str(task["state"])),
                "age_sec": int(task["elapsed_seconds"]),
            }
            status_label = task.get("status_label")
            if status_label:
                row["status_label"] = str(status_label)
            tasks.append(row)
        return tasks

    def _collect(self, task_id: str) -> dict[str, Any]:
        collected = collect_task(self.jobs, self.task_store, task_id)
        task = collected["task"]
        mapped = self._map_state(str(task["state"]))
        if not collected["ready"]:
            result: dict[str, Any] = {
                "task_id": task_id,
                "status": mapped,
                "ready": False,
            }
            if collected.get("unavailable"):
                result["unavailable"] = True
            return result

        result = dict(collected["result"])
        result["task_id"] = task_id
        result["status"] = mapped
        result["ready"] = True
        return result

    def _ack(self, task_id: str) -> dict[str, object]:
        try:
            acked = ack_task(self.jobs, self.task_store, task_id)
        except ValueError as exc:
            raise ValueError("ack requires a terminal or lost task") from exc
        return {
            "task_id": task_id,
            "status": self._map_state(str(acked["state"])),
            "acked": True,
        }

    @staticmethod
    def _map_state(state: str) -> str:
        if state == "working":
            return "running"
        if state == "completed":
            return "done"
        return state

    @staticmethod
    def _event_result(
        action: str, result: dict[str, Any], *, text: str | None
    ) -> dict[str, object]:
        if action == "emit":
            return {"text": text or ""}
        if action == "sync":
            return {"text": text or ""}
        if action == "start":
            return {
                "task_id": str(result["task_id"]),
                "execution_id": str(result["execution_id"]),
                "label": str(result["label"]),
                "status": str(result["status"]),
            }
        if action == "ack":
            return {
                "task_id": str(result["task_id"]),
                "status": str(result["status"]),
                "acked": bool(result["acked"]),
            }
        return {
            "task_id": str(result.get("task_id", "")),
            "status": str(result.get("status", "")),
            "ready": bool(result.get("ready", False)),
        }
