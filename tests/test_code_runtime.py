from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from pydantic_monty import MontyRuntimeError, MontyTypingError

import gpt_dive.app as app_module
import gpt_dive.code_capabilities as code_capabilities_module
import gpt_dive.task_runtime as task_runtime_module
from gpt_dive import code_mode


def test_code_mode_returns_expression_result() -> None:
    assert asyncio.run(code_mode("1 + 2")) == {"result": 3}


def test_code_mode_can_read_and_write_local_filesystem() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        target = Path(td) / "monty-rw.txt"
        code = f"""\nfrom pathlib import Path\np = Path({str(target)!r})\np.write_text("DIVE_RW_OK")\np.read_text()\n"""
        assert asyncio.run(code_mode(code)) == {"result": "DIVE_RW_OK"}
        assert target.read_text() == "DIVE_RW_OK"


def test_code_mode_payload_can_carry_multiline_text() -> None:
    payload = "PAYLOAD_OK\nSECOND_LINE"
    code = "PAYLOAD.splitlines()"
    result = asyncio.run(code_mode(code, payload=payload))["result"]
    assert result == ["PAYLOAD_OK", "SECOND_LINE"]


def test_code_mode_payload_type_stub_has_no_input_alias() -> None:
    from gpt_dive.code_runtime import CallableRegistry

    stubs = CallableRegistry().type_check_stubs(include_payload=True)
    assert "PAYLOAD: str" in stubs
    assert "BACKGROUND: bool" in stubs
    assert "INPUT: str" not in stubs


def test_code_mode_exposes_foreground_flag() -> None:
    assert asyncio.run(code_mode("BACKGROUND")) == {"result": False}


def test_capabilities_are_runtime_discoverable() -> None:
    result = asyncio.run(code_mode("CAPABILITIES"))["result"]
    assert set(result) == {
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
        "m3_evidence",
        "repo_search",
        "council_emit",
        "task_list",
        "task_collect",
        "task_cancel",
        "task_ack",
    }
    for removed in (
        "run_command",
        "start_command",
        "check_command",
        "stop_command",
        "gz64",
    ):
        assert removed not in result
    assert "offset" in result["read_file"]["signature"]
    assert "expected_hash" in result["write_file"]["signature"]
    assert "expected_hash" in result["edit_file"]["signature"]
    assert "conversation_id" in result["agy_worker"]["signature"]
    assert result["read_file"]["description"].startswith(
        "Read a text file with line numbers."
    )
    assert result["edit_file"]["description"].startswith("Edit a file")


def test_removed_capabilities_rejected_statically() -> None:
    for removed in (
        "run_command('echo 1')",
        "start_command('echo 1')",
        "check_command('job_id')",
        "stop_command('job_id')",
        "gz64('payload')",
    ):
        with pytest.raises((MontyTypingError, MontyRuntimeError)):
            asyncio.run(code_mode(f"await {removed}"))


def test_foreground_code_mode_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "_FOREGROUND_CODE_MODE_TIMEOUT_SECONDS", 0.05)
    code = "x = 0\nfor _ in range(20000000):\n    x += 1\nx"
    t0 = time.monotonic()
    result = asyncio.run(code_mode(code))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2, f"Foreground timeout exceeded deadline budget: {elapsed}s"
    assert result["ok"] is False
    assert result["error"] == {
        "code": "code_mode_timeout",
        "message": (
            "Foreground Code Mode reached its 0.04-second execution cutoff within "
            "the fixed 0.05-second response deadline; relaunch with task."
        ),
        "timeout_seconds": 0.05,
        "execution_cutoff_seconds": 0.04,
        "retry_as_task": True,
        "cleanup_status": result["error"]["cleanup_status"],
    }
    assert result["error"]["cleanup_status"] in {"complete", "pending"}
    recovery = asyncio.run(code_mode("1 + 2"))
    assert recovery == {"result": 3}


def test_inner_timeout_error_is_not_converted_to_code_mode_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def mock_run(*args: object, **kwargs: object) -> dict[str, object]:
        raise TimeoutError("inner capability timeout")

    monkeypatch.setattr(app_module.code_runtime, "run", mock_run)
    with pytest.raises(TimeoutError, match="inner capability timeout"):
        asyncio.run(code_mode("1 + 1"))


