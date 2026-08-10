from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RETENTION_DAYS = 5
POLL_INTERVAL_MS = 1000


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class JobNotFoundError(KeyError):
    pass


class JobManager:
    """Durable local process jobs for long-running WSL2 shell commands."""

    def __init__(
        self, root: Path | None = None, *, retention_days: int = RETENTION_DAYS
    ) -> None:
        self.root = root or (Path.home() / ".local" / "state" / "gpt-dive" / "jobs")
        self.retention_days = retention_days
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._systemd_available = self._detect_user_systemd()
        self.recover()

    def start(
        self, command: str, cwd: str | None = None, timeout: float = 600.0
    ) -> dict[str, Any]:
        if not command.strip():
            raise ValueError("command must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")

        run_cwd = str(Path(cwd).expanduser()) if cwd else None
        if run_cwd is not None and not Path(run_cwd).is_dir():
            raise ValueError(f"cwd does not exist or is not a directory: {run_cwd}")

        with self._lock:
            self.cleanup()
            job_id = uuid.uuid4().hex
            job_dir = self.root / job_id
            job_dir.mkdir(mode=0o700)
            stdout_path = job_dir / "stdout.log"
            stderr_path = job_dir / "stderr.log"
            exit_tmp = job_dir / "exit_code.tmp"
            exit_path = job_dir / "exit_code"

            guard_bin = Path(__file__).resolve().parent / "guard-bin"
            pnpm_bin = Path.home() / ".local" / "share" / "pnpm"
            guarded_command = f'export PATH="{guard_bin}:{pnpm_bin}:$PATH"; {command}'
            inner = (
                f"timeout --signal=TERM --kill-after=5s {shlex.quote(str(timeout))}s "
                f"/bin/bash -lc {shlex.quote(guarded_command)}"
            )
            runner = (
                f"set +e; {inner}; code=$?; "
                f"printf '%s\\n' \"$code\" > {shlex.quote(str(exit_tmp))}; "
                f"mv {shlex.quote(str(exit_tmp))} {shlex.quote(str(exit_path))}; "
                'exit "$code"'
            )

            backend = "systemd" if self._systemd_available else "popen"
            unit = f"gpt-dive-job-{job_id}.service" if backend == "systemd" else None
            pid: int | None = None
            pid_start_ticks: int | None = None

            if backend == "systemd":
                assert unit is not None
                systemd_runner = (
                    f"set +e; ({inner}) > {shlex.quote(str(stdout_path))} "
                    f"2> {shlex.quote(str(stderr_path))}; code=$?; "
                    f"printf '%s\\n' \"$code\" > {shlex.quote(str(exit_tmp))}; "
                    f"mv {shlex.quote(str(exit_tmp))} {shlex.quote(str(exit_path))}; "
                    'exit "$code"'
                )
                cmd = [
                    "systemd-run",
                    "--user",
                    "--quiet",
                    "--collect",
                    f"--unit={unit.removesuffix('.service')}",
                ]
                if run_cwd:
                    cmd.append(f"--working-directory={run_cwd}")
                cmd.extend(["/bin/bash", "-lc", systemd_runner])
                launched = subprocess.run(
                    cmd, capture_output=True, text=True, check=False
                )
                if launched.returncode != 0:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise RuntimeError(
                        f"systemd-run failed: {launched.stderr.strip() or launched.stdout.strip()}"
                    )
                pid = self._systemd_main_pid(unit)
                proc = self._proc_info(pid) if pid else None
                pid_start_ticks = proc.get("start_ticks") if proc else None
            else:
                out_fh = stdout_path.open("wb")
                err_fh = stderr_path.open("wb")
                try:
                    process = subprocess.Popen(
                        ["/bin/bash", "-lc", runner],
                        cwd=run_cwd,
                        stdin=subprocess.DEVNULL,
                        stdout=out_fh,
                        stderr=err_fh,
                        start_new_session=True,
                    )
                finally:
                    out_fh.close()
                    err_fh.close()
                pid = process.pid
                proc = self._proc_info(pid)
                pid_start_ticks = proc.get("start_ticks") if proc else None

            created = _iso()
            meta: dict[str, Any] = {
                "job_id": job_id,
                "command": command,
                "cwd": run_cwd,
                "timeout": timeout,
                "backend": backend,
                "systemd_unit": unit,
                "pid": pid,
                "pid_start_ticks": pid_start_ticks,
                "status": "running",
                "status_message": "Command is running asynchronously.",
                "created_at": created,
                "updated_at": created,
                "cancel_requested": False,
                "retention_days": self.retention_days,
                "poll_interval_ms": POLL_INTERVAL_MS,
            }
            self._write_meta(job_dir, meta)
            return self._public_status(meta)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self.cleanup()
            job_dir, meta = self._load(job_id)
            meta = self._refresh(job_dir, meta)
            return self._public_status(meta, job_dir=job_dir)

    def result(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self.cleanup()
            job_dir, meta = self._load(job_id)
            meta = self._refresh(job_dir, meta)
            payload = self._public_status(meta, job_dir=job_dir)
            if meta["status"] not in TERMINAL_STATUSES:
                payload["ready"] = False
                payload["message"] = (
                    "Job is still running; use wsl2_async action='status' later."
                )
                return payload
            payload["ready"] = True
            payload["stdout"] = (job_dir / "stdout.log").read_text(errors="replace")
            payload["stderr"] = (job_dir / "stderr.log").read_text(errors="replace")
            return payload

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self.cleanup()
            job_dir, meta = self._load(job_id)
            meta = self._refresh(job_dir, meta)
            if meta["status"] in TERMINAL_STATUSES:
                return self._public_status(meta, job_dir=job_dir)

            meta["cancel_requested"] = True
            meta["status_message"] = "Cancellation requested."
            meta["updated_at"] = _iso()
            self._write_meta(job_dir, meta)

            if meta.get("backend") == "systemd" and meta.get("systemd_unit"):
                subprocess.run(
                    ["systemctl", "--user", "stop", str(meta["systemd_unit"])],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    pid = int(meta["pid"])
                except KeyError, TypeError, ValueError:
                    pid = 0
                if pid and self._pid_matches(meta):
                    try:
                        os.killpg(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    except PermissionError as exc:
                        meta["status_message"] = (
                            f"Cancellation could not signal process group: {exc}"
                        )
                        meta["updated_at"] = _iso()
                        self._write_meta(job_dir, meta)
                else:
                    meta = self._refresh(job_dir, meta)
            return self._public_status(meta, job_dir=job_dir)

    def recover(self) -> None:
        with self._lock:
            for job_dir in self._job_dirs():
                try:
                    meta = self._read_meta(job_dir)
                    self._refresh(job_dir, meta)
                except OSError, ValueError, json.JSONDecodeError:
                    continue
            self.cleanup()

    def cleanup(self) -> int:
        cutoff = _now() - timedelta(days=self.retention_days)
        removed = 0
        for job_dir in self._job_dirs():
            try:
                meta = self._read_meta(job_dir)
            except OSError, ValueError, json.JSONDecodeError:
                continue
            if meta.get("status") not in TERMINAL_STATUSES:
                continue
            try:
                updated = _parse_iso(str(meta["updated_at"]))
            except KeyError, ValueError:
                continue
            if updated < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
        return removed

    def _refresh(self, job_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
        if meta.get("status") in TERMINAL_STATUSES:
            self._reap_pid(meta)
            return meta

        exit_path = job_dir / "exit_code"
        if exit_path.is_file():
            try:
                exit_code = int(exit_path.read_text().strip())
            except ValueError:
                exit_code = None
            self._reap_pid(meta)
            meta["exit_code"] = exit_code
            if meta.get("cancel_requested"):
                meta["status"] = "cancelled"
                meta["status_message"] = "Command was cancelled."
            else:
                meta["status"] = "completed"
                meta["status_message"] = "Command completed."
            meta["updated_at"] = _iso()
            self._write_meta(job_dir, meta)
            return meta

        if meta.get("backend") == "systemd":
            if self._systemd_unit_running(str(meta.get("systemd_unit") or "")):
                return meta
        elif self._pid_matches(meta):
            return meta

        self._reap_pid(meta)
        if meta.get("cancel_requested"):
            meta["status"] = "cancelled"
            meta["status_message"] = (
                "Command was cancelled before producing an exit marker."
            )
        else:
            meta["status"] = "failed"
            meta["status_message"] = (
                "Runner disappeared without an exit marker; recovered as an orphaned job."
            )
        meta["updated_at"] = _iso()
        self._write_meta(job_dir, meta)
        return meta

    @staticmethod
    def _reap_pid(meta: dict[str, Any]) -> None:
        if meta.get("backend") == "systemd":
            return
        try:
            pid = int(meta["pid"])
        except KeyError, TypeError, ValueError:
            return
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError, ProcessLookupError:
            # After an MCP restart the runner is no longer our child; init/systemd
            # owns reaping it. The durable marker/PID checks still recover state.
            pass

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
    def _systemd_main_pid(unit: str) -> int | None:
        completed = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=MainPID", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            pid = int(completed.stdout.strip())
        except ValueError:
            return None
        return pid or None

    @staticmethod
    def _systemd_unit_running(unit: str) -> bool:
        if not unit:
            return False
        completed = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=ActiveState", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip() in {"active", "activating", "reloading"}

    def _pid_matches(self, meta: dict[str, Any]) -> bool:
        try:
            pid = int(meta["pid"])
        except KeyError, TypeError, ValueError:
            return False
        proc = self._proc_info(pid)
        if proc is None or proc["state"] == "Z":
            return False
        expected = meta.get("pid_start_ticks")
        return expected is None or proc["start_ticks"] == expected

    @staticmethod
    def _proc_info(pid: int) -> dict[str, Any] | None:
        try:
            text = (Path("/proc") / str(pid) / "stat").read_text()
        except FileNotFoundError, ProcessLookupError, PermissionError:
            return None
        end = text.rfind(")")
        if end < 0:
            return None
        rest = text[end + 2 :].split()
        if len(rest) <= 19:
            return None
        return {"state": rest[0], "start_ticks": int(rest[19])}

    def _load(self, job_id: str) -> tuple[Path, dict[str, Any]]:
        if not job_id or any(ch not in "0123456789abcdef" for ch in job_id.lower()):
            raise JobNotFoundError(job_id)
        job_dir = self.root / job_id
        if not job_dir.is_dir():
            raise JobNotFoundError(job_id)
        return job_dir, self._read_meta(job_dir)

    def _job_dirs(self) -> list[Path]:
        if not self.root.exists():
            return []
        return [path for path in self.root.iterdir() if path.is_dir()]

    @staticmethod
    def _read_meta(job_dir: Path) -> dict[str, Any]:
        return json.loads((job_dir / "meta.json").read_text())

    @staticmethod
    def _write_meta(job_dir: Path, meta: dict[str, Any]) -> None:
        temp = job_dir / "meta.json.tmp"
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, job_dir / "meta.json")

    def _public_status(
        self, meta: dict[str, Any], *, job_dir: Path | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": meta["job_id"],
            "status": meta["status"],
            "status_message": meta.get("status_message"),
            "backend": meta.get("backend", "popen"),
            "systemd_unit": meta.get("systemd_unit"),
            "pid": meta.get("pid"),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
            "poll_interval_ms": meta.get("poll_interval_ms", POLL_INTERVAL_MS),
            "retention_days": meta.get("retention_days", self.retention_days),
        }
        if "exit_code" in meta:
            payload["exit_code"] = meta["exit_code"]
        if job_dir is not None:
            for name in ("stdout", "stderr"):
                path = job_dir / f"{name}.log"
                try:
                    payload[f"{name}_bytes"] = path.stat().st_size
                except FileNotFoundError:
                    payload[f"{name}_bytes"] = 0
        return payload
