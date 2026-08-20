from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from ..job_manager import JobManager, JobNotFoundError


class EventPublisher(Protocol):
    def publish(self, event: dict[str, object]) -> str: ...


class ConduitRuntime:
    """Conversation-driven task runtime backed by GPT Dive JobManager."""

    def __init__(self, *, jobs: JobManager, publisher: EventPublisher) -> None:
        self.jobs = jobs
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
            task_id_value = str(started["job_id"])
            self._write_task_meta(task_id_value, clean_label)
            result: dict[str, Any] = {
                "task_id": task_id_value,
                "label": clean_label,
                "status": self._map_status(str(started["status"])),
            }
        elif action == "sync":
            if text is None or not text.strip():
                raise ValueError("sync requires text")
            result = {"text": text}
        elif action == "collect":
            if not task_id or not task_id.strip():
                raise ValueError("collect requires task_id")
            result = self.jobs.result(task_id.strip())
            result["status"] = self._map_status(str(result["status"]))
        elif action == "ack":
            if not task_id or not task_id.strip():
                raise ValueError("ack requires task_id")
            result = self._ack_task(task_id.strip())
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
        if not self.jobs.root.is_dir():
            return tasks
        for job_dir in sorted(self.jobs.root.iterdir()):
            meta_path = job_dir / "conduit.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("acked_at"):
                    continue
                status = self.jobs.status(job_dir.name)
            except (OSError, ValueError, json.JSONDecodeError, JobNotFoundError):
                continue
            created = datetime.fromisoformat(str(meta["created_at"]))
            age_sec = max(0, int((datetime.now(UTC) - created).total_seconds()))
            tasks.append(
                {
                    "id": job_dir.name,
                    "label": str(meta["label"]),
                    "status": self._map_status(str(status["status"])),
                    "age_sec": age_sec,
                }
            )
        return tasks

    def _ack_task(self, task_id: str) -> dict[str, object]:
        status = self.jobs.status(task_id)
        mapped_status = self._map_status(str(status["status"]))
        if mapped_status not in {"done", "failed", "cancelled"}:
            raise ValueError("ack requires a terminal task")

        meta_path = self.jobs.root / task_id / "conduit.json"
        if not meta_path.is_file():
            raise JobNotFoundError(task_id)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["acked_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return {"task_id": task_id, "status": mapped_status, "acked": True}

    def _write_task_meta(self, task_id: str, label: str) -> None:
        job_dir = self.jobs.root / task_id
        payload = {
            "label": label,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        (job_dir / "conduit.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    @staticmethod
    def _map_status(status: str) -> str:
        if status == "completed":
            return "done"
        return status

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
            "task_id": str(result.get("job_id", "")),
            "status": str(result.get("status", "")),
            "ready": bool(result.get("ready", False)),
        }