def test_foreground_code_mode_completes_cleanup_before_returning_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "_FOREGROUND_CODE_MODE_TIMEOUT_SECONDS", 0.1)
    cleanup_finished = False

    async def slow_run_with_cleanup(
        *args: object, **kwargs: object
    ) -> dict[str, object]:
        nonlocal cleanup_finished
        try:
            await asyncio.sleep(10.0)
            return {"result": "ok"}
        except asyncio.CancelledError:
            await asyncio.sleep(0.005)
            cleanup_finished = True
            raise

    monkeypatch.setattr(app_module.code_runtime, "run", slow_run_with_cleanup)
    result = asyncio.run(code_mode("slow()"))
    assert result["ok"] is False
    assert result["error"]["code"] == "code_mode_timeout"
    assert result["error"]["cleanup_status"] == "complete"
    assert cleanup_finished is True, (
        "Cleanup must be 100% complete BEFORE timeout result returns!"
    )


def test_foreground_code_mode_retains_cleanup_that_exceeds_response_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "_FOREGROUND_CODE_MODE_TIMEOUT_SECONDS", 0.05)
    release_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def cleanup_past_deadline(
        *args: object, **kwargs: object
    ) -> dict[str, object]:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release_cleanup.wait()
            cleanup_finished.set()
            raise

    async def scenario() -> None:
        monkeypatch.setattr(app_module.code_runtime, "run", cleanup_past_deadline)
        result = await code_mode("slow()")
        assert result["error"]["code"] == "code_mode_timeout"
        assert result["error"]["cleanup_status"] == "pending"
        assert not cleanup_finished.is_set()
        assert len(app_module._FOREGROUND_CLEANUP_TASKS) == 1

        release_cleanup.set()
        await asyncio.wait_for(cleanup_finished.wait(), timeout=0.1)
        await asyncio.sleep(0)
        assert not app_module._FOREGROUND_CLEANUP_TASKS

    asyncio.run(scenario())


def test_foreground_code_mode_reports_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "_FOREGROUND_CODE_MODE_TIMEOUT_SECONDS", 0.1)

    async def failed_cleanup(*args: object, **kwargs: object) -> dict[str, object]:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("simulated cleanup failure") from None

    monkeypatch.setattr(app_module.code_runtime, "run", failed_cleanup)
    result = asyncio.run(code_mode("slow()"))
    assert result["error"]["code"] == "code_mode_timeout"
    assert result["error"]["cleanup_status"] == "failed"
    assert not app_module._FOREGROUND_CLEANUP_TASKS


def test_detached_code_mode_uses_fixed_600s_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gpt_dive.task_store import TaskStore

    original_task_store = app_module.task_store
    app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")
    started_timeouts: list[float] = []
    real_start = app_module.executions.start

    def mock_start(command: str, cwd: str | None = None, timeout: float = 600.0):
        started_timeouts.append(timeout)
        return real_start(command, cwd, timeout)

    monkeypatch.setattr(app_module.executions, "start", mock_start)
    try:
        started = asyncio.run(code_mode("1 + 1", task={"label": "fixed-timeout-test"}))
        assert started_timeouts == [600.0]
        _wait_code_mode_job(str(started["execution_id"]))
    finally:
        app_module.task_store = original_task_store


def test_normal_search_rejects_broad_root_paths(tmp_path: Path) -> None:
    with pytest.raises(
        MontyRuntimeError,
        match="search_files refuses broad recursive search rooted at /",
    ):
        asyncio.run(code_mode("await search_files('needle', path='/')"))
    with pytest.raises(
        MontyRuntimeError,
        match="find_files refuses broad recursive search rooted at /mnt/c",
    ):
        asyncio.run(code_mode("await find_files('*', path='/mnt/c')"))
    with pytest.raises(
        MontyRuntimeError,
        match="repo_search refuses broad recursive search rooted at /",
    ):
        asyncio.run(code_mode("await repo_search(query='needle', path='/')"))

    target = tmp_path / "narrow.txt"
    target.write_text("needle")
    result = asyncio.run(
        code_mode(f"await search_files('needle', path={str(tmp_path)!r})")
    )["result"]
    assert "narrow.txt" in result


def test_code_mode_static_type_check_rejects_wrong_capability_argument() -> None:
    with pytest.raises(MontyTypingError) as exc_info:
        asyncio.run(code_mode("await search_files(query='M3', path='.')"))

    message = str(exc_info.value)
    assert "missing-argument" in message
    assert "required parameter `pattern`" in message
    assert "unknown-argument" in message
    assert "Argument `query`" in message


