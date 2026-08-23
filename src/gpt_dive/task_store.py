from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TASK_STATES = frozenset({"working", "completed", "failed", "cancelled", "lost"})


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TaskStore:
    """Small durable registry for Web SOL task awareness."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".local" / "state" / "gpt-dive" / "tasks.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    state TEXT NOT NULL,
                    status_cmd TEXT,
                    status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create(
        self,
        *,
        execution_id: str,
        label: str,
        state: str = "working",
        status_cmd: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        clean_execution_id = execution_id.strip()
        clean_label = label.strip()
        if not clean_execution_id:
            raise ValueError("execution_id must not be empty")
        if not clean_label:
            raise ValueError("label must not be empty")
        if len(clean_label) > 80:
            raise ValueError("label must be 80 characters or fewer")
        if state not in TASK_STATES:
            raise ValueError(f"unsupported task state: {state}")

        task_id = uuid.uuid4().hex
        now = _iso_now()
        record: dict[str, Any] = {
            "task_id": task_id,
            "execution_id": clean_execution_id,
            "label": clean_label,
            "state": state,
            "status_cmd": status_cmd,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, execution_id, label, state, status_cmd, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["task_id"],
                    record["execution_id"],
                    record["label"],
                    record["state"],
                    record["status_cmd"],
                    record["status"],
                    record["created_at"],
                    record["updated_at"],
                ),
            )
        return record

    def list_tasks(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT task_id, execution_id, label, state, status_cmd, status, created_at, updated_at
                FROM tasks
                ORDER BY created_at, task_id
                """
            ).fetchall()
        return [dict(row) for row in rows]
