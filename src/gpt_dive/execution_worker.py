from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from .execution_store import ExecutionStore, parse_time, utc_now
from .runtime_env import build_runtime_path

_POLL_SECONDS = 0.05
_TERM_GRACE_SECONDS = 4.0
_KILL_GRACE_SECONDS = 4.0
_PR_SET_CHILD_SUBREAPER = 36


def _proc_info(pid: int) -> dict[str, int | str] | None:
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
    return {
        "state": rest[0],
        "ppid": int(rest[1]),
        "start_ticks": int(rest[19]),
    }


def _proc_start_ticks(pid: int) -> int | None:
    info = _proc_info(pid)
    return int(info["start_ticks"]) if info is not None else None


def _become_subreaper() -> None:
    """Keep daemonized descendants observable by the Execution Worker."""
    with contextlib.suppress(AttributeError, OSError):
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER) failed")


def _write_outcome(
    path: Path, *, returncode: int | None, deadline_exceeded: bool
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "v": 1,
                "exit_code": returncode,
                "reason": "deadline_exceeded" if deadline_exceeded else None,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    os.replace(temporary, path)


def _signal_group(pid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, sig)


def _descendant_identities(root_pid: int) -> dict[int, int]:
    children: dict[int, list[int]] = {}
    identities: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        info = _proc_info(pid)
        if info is None:
            continue
        ppid = int(info["ppid"])
        children.setdefault(ppid, []).append(pid)
        identities[pid] = int(info["start_ticks"])

    descendants: dict[int, int] = {}
    stack = list(children.get(root_pid, ()))
    while stack:
        pid = stack.pop()
        start_ticks = identities.get(pid)
        if start_ticks is None or pid in descendants:
            continue
        descendants[pid] = start_ticks
        stack.extend(children.get(pid, ()))
    return descendants


def _signal_descendants(root_pid: int, sig: signal.Signals) -> None:
    for pid, start_ticks in reversed(_descendant_identities(root_pid).items()):
        info = _proc_info(pid)
        if (
            info is None
            or info["state"] == "Z"
            or int(info["start_ticks"]) != start_ticks
        ):
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, sig)


def _reap_orphans(*, direct_pid: int) -> None:
    for pid in _descendant_identities(os.getpid()):
        if pid == direct_pid:
            continue
        with contextlib.suppress(ChildProcessError, ProcessLookupError):
            os.waitpid(pid, os.WNOHANG)


def _wait_for_tree_exit(proc: subprocess.Popen[bytes], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        direct_done = proc.poll() is not None
        _reap_orphans(direct_pid=proc.pid)
        if direct_done and not _descendant_identities(os.getpid()):
            return True
        time.sleep(_POLL_SECONDS)
    return proc.poll() is not None and not _descendant_identities(os.getpid())


def _terminate_child(proc: subprocess.Popen[bytes]) -> bool:
    if proc.poll() is None:
        _signal_group(proc.pid, signal.SIGTERM)
    _signal_descendants(os.getpid(), signal.SIGTERM)
    if _wait_for_tree_exit(proc, _TERM_GRACE_SECONDS):
        return True
    if proc.poll() is None:
        _signal_group(proc.pid, signal.SIGKILL)
    _signal_descendants(os.getpid(), signal.SIGKILL)
    return _wait_for_tree_exit(proc, _KILL_GRACE_SECONDS)


def _load_request(store: ExecutionStore, execution_id: str) -> dict[str, Any]:
    record = store.get(execution_id)
    request_path = Path(str(record["request_path"]))
    try:
        request = json.loads(request_path.read_text())
    finally:
        request_path.unlink(missing_ok=True)
        store.clear_request_path(execution_id)
    if not isinstance(request, dict) or request.get("v") != 1:
        raise ValueError("unsupported Execution worker request")
    command = request.get("command")
    cwd = request.get("cwd")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Execution worker request requires command")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Execution worker cwd must be a string or null")
    return request