def test_subagent_call_is_registry_capability(monkeypatch) -> None:
    import gpt_dive

    calls: list[dict[str, object]] = []

    async def fake_invoke_subagent(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "model": kwargs["model"],
            "output": "SUBAGENT_OK",
        }

    monkeypatch.setattr(
        code_capabilities_module, "invoke_subagent", fake_invoke_subagent
    )
    code = """\nresult = await subagent_call(\n    model='terra',\n    task='review this',\n    timeout=17,\n    output_tokens_limit=321,\n)\n{'ok': result['ok'], 'model': result['model'], 'output': result['output']}\n"""
    assert asyncio.run(gpt_dive.code_mode(code)) == {
        "result": {"ok": True, "model": "terra", "output": "SUBAGENT_OK"}
    }
    assert calls == [
        {
            "model": "terra",
            "task": "review this",
            "timeout": 17,
            "output_tokens_limit": 321,
            "workspace_dir": None,
        }
    ]


def test_m3_evidence_is_registry_capability(monkeypatch) -> None:
    import gpt_dive

    calls: list[dict[str, object]] = []

    async def fake_invoke_m3_evidence(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "known": ["k"],
            "missing": [],
            "conflicts": [],
            "queries": [],
            "done": True,
        }

    monkeypatch.setattr(
        code_capabilities_module, "invoke_m3_evidence", fake_invoke_m3_evidence
    )
    code = "result = await m3_evidence(question='q', evidence='e', max_queries=2, timeout=30.0); result['done']"
    assert asyncio.run(gpt_dive.code_mode(code)) == {"result": True}
    assert calls == [
        {
            "question": "q",
            "evidence": "e",
            "round_number": 1,
            "max_rounds": 3,
            "max_queries": 2,
            "timeout": 30.0,
            "output_tokens_limit": 2048,
        }
    ]


def test_peer_review_is_registry_capability(monkeypatch) -> None:
    import gpt_dive

    calls: list[dict[str, object]] = []

    async def fake_invoke_model_call(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "model": kwargs["model"], "output": "BARE_OK"}

    monkeypatch.setattr(
        code_capabilities_module, "invoke_model_call", fake_invoke_model_call
    )
    code = (
        "result = await peer_review(provider='aiapiflow', model='claude-opus-5', "
        "prompt='think', timeout=180.0); result['output']"
    )
    assert asyncio.run(gpt_dive.code_mode(code, cwd="/tmp/ignored")) == {
        "result": "BARE_OK"
    }
    assert calls == [
        {
            "provider": "aiapiflow",
            "model": "claude-opus-5",
            "prompt": "think",
            "timeout": 180.0,
            "peer_review": True,
            "workspace_dir": "/tmp/ignored",
        }
    ]


def test_repo_search_is_registry_capability(monkeypatch, tmp_path: Path) -> None:
    import gpt_dive

    calls: list[dict[str, object]] = []

    async def fake_search_repo(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "engine": "probe", "count": 1, "results": []}

    monkeypatch.setattr(code_capabilities_module, "search_repo", fake_search_repo)
    code = "result = await repo_search(query='model AND provider'); result['engine']"
    assert asyncio.run(gpt_dive.code_mode(code, cwd=str(tmp_path))) == {
        "result": "probe"
    }
    assert calls == [
        {
            "query": "model AND provider",
            "path": str(tmp_path),
            "max_results": 8,
            "max_tokens": 6000,
            "allow_tests": False,
        }
    ]


def test_subagent_call_preserves_failure_diagnostics(monkeypatch) -> None:
    import gpt_dive

    async def fake_invoke_subagent(**kwargs):
        return {
            "ok": False,
            "model": kwargs["model"],
            "provider": "openai-codex",
            "error": "SUBAGENT_FAILED",
            "stderr": "worker detail",
        }

    monkeypatch.setattr(
        code_capabilities_module, "invoke_subagent", fake_invoke_subagent
    )
    result = asyncio.run(
        gpt_dive.code_mode(
            "await subagent_call(model='luna', task='fail', timeout=30.0)"
        )
    )["result"]
    assert result == {
        "ok": False,
        "model": "luna",
        "provider": "openai-codex",
        "error": "SUBAGENT_FAILED",
        "stderr": "worker detail",
    }


