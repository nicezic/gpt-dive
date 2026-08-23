from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from .runtime_env import build_runtime_path


def run_command(
    command: str,
    cwd: str | None = None,
    timeout: float = 600.0,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not command.strip():
        raise ValueError("command must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    run_cwd = str(Path(cwd).expanduser()) if cwd else None
    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    runtime_path = build_runtime_path(guard_bin)
    guarded_command = f"export PATH={shlex.quote(runtime_path)}; {command}"

    try:
        completed = subprocess.run(
            ["/bin/bash", "-lc", guarded_command],
            cwd=run_cwd,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=timeout,
            check=False,
            env=env,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return {
            "command": command,
            "returncode": 124,
            "stdout": stdout,
            "stderr": (
                f"{stderr}\n[command] timed out after {timeout} seconds"
            ).lstrip(),
        }