def run_execution(store: ExecutionStore, execution_id: str) -> int:
    worker_pid = os.getpid()
    _become_subreaper()
    if not store.claim(
        execution_id,
        worker_pid=worker_pid,
        worker_start_ticks=_proc_start_ticks(worker_pid),
    ):
        record = store.get(execution_id)
        if record["state"] in {"completed", "failed", "cancelled", "lost"}:
            request_path = str(record.get("request_path") or "")
            if request_path:
                Path(request_path).unlink(missing_ok=True)
                store.clear_request_path(execution_id)
            (Path(str(record["artifact_dir"])) / "input.json").unlink(missing_ok=True)
        return 0

    record = store.get(execution_id)
    stderr_path = Path(str(record["stderr_path"]))
    proc: subprocess.Popen[bytes] | None = None
    cancellation_signal = False

    def request_cancellation(_signum: int, _frame: object) -> None:
        nonlocal cancellation_signal
        cancellation_signal = True

    signal.signal(signal.SIGTERM, request_cancellation)
    signal.signal(signal.SIGINT, request_cancellation)

    try:
        request = _load_request(store, execution_id)
        run_cwd = request.get("cwd")
        if run_cwd is not None and not Path(run_cwd).is_dir():
            raise ValueError(f"cwd does not exist or is not a directory: {run_cwd}")

        guard_bin = Path(__file__).resolve().parent / "guard-bin"
        runtime_path = build_runtime_path(guard_bin)
        guarded_command = (
            f"export PATH={shlex.quote(runtime_path)}; {request['command']!s}"
        )
        stdout_path = Path(str(record["stdout_path"]))
        stdout_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stdout_path.touch(mode=0o600, exist_ok=True)
        stderr_path.touch(mode=0o600, exist_ok=True)
        with stdout_path.open("wb") as stdout_fh, stderr_path.open("wb") as stderr_fh:
            proc = subprocess.Popen(
                ["/bin/bash", "-lc", guarded_command],
                cwd=run_cwd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_fh,
                stderr=stderr_fh,
                start_new_session=True,
            )
            store.set_child(
                execution_id,
                child_pid=proc.pid,
                child_start_ticks=_proc_start_ticks(proc.pid),
            )

            remaining_work = max(
                0.0,
                (
                    parse_time(str(record["work_deadline_at"])) - utc_now()
                ).total_seconds(),
            )
            work_deadline = time.monotonic() + remaining_work
            deadline_exceeded = False
            while proc.poll() is None:
                current = store.get(execution_id)
                if cancellation_signal or current["cancel_requested"]:
                    if not current["cancel_requested"]:
                        store.request_cancel(execution_id)
                    _terminate_child(proc)
                    break
                if time.monotonic() >= work_deadline:
                    deadline_exceeded = True
                    _terminate_child(proc)
                    break
                time.sleep(_POLL_SECONDS)

            returncode = proc.poll()
            cleanup_confirmed = _terminate_child(proc)
            returncode = proc.poll()

        if not cleanup_confirmed:
            store.mark_lost(execution_id, reason="cleanup_unconfirmed")
            return 1

        _write_outcome(
            Path(str(record["outcome_path"])),
            returncode=returncode,
            deadline_exceeded=deadline_exceeded,
        )
        (Path(str(record["artifact_dir"])) / "input.json").unlink(missing_ok=True)
        store.finish(
            execution_id,
            exit_code=returncode,
            deadline_exceeded=deadline_exceeded,
        )
        return int(returncode or 0)
    except BaseException:
        (Path(str(record["artifact_dir"])) / "input.json").unlink(missing_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with stderr_path.open("a", encoding="utf-8", errors="replace") as stderr_fh:
            traceback.print_exc(file=stderr_fh)
        if proc is not None:
            _terminate_child(proc)
        try:
            current = store.get(execution_id)
            if current["state"] == "running":
                store.fail_running(execution_id, reason="worker_error")
            elif current["state"] == "accepted":
                store.fail_accepted(execution_id, reason="launch_interrupted")
        except Exception:
            traceback.print_exc(file=sys.stderr)
        return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--execution", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    raise SystemExit(run_execution(ExecutionStore(args.store), args.execution))


if __name__ == "__main__":
    main()