def test_subagent_call_inherits_code_mode_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    import gpt_dive

    calls: list[dict[str, object]] = []

    async def fake_invoke_subagent(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "model": kwargs["model"], "output": "WORKSPACE_OK"}

    monkeypatch.setattr(
        code_capabilities_module, "invoke_subagent", fake_invoke_subagent
    )
    code = "result = await subagent_call(model='terra', task='edit file', timeout=30.0); result['output']"
    assert asyncio.run(gpt_dive.code_mode(code, cwd=str(tmp_path))) == {
        "result": "WORKSPACE_OK"
    }
    assert calls[0]["workspace_dir"] == str(tmp_path)


def test_council_emit_is_registry_capability(monkeypatch, tmp_path: Path) -> None:

    calls: list[tuple[str, str, str | None]] = []

    def fake_emit(council_dir: str, message: str, expected_head: str | None = None):
        calls.append((council_dir, message, expected_head))
        return {"ok": True, "commit": "abc123"}

    monkeypatch.setattr(code_capabilities_module, "emit_sol_response", fake_emit)
    code = (
        f"await council_emit(council_dir={str(tmp_path)!r}, "
        'message="SOL_OK", expected_head="deadbeef")'
    )
    result = asyncio.run(code_mode(code))["result"]
    assert result == {"ok": True, "commit": "abc123"}
    assert calls == [(str(tmp_path), "SOL_OK", "deadbeef")]


def _wait_code_mode_job(execution_id: str, timeout: float = 4.0) -> dict[str, object]:
    import time

    import gpt_dive

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = asyncio.run(
            gpt_dive.code_mode(action="status", execution_id=execution_id)
        )
        if state["status"] != "running":
            return state
        time.sleep(0.03)
    raise AssertionError("background Code Mode execution did not finish")


