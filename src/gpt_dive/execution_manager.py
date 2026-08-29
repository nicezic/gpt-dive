from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .code_mode_protocol import CODE_MODE_WORKER_PROTOCOL
from .execution_store import (
    TERMINAL_EXECUTION_STATES,
    ExecutionStore,
    generate_execution_id,
    is_valid_execution_id,
    parse_time,
    utc_now,
)
from .process_identity import process_matches

RETENTION_DAYS = 5
POLL_INTERVAL_MS = 1000
DEFAULT_WORK_TIMEOUT_SECONDS = 43190.0
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 10.0
_ACCEPTED_LAUNCH_GRACE_SECONDS = 30.0
_EXIT_MARKER_GRACE_SECONDS = 0.25
_CLEANUP_INTERVAL_SECONDS = 3600.0


class ExecutionNotFoundError(KeyError):
    pass


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


def _code_mode_error_result(
    raw: dict[str, Any],
    *,
    code: str,
    message: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "error",
        "execution_id": str(raw["execution_id"]),
        "code": code,
        "message": message,
    }


def task_elapsed_seconds(record: dict[str, Any]) -> int:
    accepted_raw = record.get("accepted_at")
    if not accepted_raw:
        return 0
    accepted = datetime.fromisoformat(str(accepted_raw))
    finished_at = record.get("finished_at")
    end = datetime.fromisoformat(str(finished_at)) if finished_at else datetime.now(UTC)
    return max(0, int((end - accepted).total_seconds()))


