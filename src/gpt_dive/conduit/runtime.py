from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from ..execution_manager import ExecutionManager


class EventPublisher(Protocol):
    def publish(self, event: dict[str, object]) -> str: ...


class ConduitRuntime:
    """Conversation surface over Runtime-owned Executions and Tasks."""

    def __init__(
        self,
        *,
        executions: ExecutionManager,
        publisher: EventPublisher,
    ) -> None:
        self.executions = executions
        self.publisher = publisher

    def call(
        self,
        *,
        action: str,
        label: str | None = None,
        command: str | None = None,
        cwd: str | None = None,
        execution_id: str | None = None,
        session_id: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        action = action.strip().lower()
        if action == "start":
            result = self._start(label=label, command=command, cwd=cwd)
        elif action == "sync":
            if text is None or not text.strip():
                raise ValueError("sync requires text")
            result = {"text": text}
        elif action == "get":
            result = self._get(self._require_execution_id(action, execution_id))
        elif action == "cancel":
            result = self._cancel(self._require_execution_id(action, execution_id))
        elif action == "dismiss":
            result = self._dismiss(self._require_execution_id(action, execution_id))
        elif action == "emit":
            if text is None or not text.strip():
                raise ValueError("emit requires text")
            if session_id is not None:
                session_id = session_id.strip()
                if not session_id:
                    raise ValueError("emit session_id must not be empty")
            result = {"emitted": True}
        else:
            raise ValueError(
                "action must be one of: start, sync, get, cancel, dismiss, emit"
            )

        tasks = self.snapshot()
        event: dict[str, object] = {
            "v": 2,
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
        for projected in self.executions.tasks(limit=8):
            row: dict[str, object] = {
                "id": str(projected["execution_id"]),
                "label": str(projected["label"]),
                "status": self._map_state(str(projected["state"])),
                "age_sec": int(projected["elapsed_seconds"]),
            }
            reason = projected.get("reason")
            if reason:
                row["reason"] = str(reason)
            tasks.append(row)
        return tasks

    def _start(
        self,
        *,
        label: str | None,
        command: str | None,
        cwd: str | None,
    ) -> dict[str, Any]:
        if not command or not command.strip():
            raise ValueError("start requires command")
        clean_label = (label or "task").strip()
        if not clean_label:
            raise ValueError("start label must not be empty")
        if len(clean_label) > 80:
            raise ValueError("start label must be 80 characters or fewer")
        started = self.executions.start(
            command,
            label=clean_label,
            cwd=cwd,
            kind="conduit",
            publish=True,
        )
        return {
            "execution_id": str(started["execution_id"]),
            "label": clean_label,
            "status": self._map_state(str(started["state"])),
        }

    def _get(self, execution_id: str) -> dict[str, Any]:
        collected = self.executions.task_with_result(execution_id)
        task = collected["task"]
        result: dict[str, Any] = {
            "execution_id": execution_id,
            "status": self._map_state(str(task["state"])),
            "ready": bool(collected["ready"]),
        }
        if collected.get("unavailable"):
            result["unavailable"] = True
        if collected["ready"]:
            result["output"] = collected["result"]
        return result

    def _cancel(self, execution_id: str) -> dict[str, Any]:
        cancelled = self.executions.cancel_task(execution_id)["task"]
        return {
            "execution_id": execution_id,
            "status": self._map_state(str(cancelled["state"])),
            "cancel_requested": True,
        }

    def _dismiss(self, execution_id: str) -> dict[str, Any]:
        try:
            dismissed = self.executions.dismiss_task(execution_id)
        except ValueError as exc:
            raise ValueError("dismiss requires a terminal or lost Task") from exc
        return {
            "execution_id": execution_id,
            "status": self._map_state(str(dismissed["state"])),
            "dismissed": True,
        }

    @staticmethod
    def _require_execution_id(action: str, execution_id: str | None) -> str:
        if not execution_id or not execution_id.strip():
            raise ValueError(f"{action} requires execution_id")
        return execution_id.strip()

    @staticmethod
    def _map_state(state: str) -> str:
        return "done" if state == "completed" else state

    @staticmethod
    def _event_result(
        action: str, result: dict[str, Any], *, text: str | None
    ) -> dict[str, object]:
        if action in {"emit", "sync"}:
            return {"text": text or ""}
        if action == "start":
            return {
                "execution_id": str(result["execution_id"]),
                "label": str(result["label"]),
                "status": str(result["status"]),
            }
        event_result: dict[str, object] = {
            "execution_id": str(result["execution_id"]),
            "status": str(result["status"]),
        }
        for key in ("ready", "unavailable", "cancel_requested", "dismissed"):
            if key in result:
                event_result[key] = bool(result[key])
        return event_result