def test_code_mode_background_lifecycle_and_stdout(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode(
                'print("BG_STDOUT")\n1 + 2',
                task={"label": "bg-lifecycle"},
            )
        )
        assert started["state"] == "working"
        assert "result" not in started

        state = _wait_code_mode_job(str(started["execution_id"]))
        assert state["status"] == "completed"
        result = asyncio.run(
            gpt_dive.code_mode(
                action="result", execution_id=str(started["execution_id"])
            )
        )
        assert result["execution_id"] == started["execution_id"]
        assert result["result"] == 3
        assert result["stdout"] == "BG_STDOUT\n"
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_background_exposes_background_flag(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode("BACKGROUND", task={"label": "bg-flag"})
        )
        _wait_code_mode_job(str(started["execution_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(
                action="result", execution_id=str(started["execution_id"])
            )
        )
        assert result["result"] is True
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_background_preserves_payload(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False

        payload = "BG_PAYLOAD ' \" ` $() <<EOF\n"
        started = asyncio.run(
            gpt_dive.code_mode(
                "PAYLOAD",
                payload=payload,
                task={"label": "bg-payload"},
            )
        )
        _wait_code_mode_job(str(started["execution_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(
                action="result", execution_id=str(started["execution_id"])
            )
        )
        assert result["result"] == payload
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_background_result_preserves_nested_subagent_failure(monkeypatch) -> None:
    import json

    import gpt_dive.app as app_module

    failure = {"ok": False, "model": "luna", "error": "SUBAGENT_FAILED"}
    envelope = {
        "v": app_module.CODE_MODE_WORKER_PROTOCOL,
        "ok": True,
        "result": {"result": failure},
    }
    monkeypatch.setattr(
        app_module.executions,
        "result",
        lambda _execution_id: {
            "execution_id": "execution",
            "ready": True,
            "status": "completed",
            "exit_code": 0,
            "stdout": json.dumps(envelope),
            "stderr": "",
        },
    )
    monkeypatch.setattr(
        app_module, "_cleanup_code_mode_request", lambda _execution_id: None
    )

    assert app_module._background_code_mode_result("execution")["result"] == failure


def test_code_mode_background_exception_is_structured(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode(
                'raise ValueError("BG_BOOM")', task={"label": "bg-error"}
            )
        )
        _wait_code_mode_job(str(started["execution_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(
                action="result", execution_id=str(started["execution_id"])
            )
        )
        assert result["exit_code"] != 0
        assert result["error"]["code"] == "background_execution_error"
        assert "BG_BOOM" in result["error"]["message"]
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_background_rejects_non_json_result(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode('float("nan")', task={"label": "bg-nonjson"})
        )
        _wait_code_mode_job(str(started["execution_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(
                action="result", execution_id=str(started["execution_id"])
            )
        )
        assert result["exit_code"] != 0
        assert result["error"]["code"] == "non_json_result"
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_background_cancel(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode(
                'x = 0\nfor _ in range(20000000):\n    x += 1\n"never"',
                task={"label": "bg-cancel"},
            )
        )
        asyncio.run(
            gpt_dive.code_mode(
                action="cancel", execution_id=str(started["execution_id"])
            )
        )
        state = _wait_code_mode_job(str(started["execution_id"]))
        assert state["status"] == "cancelled"
        payload_dir = gpt_dive.executions.root.parent / "code-mode-inputs"
        assert not list(payload_dir.glob("*.json"))
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_background_jobs_and_internal_gather_overlap(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        (tmp_path / "file_a.txt").write_text("a")
        (tmp_path / "file_b.txt").write_text("b")
        code = """
a, b = await asyncio.gather(
    read_file("file_a.txt"),
    read_file("file_b.txt"),
)
[a, b]
"""
        first = asyncio.run(
            gpt_dive.code_mode(code, cwd=str(tmp_path), task={"label": "gather-a"})
        )
        second = asyncio.run(
            gpt_dive.code_mode(code, cwd=str(tmp_path), task={"label": "gather-b"})
        )
        first_while_second_running = asyncio.run(
            gpt_dive.code_mode(action="status", execution_id=str(first["execution_id"]))
        )
        assert first_while_second_running["status"] in ("running", "completed")
        _wait_code_mode_job(str(first["execution_id"]))
        _wait_code_mode_job(str(second["execution_id"]))
        for started in (first, second):
            result = asyncio.run(
                gpt_dive.code_mode(
                    action="result", execution_id=str(started["execution_id"])
                )
            )
            assert all(
                marker in output
                for marker, output in zip(("a", "b"), result["result"], strict=True)
            )
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_task_aware_background_launch_and_task_list(tmp_path: Path) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        started = asyncio.run(
            code_mode(
                "7",
                task={"label": "task canary"},
            )
        )

        assert started["task_id"] != started["execution_id"]
        assert started["label"] == "task canary"
        assert started["state"] == "working"
        tasks = app_module.task_store.list_tasks()
        assert [task["task_id"] for task in tasks] == [started["task_id"]]
        assert tasks[0]["execution_id"] == started["execution_id"]

        listed = asyncio.run(code_mode("await task_list()"))["result"]
        listed_task = listed["tasks"][0]
        for key, value in tasks[0].items():
            assert listed_task[key] == value
        assert "status_cmd" not in tasks[0]
        assert "status_cmd" not in listed_task
        assert listed_task["status_label"] is None
        assert listed_task["elapsed_seconds"] >= 0

        _wait_code_mode_job(str(started["execution_id"]))
        result = asyncio.run(
            code_mode(action="result", execution_id=str(started["execution_id"]))
        )
        assert result["result"] == 7
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_task_collect_is_non_destructive_and_ack_preserves_execution_result(
    tmp_path: Path,
) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        started = asyncio.run(
            code_mode(
                "x = 0\nfor _ in range(5000000):\n    x += 1\n21",
                task={"label": "collect"},
            )
        )
        task_id = str(started["task_id"])
        execution_id = str(started["execution_id"])

        early = asyncio.run(code_mode("await task_collect(PAYLOAD)", payload=task_id))[
            "result"
        ]
        assert early["ready"] is False
        assert early["task"]["state"] == "working"
        with pytest.raises(MontyRuntimeError, match="terminal or lost"):
            asyncio.run(code_mode("await task_ack(PAYLOAD)", payload=task_id))

        _wait_code_mode_job(execution_id)
        first = asyncio.run(code_mode("await task_collect(PAYLOAD)", payload=task_id))[
            "result"
        ]
        second = asyncio.run(code_mode("await task_collect(PAYLOAD)", payload=task_id))[
            "result"
        ]
        assert first["ready"] is True
        assert first["task"]["state"] == "completed"
        assert first["result"]["result"] == 21
        assert second == first

        acked = asyncio.run(code_mode("await task_ack(PAYLOAD)", payload=task_id))[
            "result"
        ]
        assert acked == {"task_id": task_id, "state": "completed", "acked": True}
        assert asyncio.run(code_mode("await task_list()"))["result"] == {"tasks": []}

        raw = asyncio.run(code_mode(action="result", execution_id=execution_id))
        assert raw["result"] == 21
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_task_refresh_uses_worker_failure_semantics(tmp_path: Path) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        started = asyncio.run(
            code_mode('raise ValueError("TASK_FAIL")', task={"label": "failure"})
        )
        task_id = str(started["task_id"])
        _wait_code_mode_job(str(started["execution_id"]))

        listed = asyncio.run(code_mode("await task_list()"))["result"]["tasks"]
        assert listed[0]["state"] == "failed"
        collected = asyncio.run(
            code_mode("await task_collect(PAYLOAD)", payload=task_id)
        )["result"]
        assert collected["ready"] is True
        assert collected["task"]["state"] == "failed"
        assert collected["result"]["error"]["code"] == "background_execution_error"
        assert "TASK_FAIL" in collected["result"]["error"]["message"]
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_task_cancel_forwards_and_becomes_cancelled(tmp_path: Path) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        started = asyncio.run(
            code_mode(
                "x = 0\nfor _ in range(20000000):\n    x += 1\nx",
                task={"label": "cancel"},
            )
        )
        task_id = str(started["task_id"])
        execution_id = str(started["execution_id"])

        asyncio.run(code_mode("await task_cancel(PAYLOAD)", payload=task_id))
        asyncio.run(code_mode("await task_cancel(PAYLOAD)", payload=task_id))
        _wait_code_mode_job(execution_id)

        listed = asyncio.run(code_mode("await task_list()"))["result"]["tasks"]
        assert listed[0]["state"] == "cancelled"
        collected = asyncio.run(
            code_mode("await task_collect(PAYLOAD)", payload=task_id)
        )["result"]
        assert collected["ready"] is True
        assert collected["task"]["state"] == "cancelled"
        assert collected["result"]["error"]["code"] == "background_cancelled"
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_terminal_task_becomes_lost_when_execution_disappears(tmp_path: Path) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        started = asyncio.run(code_mode("42", task={"label": "lost"}))
        task_id = str(started["task_id"])
        execution_id = str(started["execution_id"])
        _wait_code_mode_job(execution_id)

        collected = asyncio.run(
            code_mode("await task_collect(PAYLOAD)", payload=task_id)
        )["result"]
        assert collected["task"]["state"] == "completed"

        shutil.rmtree(gpt_dive.executions.root / execution_id)
        listed = asyncio.run(code_mode("await task_list()"))["result"]["tasks"]
        assert listed[0]["state"] == "lost"

        unavailable = asyncio.run(
            code_mode("await task_collect(PAYLOAD)", payload=task_id)
        )["result"]
        assert unavailable["ready"] is False
        assert unavailable["unavailable"] is True

        acked = asyncio.run(code_mode("await task_ack(PAYLOAD)", payload=task_id))[
            "result"
        ]
        assert acked == {"task_id": task_id, "state": "lost", "acked": True}
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_task_aware_launch_derives_status_and_elapsed(tmp_path: Path) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        started = asyncio.run(
            code_mode(
                "x = 0\nfor _ in range(20000000):\n    x += 1\nx",
                task={
                    "label": "AGY worker",
                    "status": "TODOS 3/9",
                },
            )
        )
        task_id = str(started["task_id"])
        listed = asyncio.run(code_mode("await task_list()"))["result"]["tasks"]
        task = listed[0]
        assert task["status"] == "TODOS 3/9"
        assert task["status_label"] == "TODOS 3/9"
        assert isinstance(task["elapsed_seconds"], int)
        assert task["elapsed_seconds"] >= 0
        assert "duration" not in task
        raw = app_module.task_store.get(task_id)
        assert "status_cmd" not in raw
        assert "status_label" not in raw
        assert "elapsed_seconds" not in raw

        asyncio.run(code_mode("await task_cancel(PAYLOAD)", payload=task_id))
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_task_status_display_uses_static_status_without_changing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gpt_dive.task_store import TaskStore

    original_task_store = app_module.task_store
    try:
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")
        app_module.task_store.create(execution_id="a", label="static", status="STATIC")
        app_module.task_store.create(execution_id="b", label="fail", status="FAILBACK")
        monkeypatch.setattr(task_runtime_module, "refresh_task", lambda rt, task: task)

        tasks = asyncio.run(code_mode("await task_list()"))["result"]["tasks"]
        assert [task["status_label"] for task in tasks] == [
            "STATIC",
            "FAILBACK",
        ]
        assert all(task["state"] == "working" for task in tasks)
    finally:
        app_module.task_store = original_task_store


def test_task_launch_ignores_or_rejects_status_cmd(tmp_path: Path) -> None:
    import gpt_dive
    from gpt_dive.task_store import TaskStore

    original_task_store = app_module.task_store
    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(tmp_path / "tasks.sqlite3")

        canary = tmp_path / "canary.txt"
        started = asyncio.run(
            code_mode(
                "x = 0\nfor _ in range(5000000):\n    x += 1\nx",
                task={
                    "label": "canary",
                    "status_cmd": f"touch {canary}",
                    "status": "SAFE",
                },
            )
        )
        tasks = asyncio.run(code_mode("await task_list()"))["result"]["tasks"]
        assert not canary.exists(), "status_cmd must NEVER be executed via shell!"
        assert tasks[0]["status"] == "SAFE"
        assert tasks[0]["status_label"] == "SAFE"
        _wait_code_mode_job(str(started["execution_id"]))
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_task_launch_validation() -> None:
    with pytest.raises(ValueError, match=r"task\.label must not be empty"):
        asyncio.run(code_mode("1", task={"label": "   "}))
    with pytest.raises(ValueError, match="task is only valid when launching"):
        asyncio.run(
            code_mode(action="status", execution_id="x", task={"label": "nope"})
        )


def test_code_mode_cancels_execution_when_task_persistence_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    cancelled: list[str] = []

    class FailingTaskStore:
        def create(self, **_kwargs):
            raise OSError("task db unavailable")

    real_cancel = app_module.executions.cancel

    def record_cancel(execution_id: str):
        cancelled.append(execution_id)
        return real_cancel(execution_id)

    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        app_module.task_store = FailingTaskStore()  # type: ignore[assignment]
        monkeypatch.setattr(app_module.executions, "cancel", record_cancel)

        with pytest.raises(OSError, match="task db unavailable"):
            asyncio.run(
                code_mode(
                    "1",
                    task={"label": "fails"},
                )
            )

        assert len(cancelled) == 1
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_code_mode_validates_background_lifecycle_fields() -> None:
    import pytest

    import gpt_dive

    with pytest.raises(ValueError, match="requires code"):
        asyncio.run(gpt_dive.code_mode())
    with pytest.raises(ValueError, match="mutually exclusive"):
        asyncio.run(gpt_dive.code_mode("1 + 2", action="status", execution_id="x"))
    with pytest.raises(ValueError, match="requires execution_id"):
        asyncio.run(gpt_dive.code_mode(action="status"))
    with pytest.raises(ValueError, match="unsupported code_mode action"):
        asyncio.run(gpt_dive.code_mode(action="future", execution_id="x"))  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match="payload is only valid"):
        asyncio.run(
            gpt_dive.code_mode(action="status", execution_id="x", payload="payload")
        )


def test_harness_filesystem_capabilities_work_at_code_mode_seam() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        workspace = Path(td)
        (workspace / "input.txt").write_text("alpha\nbeta\n")
        code = r"""
read = await read_file("input.txt", limit=1)
listing = await list_directory(".")
search = await search_files("beta")
found = await find_files("*.txt")
info = await file_info("input.txt")
created = await create_directory("nested")
written = await write_file("nested/out.txt", "one\n")
edited = await edit_file("nested/out.txt", "one", "two")
{
    "read": read,
    "listing": listing,
    "search": search,
    "found": found,
    "info": info,
    "created": created,
    "written": written,
    "edited": edited,
}
"""
        result = asyncio.run(code_mode(code, cwd=str(workspace)))["result"]
        assert "1\talpha" in result["read"]
        assert "input.txt" in result["listing"]
        assert "input.txt:2:beta" in result["search"]
        assert "input.txt" in result["found"]
        assert "type: file" in result["info"]
        assert result["created"].endswith("/nested")
        assert "Wrote" in result["written"]
        assert "/nested/out.txt" in result["edited"]
        assert (workspace / "nested" / "out.txt").read_text() == "two\n"


def test_code_mode_reads_anywhere_outside_home(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("visible\n")

    result = asyncio.run(
        code_mode('await read_file("../outside.txt", limit=1)', cwd=str(workspace))
    )["result"]
    assert "1\tvisible" in result

    direct = asyncio.run(
        code_mode(
            f"from pathlib import Path\nPath({str(target)!r}).read_text()",
            cwd=str(workspace),
        )
    )["result"]
    assert direct == "visible\n"


def test_code_mode_missing_tilde_path_reports_resolved_target() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        workspace = Path(td)
        missing = workspace / "missing.txt"
        requested = f"~/{missing.relative_to(Path.home())}"

        with pytest.raises(Exception) as exc_info:
            asyncio.run(code_mode(f"await read_file({requested!r})"))

        assert str(missing.resolve()) in str(exc_info.value)


def test_code_mode_writes_outside_home(tmp_path: Path) -> None:
    harness_target = tmp_path / "outside-write.txt"
    direct_target = tmp_path / "outside-direct-write.txt"

    result = asyncio.run(
        code_mode(f'await write_file({str(harness_target)!r}, "allowed")')
    )["result"]
    assert "Wrote" in result
    assert harness_target.read_text() == "allowed"

    direct = asyncio.run(
        code_mode(
            f"from pathlib import Path\nPath({str(direct_target)!r}).write_text('allowed')"
        )
    )["result"]
    assert direct == len("allowed")
    assert direct_target.read_text() == "allowed"


def test_code_mode_blocks_secret_reads_and_writes(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret\n")

    with pytest.raises(Exception, match="denied by pattern"):
        asyncio.run(code_mode(f"await read_file({str(secret)!r})"))

    with pytest.raises(Exception, match="Credential/secret path is blocked"):
        asyncio.run(
            code_mode(f"from pathlib import Path\nPath({str(secret)!r}).read_text()")
        )

    with pytest.raises(Exception, match="denied by pattern"):
        asyncio.run(code_mode(f'await write_file({str(secret)!r}, "blocked")'))
    with pytest.raises(Exception, match="Credential/secret path is blocked"):
        asyncio.run(
            code_mode(
                f"from pathlib import Path\nPath({str(secret)!r}).write_text('blocked')"
            )
        )

    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        home_secret = Path(td) / ".env"
        with pytest.raises(Exception, match="denied by pattern"):
            asyncio.run(code_mode(f'await write_file({str(home_secret)!r}, "blocked")'))
        with pytest.raises(Exception, match="Credential/secret path is blocked"):
            asyncio.run(
                code_mode(
                    f"from pathlib import Path\nPath({str(home_secret)!r}).write_text('blocked')"
                )
            )
        assert not home_secret.exists()


def test_repo_search_relative_path_inherits_code_mode_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def fake_search_repo(**kwargs):
        return kwargs

    monkeypatch.setattr(code_capabilities_module, "search_repo", fake_search_repo)
    result = asyncio.run(
        code_mode(
            "await repo_search(query='needle', path='src')",
            cwd=str(workspace),
        )
    )["result"]
    assert result["path"] == str((workspace / "src").resolve())


def test_harness_filesystem_write_rejects_stale_expected_hash() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        workspace = Path(td)
        target = workspace / "target.txt"
        stale_hash = hashlib.sha256(b"original").hexdigest()[:12]
        target.write_text("external")
        code = (
            f'await write_file("target.txt", "changed", expected_hash={stale_hash!r})'
        )
        with pytest.raises(
            Exception, match=r"Conflict: file .*target\.txt.* has changed"
        ):
            asyncio.run(code_mode(code, cwd=str(workspace)))
        assert target.read_text() == "external"


def test_harness_filesystem_edit_rejects_stale_expected_hash() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        workspace = Path(td)
        target = workspace / "target.txt"
        stale_hash = hashlib.sha256(b"original").hexdigest()[:12]
        target.write_text("external")
        code = f'await edit_file("target.txt", "external", "changed", expected_hash={stale_hash!r})'
        with pytest.raises(
            Exception, match=r"Conflict: file .*target\.txt.* has changed"
        ):
            asyncio.run(code_mode(code, cwd=str(workspace)))
        assert target.read_text() == "external"


def test_code_mode_result_passthrough_for_raw_shell_execution(tmp_path: Path) -> None:
    import time

    import gpt_dive

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    try:
        gpt_dive.executions.root = tmp_path / "executions"
        gpt_dive.executions.root.mkdir()
        gpt_dive.executions._systemd_available = False
        started = gpt_dive.executions.start("printf RAW_PASSTHROUGH_OK", timeout=5)
        execution_id = str(started["execution_id"])
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if gpt_dive.executions.status(execution_id)["status"] != "running":
                break
            time.sleep(0.02)
        result = asyncio.run(code_mode(action="result", execution_id=execution_id))
        assert result["exit_code"] == 0
        assert result["stdout"] == "RAW_PASSTHROUGH_OK"
        assert "error" not in result
    finally:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd
