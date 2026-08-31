from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic_monty import MontyRuntimeError, MontyTypingError

import gpt_dive.code_capabilities as capabilities_module
from gpt_dive.code_capabilities import build_code_registry, code_runtime
from gpt_dive.code_runtime import CallableRegistry
from gpt_dive.command_runtime import runtime_record
from gpt_dive.execution_store import ExecutionStore, generate_execution_id

EXPECTED_CAPABILITIES = {
    "read_file",
    "write_file",
    "edit_file",
    "list_directory",
    "search_files",
    "find_files",
    "create_directory",
    "file_info",
    "agy_worker",
    "subagent_call",
    "peer_review",
    "repo_search",
    "council_emit",
    "run_command",
    "deadline_remaining",
}


def registry_for_test(
    root: Path, *, duration_seconds: float = 60.0
) -> CallableRegistry:
    store = ExecutionStore(root / "runtime.sqlite3")
    execution_id = generate_execution_id()
    store.create(
        execution_id=execution_id,
        kind="test",
        label="test execution",
        cwd=str(root),
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=duration_seconds,
        cleanup_timeout_seconds=10.0,
        request_path=root / "request.json",
        artifact_dir=root / "artifacts",
        stdout_path=root / "stdout.log",
        stderr_path=root / "stderr.log",
        outcome_path=root / "outcome.json",
    )
    record = runtime_record(store.get(execution_id), store=store)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    return build_code_registry(str(root), record=record)


def run_code(
    root: Path,
    code: str,
    *,
    payload: str | None = None,
    duration_seconds: float = 60.0,
) -> Any:
    return asyncio.run(
        code_runtime.run(
            code,
            registry_for_test(root, duration_seconds=duration_seconds),
            cwd=str(root),
            payload=payload,
        )
    )


def test_registry_has_the_renewed_fifteen_capabilities(tmp_path: Path) -> None:
    registry = registry_for_test(tmp_path)
    descriptions = registry.describe()
    stubs = registry.type_check_stubs(include_payload=True)

    assert set(descriptions) == EXPECTED_CAPABILITIES
    assert "PAYLOAD: str" in stubs
    assert "BACKGROUND" not in stubs
    for removed in ("task_list", "task_collect", "task_cancel", "task_ack"):
        assert removed not in descriptions
    for name in ("agy_worker", "subagent_call", "peer_review"):
        assert "timeout" not in descriptions[name]["signature"]


def test_runtime_returns_expression_and_payload_results(tmp_path: Path) -> None:
    assert run_code(tmp_path, "1 + 2") == 3
    assert run_code(
        tmp_path,
        "PAYLOAD.splitlines()",
        payload="first\nsecond",
    ) == ["first", "second"]


def test_capabilities_are_discoverable_inside_monty(tmp_path: Path) -> None:
    result = run_code(tmp_path, "CAPABILITIES")

    assert set(result) == EXPECTED_CAPABILITIES
    assert (
        "read-only Execution work budget" in result["deadline_remaining"]["description"]
    )


def test_run_command_is_awaited_bounded_and_preserves_output(tmp_path: Path) -> None:
    result = run_code(
        tmp_path,
        "await run_command(\"printf '  CLI_OK  \\n'; printf ' ERR ' >&2\")",
    )

    assert result == {
        "exit_code": 0,
        "stdout": "  CLI_OK  \n",
        "stderr": " ERR ",
        "duration_ms": result["duration_ms"],
        "truncated": False,
    }
    assert result["duration_ms"] >= 0


def test_run_command_resolves_tool_from_mise_shims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    shim_dir = fake_home / ".local" / "share" / "mise" / "shims"
    shim_dir.mkdir(parents=True)
    tool = shim_dir / "mise-probe"
    tool.write_text("#!/bin/sh\nprintf 'MISE_SHIM_OK\\n'\n")
    tool.chmod(0o755)
    monkeypatch.setenv("HOME", str(fake_home))

    result = run_code(tmp_path, 'await run_command("mise-probe")')

    assert result["exit_code"] == 0
    assert result["stdout"] == "MISE_SHIM_OK\n"


def test_deadline_remaining_is_read_only_and_dynamic(tmp_path: Path) -> None:
    result = run_code(
        tmp_path,
        "first = deadline_remaining()\nsecond = deadline_remaining()\n"
        "{'first': first, 'second': second}",
    )

    assert 0 < result["second"] <= result["first"] <= 60


def test_runtime_supplies_child_budget_without_model_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_subagent(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"ok": True, "model": kwargs["model"], "output": "OK"}

    monkeypatch.setattr(capabilities_module, "invoke_subagent", fake_subagent)

    result = run_code(
        tmp_path,
        "await subagent_call(model='terra', task='review', output_tokens_limit=321)",
    )

    assert result == {"ok": True, "model": "terra", "output": "OK"}
    timeout = calls[0]["timeout"]
    assert isinstance(timeout, int | float)
    assert 0 < timeout <= 60
    assert calls[0]["workspace_dir"] == str(tmp_path)
    with pytest.raises((MontyTypingError, MontyRuntimeError)):
        run_code(
            tmp_path,
            "await subagent_call(model='terra', task='review', timeout=30)",
        )


def test_all_model_capabilities_receive_runtime_owned_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, dict[str, object]] = {}

    async def fake_agy(**kwargs: object) -> dict[str, object]:
        calls["agy"] = kwargs
        return {"ok": True}

    async def fake_peer(**kwargs: object) -> dict[str, object]:
        calls["peer"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(capabilities_module, "invoke_agy_worker", fake_agy)
    monkeypatch.setattr(capabilities_module, "invoke_model_call", fake_peer)

    run_code(
        tmp_path,
        "await asyncio.gather("
        "agy_worker(task='research'), "
        "peer_review(provider='openai', prompt='review'))",
    )

    assert set(calls) == {"agy", "peer"}
    for call in calls.values():
        timeout = call["timeout"]
        assert isinstance(timeout, int | float)
        assert 0 < timeout <= 60


def test_filesystem_capabilities_keep_conflict_and_secret_policy(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("original")
    stale_hash = hashlib.sha256(b"stale").hexdigest()[:12]

    assert "original" in run_code(tmp_path, "await read_file('target.txt')")
    with pytest.raises(Exception, match="Conflict: file"):
        run_code(
            tmp_path,
            f"await write_file('target.txt', 'changed', expected_hash={stale_hash!r})",
        )

    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret")
    with pytest.raises(Exception, match="denied by pattern"):
        run_code(tmp_path, "await read_file('.env')")


def test_broad_recursive_search_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        MontyRuntimeError,
        match="search_files refuses broad recursive search rooted at /",
    ):
        run_code(tmp_path, "await search_files('needle', path='/')")


def test_repo_search_and_council_emit_use_explicit_capability_seams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_search(**kwargs: object) -> dict[str, object]:
        return kwargs

    def fake_emit(
        council_dir: str, message: str, expected_head: str | None
    ) -> dict[str, object]:
        return {
            "council_dir": council_dir,
            "message": message,
            "expected_head": expected_head,
        }

    monkeypatch.setattr(capabilities_module, "search_repo", fake_search)
    monkeypatch.setattr(capabilities_module, "emit_sol_response", fake_emit)

    search = run_code(
        tmp_path,
        "await repo_search(query='needle', path='src')",
    )
    council = run_code(
        tmp_path,
        "await council_emit(council_dir='.', message='round')",
    )

    assert search["path"] == str((tmp_path / "src").resolve())
    assert council["message"] == "round"
