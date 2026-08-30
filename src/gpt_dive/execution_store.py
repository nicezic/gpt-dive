from __future__ import annotations

import re
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

EXECUTION_ID_PATTERN = r"^[A-Za-z0-9_-]{6}$"
EXECUTION_ID_REGEX = re.compile(EXECUTION_ID_PATTERN)


def generate_execution_id() -> str:
    token = secrets.token_urlsafe(4)
    while token.startswith("-"):
        token = secrets.token_urlsafe(4)
    return token


def is_valid_execution_id(identifier: str) -> bool:
    return bool(EXECUTION_ID_REGEX.fullmatch(identifier))


EXECUTION_STATES = frozenset(
    {"accepted", "running", "completed", "failed", "cancelled", "lost"}
)
TERMINAL_EXECUTION_STATES = frozenset({"completed", "failed", "cancelled", "lost"})


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_time(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ExecutionStore:
    """SQLite control-plane authority for Executions and Task awareness."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (
            Path.home() / ".local" / "state" / "gpt-dive" / "runtime-v2.sqlite3"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._ensure_schema()
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT,
                    cwd TEXT,
                    backend TEXT NOT NULL,
                    systemd_unit TEXT,
                    worker_pid INTEGER,
                    worker_start_ticks INTEGER,
                    child_pid INTEGER,
                    child_start_ticks INTEGER,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    work_timeout_seconds REAL NOT NULL,
                    cleanup_timeout_seconds REAL NOT NULL,
                    work_deadline_at TEXT NOT NULL,
                    absolute_deadline_at TEXT NOT NULL,
                    request_path TEXT NOT NULL,
                    artifact_dir TEXT NOT NULL,
                    stdout_path TEXT NOT NULL,
                    stderr_path TEXT NOT NULL,
                    outcome_path TEXT NOT NULL,
                    exit_code INTEGER,
                    accepted_at TEXT NOT NULL,
                    claimed_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    published_at TEXT,
                    dismissed_at TEXT,
                    CHECK (state IN (
                        'accepted', 'running', 'completed',
                        'failed', 'cancelled', 'lost'
                    )),
                    CHECK (cancel_requested IN (0, 1))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS executions_task_projection
                ON executions (published_at, dismissed_at, accepted_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS executions_retention
                ON executions (state, updated_at)
                """
            )
            connection.execute(
                "DELETE FROM executions WHERE length(execution_id) != 6"
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["cancel_requested"] = bool(record["cancel_requested"])
        return record

    @staticmethod
    def _validate_label(label: str) -> str:
        clean = label.strip()
        if not clean:
            raise ValueError("label must not be empty")
        if len(clean) > 80:
            raise ValueError("label must be 80 characters or fewer")
        return clean

    def create(
        self,
        *,
        kind: str,
        label: str,
        cwd: str | None,
        backend: str,
        systemd_unit: str | None,
        work_timeout_seconds: float,
        cleanup_timeout_seconds: float,
        request_path: Path,
        artifact_dir: Path,
        stdout_path: Path,
        stderr_path: Path,
        outcome_path: Path,
        publish: bool = False,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        clean_kind = kind.strip()
        if not clean_kind:
            raise ValueError("kind must not be empty")
        clean_label = self._validate_label(label)
        if backend not in {"systemd", "popen"}:
            raise ValueError(f"unsupported execution backend: {backend}")
        if work_timeout_seconds <= 0:
            raise ValueError("work_timeout_seconds must be greater than 0")
        if cleanup_timeout_seconds <= 0:
            raise ValueError("cleanup_timeout_seconds must be greater than 0")

        identifier = execution_id or generate_execution_id()
        if not is_valid_execution_id(identifier):
            raise ValueError(
                "execution_id must be a 6-character URL-safe Base64 string"
            )
        now = utc_now()
        accepted_at = iso_time(now)
        work_deadline_at = iso_time(now + timedelta(seconds=work_timeout_seconds))
        absolute_deadline_at = iso_time(
            now + timedelta(seconds=work_timeout_seconds + cleanup_timeout_seconds)
        )
        published_at = accepted_at if publish else None
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO executions (
                    execution_id, kind, label, state, cwd, backend, systemd_unit,
                    work_timeout_seconds, cleanup_timeout_seconds,
                    work_deadline_at, absolute_deadline_at,
                    request_path, artifact_dir, stdout_path, stderr_path,
                    outcome_path,
                    accepted_at, updated_at, published_at
                ) VALUES (
                    ?, ?, ?, 'accepted', ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    identifier,
                    clean_kind,
                    clean_label,
                    cwd,
                    backend,
                    systemd_unit,
                    work_timeout_seconds,
                    cleanup_timeout_seconds,
                    work_deadline_at,
                    absolute_deadline_at,
                    str(request_path),
                    str(artifact_dir),
                    str(stdout_path),
                    str(stderr_path),
                    str(outcome_path),
                    accepted_at,
                    accepted_at,
                    published_at,
                ),
            )
        return self.get(identifier)

    def get(self, execution_id: str) -> dict[str, Any]:
        clean = execution_id.strip()
        if not clean:
            raise ValueError("execution_id must not be empty")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_id = ?", (clean,)
            ).fetchone()
        if row is None:
            raise KeyError(clean)
        return self._record(row)

    def get_task(self, execution_id: str) -> dict[str, Any]:
        record = self.get(execution_id)
        if record["published_at"] is None or record["dismissed_at"] is not None:
            raise KeyError(execution_id.strip())
        return record

    def list_executions(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM executions ORDER BY accepted_at, execution_id"
            ).fetchall()
        return [self._record(row) for row in rows]

    def list_tasks(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is not None and limit <= 0:
            return []
        limit_clause = " LIMIT ?" if limit is not None else ""
        parameters: tuple[int, ...] = (limit,) if limit is not None else ()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM executions
                WHERE published_at IS NOT NULL AND dismissed_at IS NULL
                  AND length(execution_id) = 6
                ORDER BY
                    CASE WHEN state IN ('accepted', 'running') THEN 0 ELSE 1 END,
                    published_at DESC,
                    execution_id
                {limit_clause}
                """,
                parameters,
            ).fetchall()
        return [self._record(row) for row in rows]

    def claim(
        self,
        execution_id: str,
        *,
        worker_pid: int,
        worker_start_ticks: int | None,
    ) -> bool:
        now = iso_time()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE executions
                SET state = 'running', worker_pid = ?, worker_start_ticks = ?,
                    claimed_at = ?, updated_at = ?
                WHERE execution_id = ?
                  AND state = 'accepted'
                  AND cancel_requested = 0
                """,
                (worker_pid, worker_start_ticks, now, now, execution_id),
            )
        return cursor.rowcount == 1

    def set_child(
        self,
        execution_id: str,
        *,
        child_pid: int,
        child_start_ticks: int | None,
    ) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE executions
                SET child_pid = ?, child_start_ticks = ?, updated_at = ?
                WHERE execution_id = ? AND state = 'running'
                """,
                (child_pid, child_start_ticks, iso_time(), execution_id),
            )
        return cursor.rowcount == 1

    def clear_request_path(self, execution_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE executions SET request_path = '', updated_at = ? WHERE execution_id = ?",
                (iso_time(), execution_id),
            )

    def publish(self, execution_id: str) -> dict[str, Any]:
        now = iso_time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE executions
                SET published_at = COALESCE(published_at, ?), updated_at = ?
                WHERE execution_id = ? AND dismissed_at IS NULL
                """,
                (now, now, execution_id),
            )
        return self.get_task(execution_id)

    def dismiss(self, execution_id: str) -> dict[str, Any]:
        task = self.get_task(execution_id)
        if task["state"] not in TERMINAL_EXECUTION_STATES:
            raise ValueError("dismiss requires a terminal or lost Task")
        now = iso_time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE executions
                SET dismissed_at = ?, updated_at = ?
                WHERE execution_id = ? AND dismissed_at IS NULL
                """,
                (now, now, execution_id),
            )
        return self.get(execution_id)

    def request_cancel(self, execution_id: str) -> dict[str, Any]:
        current = self.get(execution_id)
        if current["state"] in TERMINAL_EXECUTION_STATES:
            return current
        now = iso_time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE executions
                SET cancel_requested = 1,
                    state = CASE WHEN state = 'accepted' THEN 'cancelled' ELSE state END,
                    reason = CASE WHEN state = 'accepted' THEN 'cancelled' ELSE reason END,
                    finished_at = CASE WHEN state = 'accepted' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE execution_id = ?
                  AND state IN ('accepted', 'running')
                """,
                (now, now, execution_id),
            )
        return self.get(execution_id)

    def _transition_to_terminal(
        self,
        execution_id: str,
        *,
        entry_states: tuple[str, ...],
        terminal_state: str,
        reason: str | None,
        exit_code: int | None = None,
        include_exit_code: bool = False,
        honor_cancel_request: bool = True,
    ) -> dict[str, Any]:
        now = iso_time()
        if honor_cancel_request:
            state_sql = "CASE WHEN cancel_requested = 1 THEN ? ELSE ? END"
            reason_sql = "CASE WHEN cancel_requested = 1 THEN ? ELSE ? END"
            state_vals = ("cancelled", terminal_state)
            reason_vals = ("cancelled", reason)
        else:
            state_sql = "?"
            reason_sql = "?"
            state_vals = (terminal_state,)
            reason_vals = (reason,)

        exit_code_sql = "exit_code = ?, " if include_exit_code else ""
        exit_code_vals = (exit_code,) if include_exit_code else ()
        entry_placeholders = ", ".join("?" for _ in entry_states)

        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"""
                UPDATE executions
                SET state = {state_sql},
                    reason = {reason_sql},
                    {exit_code_sql}finished_at = COALESCE(finished_at, ?),
                    updated_at = ?
                WHERE execution_id = ? AND state IN ({entry_placeholders})
                """,
                (
                    *state_vals,
                    *reason_vals,
                    *exit_code_vals,
                    now,
                    now,
                    execution_id,
                    *entry_states,
                ),
            )
        return self.get(execution_id)

    def finish(
        self,
        execution_id: str,
        *,
        exit_code: int | None,
        reason: str | None = None,
        deadline_exceeded: bool = False,
    ) -> dict[str, Any]:
        current = self.get(execution_id)
        if current["state"] in TERMINAL_EXECUTION_STATES:
            return current
        if current["state"] != "running":
            raise ValueError(f"cannot finish execution in state {current['state']!r}")

        if deadline_exceeded:
            terminal_state = "failed"
            terminal_reason = "deadline_exceeded"
        elif exit_code == 0:
            terminal_state = "completed"
            terminal_reason = None
        else:
            terminal_state = "failed"
            terminal_reason = reason or (
                f"exit_code_{exit_code}" if exit_code is not None else "worker_failed"
            )
        return self._transition_to_terminal(
            execution_id,
            entry_states=("running",),
            terminal_state=terminal_state,
            reason=terminal_reason,
            exit_code=exit_code,
            include_exit_code=True,
        )

    def fail_accepted(self, execution_id: str, *, reason: str) -> dict[str, Any]:
        return self._transition_to_terminal(
            execution_id,
            entry_states=("accepted",),
            terminal_state="failed",
            reason=reason,
        )

    def fail_running(self, execution_id: str, *, reason: str) -> dict[str, Any]:
        return self._transition_to_terminal(
            execution_id,
            entry_states=("running",),
            terminal_state="failed",
            reason=reason,
        )

    def mark_lost(self, execution_id: str, *, reason: str) -> dict[str, Any]:
        current = self.get(execution_id)
        if current["state"] == "accepted":
            raise ValueError("an unclaimed accepted Execution is failed, not lost")
        if current["state"] == "lost":
            return current
        return self._transition_to_terminal(
            execution_id,
            entry_states=("running", "completed", "failed", "cancelled"),
            terminal_state="lost",
            reason=reason,
            honor_cancel_request=False,
        )

    def delete(self, execution_id: str) -> None:
        self.get(execution_id)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM executions WHERE execution_id = ?", (execution_id,)
            )