class ExecutionManager:
    """Durable process lifecycle with SQLite as its control-plane authority."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        store: ExecutionStore | None = None,
        retention_days: int = RETENTION_DAYS,
        work_timeout_seconds: float = DEFAULT_WORK_TIMEOUT_SECONDS,
        cleanup_timeout_seconds: float = DEFAULT_CLEANUP_TIMEOUT_SECONDS,
    ) -> None:
        self.root = root or (
            Path.home() / ".local" / "state" / "gpt-dive" / "executions-v2"
        )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store = store or ExecutionStore(self.root.parent / "runtime-v2.sqlite3")
        self.retention_days = retention_days
        self.work_timeout_seconds = work_timeout_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        if self.work_timeout_seconds <= 0:
            raise ValueError("work_timeout_seconds must be greater than 0")
        if self.cleanup_timeout_seconds <= 0:
            raise ValueError("cleanup_timeout_seconds must be greater than 0")
        self._lock = threading.RLock()
        self._next_cleanup_monotonic = 0.0
        self._systemd_available = self._detect_user_systemd()
        self.recover()

    def start(
        self,
        command: str,
        *,
        label: str,
        cwd: str | None = None,
        kind: str = "shell",
        publish: bool = False,
        execution_id: str | None = None,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not command.strip():
            raise ValueError("command must not be empty")
        run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else None
        if run_cwd is not None and not Path(run_cwd).is_dir():
            raise ValueError(f"cwd does not exist or is not a directory: {run_cwd}")

        with self._lock:
            self._maybe_cleanup()
            identifier = execution_id or generate_execution_id()
            if not is_valid_execution_id(identifier):
                raise ValueError(
                    "execution_id must be a 6-character URL-safe Base64 string"
                )
            execution_dir = self.root / identifier
            execution_dir.mkdir(mode=0o700)
            stdout_path = execution_dir / "stdout.log"
            stderr_path = execution_dir / "stderr.log"
            outcome_path = execution_dir / "outcome.json"
            request_path = execution_dir / "request.json"
            input_path = execution_dir / "input.json"
            request = {"v": 1, "command": command, "cwd": run_cwd}
            try:
                self._write_json_atomic(request_path, request, mode=0o600)
                if input_payload is not None:
                    self._write_json_atomic(input_path, input_payload, mode=0o600)

                backend = "systemd" if self._systemd_available else "popen"
                unit = (
                    f"gpt-dive-execution-{identifier}.service"
                    if backend == "systemd"
                    else None
                )
                self.store.create(
                    execution_id=identifier,
                    kind=kind,
                    label=label,
                    cwd=run_cwd,
                    backend=backend,
                    systemd_unit=unit,
                    work_timeout_seconds=self.work_timeout_seconds,
                    cleanup_timeout_seconds=self.cleanup_timeout_seconds,
                    request_path=request_path,
                    artifact_dir=execution_dir,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    outcome_path=outcome_path,
                    publish=publish,
                )
            except Exception:
                shutil.rmtree(execution_dir, ignore_errors=True)
                raise

            try:
                # Atomic sequence: journal row committed above, spawn must follow
                # or fail_accepted rolls it back; keep both visible in one place.
                worker_command = [
                    sys.executable,
                    "-m",
                    "gpt_dive.execution_worker",
                    f"--store={self.store.path}",
                    f"--execution={identifier}",
                ]
                if backend == "systemd":
                    assert unit is not None
                    absolute_seconds = (
                        self.work_timeout_seconds + self.cleanup_timeout_seconds
                    )
                    launched = subprocess.run(
                        [
                            "systemd-run",
                            "--user",
                            "--quiet",
                            "--collect",
                            f"--unit={unit.removesuffix('.service')}",
                            "--property=KillMode=control-group",
                            f"--property=TimeoutStopSec={self.cleanup_timeout_seconds}s",
                            f"--property=RuntimeMaxSec={absolute_seconds}s",
                            *worker_command,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5.0,
                        check=False,
                    )
                    if launched.returncode != 0:
                        raise RuntimeError(
                            "systemd-run failed: "
                            f"{launched.stderr.strip() or launched.stdout.strip()}"
                        )
                else:
                    subprocess.Popen(
                        worker_command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
            except Exception:
                record = self.store.fail_accepted(
                    identifier, reason="launch_interrupted"
                )
                if record["claimed_at"] is not None:
                    return self._public_status(record)
                request_path.unlink(missing_ok=True)
                input_path.unlink(missing_ok=True)
                with contextlib.suppress(Exception):
                    self.store.clear_request_path(identifier)
                raise
            return self._public_status(self.store.get(identifier))

    def status(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._maybe_cleanup()
            record = self._refresh(self._get(execution_id))
            return self._public_status(record)

    def result(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._maybe_cleanup()
            record = self._refresh(self._get(execution_id))
            payload = self._public_status(record)
            state = str(record["state"])
            if state in {"accepted", "running"}:
                payload["ready"] = False
                return payload
            if state == "lost":
                payload["ready"] = False
                payload["unavailable"] = True
                return self._code_mode_projection(record, payload)

            stdout_path = Path(str(record["stdout_path"]))
            stderr_path = Path(str(record["stderr_path"]))
            if not stdout_path.is_file() or not stderr_path.is_file():
                known_without_artifacts = (
                    record["claimed_at"] is None or state == "cancelled"
                )
                if known_without_artifacts:
                    payload.update({"ready": True, "stdout": "", "stderr": ""})
                    return self._code_mode_projection(record, payload)
                record = self.store.mark_lost(
                    execution_id, reason="retained_result_missing"
                )
                payload = self._public_status(record)
                payload.update({"ready": False, "unavailable": True})
                return self._code_mode_projection(record, payload)
            payload["ready"] = True
            payload["stdout"] = stdout_path.read_text(errors="replace")
            payload["stderr"] = stderr_path.read_text(errors="replace")
            return self._code_mode_projection(record, payload)

    @staticmethod
    def _code_mode_projection(
        record: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Normalize Code Mode terminal results into structured envelopes."""
        if record["kind"] != "code_mode":
            return payload
        state = str(payload["state"])
        reason = str(payload.get("reason") or "") or None
        if state == "lost":
            return _code_mode_error_result(
                payload,
                code="lost",
                message="Code Mode Execution outcome is no longer observable.",
                reason=reason,
            )
        if state == "cancelled":
            return _code_mode_error_result(
                payload,
                code="cancelled",
                message="Code Mode Execution was cancelled.",
                reason=reason,
            )
        if reason == "deadline_exceeded":
            return _code_mode_error_result(
                payload,
                code="deadline_exceeded",
                message="Code Mode Execution reached its absolute work deadline.",
                reason=reason,
            )
        if reason == "launch_interrupted":
            return _code_mode_error_result(
                payload,
                code="launch_interrupted",
                message="Code Mode Worker could not be launched.",
                reason=reason,
            )

        envelope = _parse_code_mode_envelope(payload)
        if envelope is None:
            return _code_mode_error_result(
                payload,
                code="worker_protocol_error",
                message="Code Mode Worker produced no valid result envelope.",
                reason=reason,
            )
        if envelope["ok"] is True and state == "completed":
            return {
                "kind": "completed",
                "execution_id": str(payload["execution_id"]),
                "label": str(payload["label"]),
                "result": envelope.get("result"),
            }

        error = envelope.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "execution_failed")
            message = str(error.get("message") or "Code Mode Execution failed.")
        else:
            code = "worker_protocol_error"
            message = "Code Mode Worker exited without a valid error envelope."
        return _code_mode_error_result(
            payload, code=code, message=message, reason=reason
        )

    def publish(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._maybe_cleanup()
            record = self.store.publish(execution_id)
            return self._public_task(record)

    def dismiss(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._maybe_cleanup()
            record = self.store.dismiss(execution_id)
            return {
                "execution_id": execution_id,
                "state": record["state"],
                "dismissed": True,
            }

    def cancel(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._maybe_cleanup()
            record = self.store.request_cancel(execution_id)
            self._signal_execution(record)
            deadline = time.monotonic() + self.cleanup_timeout_seconds
            while (
                record["state"] not in TERMINAL_EXECUTION_STATES
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
                record = self._refresh(self._get(execution_id))
            return self._public_status(record)

    def task(self, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._maybe_cleanup()
            try:
                record = self.store.get_task(execution_id)
            except KeyError as exc:
                raise ExecutionNotFoundError(execution_id) from exc
            record = self._refresh(record)
            return self._public_task(record)

    def tasks(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._maybe_cleanup()
            records = self.store.list_tasks(limit=limit)
            refreshed = [self._refresh(record) for record in records]
            return [self._public_task(record) for record in refreshed]

    def recover(self) -> None:
        with self._lock:
            for record in self.store.list_executions():
                if record["state"] in TERMINAL_EXECUTION_STATES:
                    continue
                with contextlib.suppress(Exception):
                    self._refresh(record)
            self.cleanup()

    def cleanup(self) -> int:
        with self._lock:
            cutoff = utc_now() - timedelta(days=self.retention_days)
            removed = 0
            for record in self.store.list_executions():
                if record["state"] not in TERMINAL_EXECUTION_STATES:
                    continue
                try:
                    updated = parse_time(str(record["updated_at"]))
                except ValueError:
                    continue
                if updated >= cutoff:
                    continue

                outstanding_task = (
                    record["published_at"] is not None
                    and record["dismissed_at"] is None
                )
                self._remove_artifacts(record)
                if outstanding_task:
                    if record["state"] != "lost":
                        self.store.mark_lost(
                            str(record["execution_id"]), reason="retention_expired"
                        )
                    continue
                self.store.delete(str(record["execution_id"]))
                removed += 1
            self._next_cleanup_monotonic = time.monotonic() + _CLEANUP_INTERVAL_SECONDS
            return removed

    def _maybe_cleanup(self) -> None:
        if time.monotonic() >= self._next_cleanup_monotonic:
            self.cleanup()

    def _refresh(self, record: dict[str, Any]) -> dict[str, Any]:
        state = str(record["state"])
        if state in TERMINAL_EXECUTION_STATES:
            self._reap_pid(record)
            return record

        if state == "accepted":
            age = utc_now() - parse_time(str(record["accepted_at"]))
            if age.total_seconds() >= _ACCEPTED_LAUNCH_GRACE_SECONDS:
                failed = self.store.fail_accepted(
                    str(record["execution_id"]), reason="launch_interrupted"
                )
                if (
                    failed["state"] == "failed"
                    and failed["reason"] == "launch_interrupted"
                ):
                    self._signal_execution(failed)
                    self._discard_request_artifacts(failed)
                return failed
            if self._execution_alive(record):
                return record
            return record

        outcome_path = Path(str(record["outcome_path"]))
        if outcome_path.is_file():
            return self._recover_outcome(record, outcome_path)
        if self._execution_alive(record):
            return record

        deadline = time.monotonic() + _EXIT_MARKER_GRACE_SECONDS
        while time.monotonic() < deadline:
            current = self._get(str(record["execution_id"]))
            if current["state"] in TERMINAL_EXECUTION_STATES:
                self._reap_pid(current)
                return current
            if outcome_path.is_file():
                return self._recover_outcome(current, outcome_path)
            time.sleep(0.025)

        self._reap_pid(record)
        if record["cancel_requested"]:
            return self.store.finish(
                str(record["execution_id"]), exit_code=None, reason="cancelled"
            )
        return self.store.mark_lost(
            str(record["execution_id"]), reason="worker_disappeared"
        )

    def _recover_outcome(
        self, record: dict[str, Any], outcome_path: Path
    ) -> dict[str, Any]:
        try:
            outcome = json.loads(outcome_path.read_text())
            if not isinstance(outcome, dict) or outcome.get("v") != 1:
                raise ValueError("unsupported outcome marker")
            raw_exit_code = outcome.get("exit_code")
            if raw_exit_code is not None and not isinstance(raw_exit_code, int):
                raise TypeError("outcome exit_code must be an integer or null")
            exit_code = raw_exit_code
            deadline_exceeded = outcome.get("reason") == "deadline_exceeded"
        except json.JSONDecodeError, TypeError, ValueError:
            self._reap_pid(record)
            if record["cancel_requested"]:
                return self.store.finish(
                    str(record["execution_id"]), exit_code=None, reason="cancelled"
                )
            return self.store.mark_lost(
                str(record["execution_id"]), reason="outcome_marker_invalid"
            )
        self._reap_pid(record)
        return self.store.finish(
            str(record["execution_id"]),
            exit_code=exit_code,
            deadline_exceeded=deadline_exceeded,
        )

    def _signal_execution(self, record: dict[str, Any]) -> None:
        if record["backend"] == "systemd" and record["systemd_unit"]:
            with contextlib.suppress(subprocess.TimeoutExpired):
                subprocess.run(
                    [
                        "systemctl",
                        "--user",
                        "stop",
                        "--no-block",
                        str(record["systemd_unit"]),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                    check=False,
                )
            return

        for key in ("child_pid", "worker_pid"):
            try:
                pid = int(record[key])
            except KeyError, TypeError, ValueError:
                continue
            if not process_matches(
                pid, record.get(f"{key.removesuffix('_pid')}_start_ticks")
            ):
                continue
            try:
                if key == "child_pid":
                    os.killpg(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
            except ProcessLookupError, PermissionError:
                pass

    def _execution_alive(self, record: dict[str, Any]) -> bool:
        try:
            worker_pid = int(record["worker_pid"])
        except TypeError, ValueError:
            worker_pid = None
        if worker_pid is not None and process_matches(
            worker_pid, record.get("worker_start_ticks")
        ):
            return True
        if record["backend"] == "systemd":
            return self._systemd_unit_running(str(record["systemd_unit"] or ""))
        return False

    def _get(self, execution_id: str) -> dict[str, Any]:
        try:
            return self.store.get(execution_id)
        except KeyError as exc:
            raise ExecutionNotFoundError(execution_id) from exc

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any], *, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        temporary.chmod(mode)
        os.replace(temporary, path)

    def _remove_artifacts(self, record: dict[str, Any]) -> None:
        candidate = Path(str(record["artifact_dir"])).resolve()
        root = self.root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return
        if candidate == root:
            return
        shutil.rmtree(candidate, ignore_errors=True)

    def _discard_request_artifacts(self, record: dict[str, Any]) -> None:
        request_path = str(record.get("request_path") or "")
        if request_path:
            Path(request_path).unlink(missing_ok=True)
        (Path(str(record["artifact_dir"])) / "input.json").unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            self.store.clear_request_path(str(record["execution_id"]))

    @staticmethod
    def _detect_user_systemd() -> bool:
        try:
            completed = subprocess.run(
                ["systemctl", "--user", "is-system-running"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                check=False,
            )
        except FileNotFoundError, subprocess.TimeoutExpired:
            return False
        return completed.stdout.strip() in {"running", "degraded", "starting"}

    @staticmethod
    def _systemd_unit_running(unit: str) -> bool:
        if not unit:
            return False
        try:
            completed = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ActiveState",
                    "--value",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except FileNotFoundError, subprocess.TimeoutExpired:
            return False
        return completed.stdout.strip() in {"active", "activating", "reloading"}

    @staticmethod
    def _reap_pid(record: dict[str, Any]) -> None:
        if record["backend"] == "systemd":
            return
        try:
            pid = int(record["worker_pid"])
        except TypeError, ValueError:
            return
        with contextlib.suppress(ChildProcessError, ProcessLookupError):
            os.waitpid(pid, os.WNOHANG)

    @staticmethod
    def _public_status(record: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "execution_id": record["execution_id"],
            "label": record["label"],
            "state": record["state"],
            "reason": record["reason"],
            "backend": record["backend"],
            "systemd_unit": record["systemd_unit"],
            "worker_pid": record["worker_pid"],
            "accepted_at": record["accepted_at"],
            "claimed_at": record["claimed_at"],
            "finished_at": record["finished_at"],
            "updated_at": record["updated_at"],
            "published": record["published_at"] is not None,
            "cancel_requested": record["cancel_requested"],
            "work_deadline_at": record["work_deadline_at"],
            "absolute_deadline_at": record["absolute_deadline_at"],
            "poll_interval_ms": POLL_INTERVAL_MS,
        }
        if record["exit_code"] is not None:
            payload["exit_code"] = record["exit_code"]
        for name in ("stdout", "stderr"):
            path = Path(str(record[f"{name}_path"]))
            try:
                payload[f"{name}_bytes"] = path.stat().st_size
            except FileNotFoundError:
                payload[f"{name}_bytes"] = 0
        return payload

    @staticmethod
    def _public_task(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "execution_id": record["execution_id"],
            "label": record["label"],
            "state": record["state"],
            "reason": record["reason"],
            "accepted_at": record["accepted_at"],
            "finished_at": record["finished_at"],
            "published_at": record["published_at"],
            "updated_at": record["updated_at"],
            "elapsed_seconds": task_elapsed_seconds(record),
        }

    def task_with_result(self, execution_id: str) -> dict[str, Any]:
        task = self.task(execution_id)
        state = str(task["state"])
        if state in {"accepted", "running"}:
            return {"task": task, "ready": False}
        if state == "lost":
            return {"task": task, "ready": False, "unavailable": True}
        try:
            result = self.result(execution_id)
        except (ExecutionNotFoundError, FileNotFoundError):
            self.store.mark_lost(execution_id, reason="retained_result_missing")
            return {
                "task": self.task(execution_id),
                "ready": False,
                "unavailable": True,
            }
        return {"task": task, "ready": True, "result": result}

    def cancel_task(self, execution_id: str) -> dict[str, Any]:
        self.task(execution_id)
        self.cancel(execution_id)
        return {"task": self.task(execution_id)}

    def dismiss_task(self, execution_id: str) -> dict[str, Any]:
        task = self.task(execution_id)
        if task["state"] not in TERMINAL_EXECUTION_STATES:
            raise ValueError("dismiss requires a terminal or lost Task")
        return self.dismiss(execution_id)
