from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .runtime_env import build_runtime_path
from .worker_subprocess import run_bounded_worker, stderr_tail


def _compact_probe_result(data: dict[str, Any], root: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        raw_file = Path(str(item.get("file", "")))
        try:
            file_name = str(raw_file.resolve().relative_to(root))
        except ValueError:
            file_name = str(raw_file)

        results.append(
            {
                "file": file_name,
                "lines": item.get("lines"),
                "code": item.get("code", ""),
                "score": item.get("score"),
                "symbol": item.get("owner_qualified_symbol")
                or item.get("owner_symbol"),
                "language": item.get("language"),
            }
        )

    summary = data.get("summary", {})
    return {
        "count": len(results),
        "total_tokens": summary.get("total_tokens"),
        "results": results,
    }


async def search_repo(
    *,
    query: str,
    path: str,
    max_results: int = 8,
    max_tokens: int = 6000,
    allow_tests: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Search a local repository with Probe and return compact AST-aware results."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if max_results <= 0:
        raise ValueError("max_results must be greater than 0")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than 0")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {root}")

    command = [
        "probe",
        "search",
        query,
        str(root),
        "--format",
        "json",
        "--max-results",
        str(max_results),
        "--max-tokens",
        str(max_tokens),
    ]
    if allow_tests:
        command.append("--allow-tests")

    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))
    outcome = await run_bounded_worker(
        command,
        env=env,
        timeout=timeout,
        grace_seconds=0.0,
        termination_grace_seconds=2.0,
        log_label="PROBE SEARCH",
    )
    if not outcome.reaped:
        return {
            "ok": False,
            "engine": "probe",
            "query": query,
            "path": str(root),
            "error": "probe search process group could not be reaped after termination",
        }
    if outcome.timed_out:
        return {
            "ok": False,
            "engine": "probe",
            "query": query,
            "path": str(root),
            "error": f"probe search timed out after {timeout} seconds",
        }

    stdout_text = outcome.stdout_text
    stderr_text = outcome.stderr_text
    if outcome.returncode != 0:
        return {
            "ok": False,
            "engine": "probe",
            "query": query,
            "path": str(root),
            "error": f"probe search exited with code {outcome.returncode}",
            "stderr": stderr_tail(stderr_text),
        }

    try:
        data = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "engine": "probe",
            "query": query,
            "path": str(root),
            "error": f"invalid probe JSON: {exc}",
            "stdout": stdout_text[-2000:],
            "stderr": stderr_tail(stderr_text),
        }

    compact = _compact_probe_result(data, root)
    return {
        "ok": True,
        "engine": "probe",
        "query": query,
        "path": str(root),
        **compact,
    }
