from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import pytest
from pydantic_monty import MontyRuntimeError, MontyTypingError

import gpt_dive.app as app_module
from gpt_dive import code_mode


def test_code_mode_returns_expression_result() -> None:
    assert asyncio.run(code_mode("1 + 2")) == {"result": 3}


def test_code_mode_can_read_and_write_local_filesystem() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        target = Path(td) / "monty-rw.txt"
        code = f"""\nfrom pathlib import Path\np = Path({str(target)!r})\np.write_text("DIVE_RW_OK")\np.read_text()\n"""
        assert asyncio.run(code_mode(code)) == {"result": "DIVE_RW_OK"}
        assert target.read_text() == "DIVE_RW_OK"


def test_run_command_works_and_preserves_guard_bin() -> None:
    code = """\
ok = await run_command("printf 'RUN_COMMAND_OK\\n'")
rerouted = await run_command("python --version")
old_python = await run_command("python3.10 --version")
{"ok": ok, "rerouted": rerouted, "old_python": old_python}
"""
    result = asyncio.run(code_mode(code))["result"]
    assert "RUN_COMMAND_OK" in result["ok"]
    assert "Python 3.14" in result["rerouted"]
    assert "auto-reroute" in result["rerouted"]
    assert "Old Python" in result["old_python"]
    assert "[exit code: 2]" in result["old_python"]


def test_run_command_allows_normal_cleanup_commands(tmp_path: Path) -> None:
    target = tmp_path / "cleanup-me.txt"
    target.write_text("temporary")
    result = asyncio.run(code_mode("await run_command(PAYLOAD)", payload=f"rm {target}"))["result"]
    assert result == "(no output)"
    assert not target.exists()


def test_run_command_strips_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-run-command")
    monkeypatch.setenv("MINIMAX_API_KEY", "must-not-reach-run-command")
    monkeypatch.setenv("AIAPIFLOW_CLAUDE_KEY", "must-not-reach-run-command")
    code = r'''
result = await run_command(
    "printf '%s|%s|%s' \"$OPENAI_API_KEY\" \"$MINIMAX_API_KEY\" \"$AIAPIFLOW_CLAUDE_KEY\""
)
result
'''
    result = asyncio.run(code_mode(code))["result"]
    assert "||" in result
    assert "must-not-reach-run-command" not in result


def test_code_mode_payload_can_carry_multiline_shell() -> None:
    payload = "printf 'PAYLOAD_OK\n'\nprintf 'SECOND_LINE\n'"
    code = "await run_command(PAYLOAD)"
    result = asyncio.run(code_mode(code, payload=payload))["result"]
    assert "PAYLOAD_OK" in result
    assert "SECOND_LINE" in result


def test_code_mode_payload_type_stub_has_no_input_alias() -> None:
    from gpt_dive.code_runtime import CallableRegistry

    stubs = CallableRegistry().type_check_stubs(include_payload=True)
    assert "PAYLOAD: str" in stubs
    assert "BACKGROUND: bool" in stubs
    assert "INPUT: str" not in stubs


def test_code_mode_exposes_foreground_flag() -> None:
    assert asyncio.run(code_mode("BACKGROUND")) == {"result": False}


def test_run_command_calls_can_overlap() -> None:
    code = """\ncmd = "date +%s%N; sleep 0.35; date +%s%N"\na, b = await asyncio.gather(run_command(cmd), run_command(cmd))\n[a, b]\n"""
    outputs = asyncio.run(code_mode(code))["result"]
    intervals = []
    for output in outputs:
        numbers = [int(part) for part in output.split() if part.isdigit()]
        intervals.append((numbers[0], numbers[1]))
    starts = [start for start, _ in intervals]
    ends = [end for _, end in intervals]
    assert max(starts) < min(ends)


def test_run_command_output_is_bounded() -> None:
    code = "await run_command(\"yes alpha | head -n 20000\")"
    result = asyncio.run(code_mode(code))["result"]
    assert len(result) <= 50_000
    assert "alpha" in result


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
        "run_command",
        "start_command",
        "check_command",
        "stop_command",
        "agy_worker",
        "subagent_call",
        "bare",
        "m3_evidence",
        "repo_search",
        "council_emit",
        "gz64",
    }
    assert "offset" in result["read_file"]["signature"]
    assert "expected_hash" in result["write_file"]["signature"]
    assert "expected_hash" in result["edit_file"]["signature"]
    assert "timeout_seconds" in result["run_command"]["signature"]
    assert "conversation_id" in result["agy_worker"]["signature"]
    assert result["read_file"]["description"].startswith(
        "Read a text file with line numbers."
    )
    assert result["run_command"]["description"].startswith("Execute a shell command")


def test_normal_search_rejects_broad_root_paths(tmp_path: Path) -> None:
    with pytest.raises(MontyRuntimeError, match="search_files refuses broad recursive search rooted at /"):
        asyncio.run(code_mode("await search_files('needle', path='/')"))
    with pytest.raises(MontyRuntimeError, match="find_files refuses broad recursive search rooted at /mnt/c"):
        asyncio.run(code_mode("await find_files('*', path='/mnt/c')"))
    with pytest.raises(MontyRuntimeError, match="repo_search refuses broad recursive search rooted at /"):
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


def test_gz64_capability_round_trip() -> None:
    import base64
    import gzip

    command = "printf 'GZ64_EXEC_OK\\n'"
    payload = base64.b64encode(
        gzip.compress(command.encode("utf-8"), compresslevel=1, mtime=0)
    ).decode("ascii")
    code = f"await gz64({payload!r})"
    result = asyncio.run(code_mode(code))["result"]
    assert result["returncode"] == 0
    assert result["stdout"] == "GZ64_EXEC_OK\n"


def test_subagent_call_is_registry_capability(monkeypatch) -> None:
    import gpt_dive
    import gpt_dive.app as app_module

    calls: list[dict[str, object]] = []

    async def fake_invoke_subagent(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "model": kwargs["model"],
            "output": "SUBAGENT_OK",
        }

    monkeypatch.setattr(app_module, "invoke_subagent", fake_invoke_subagent)
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
    import gpt_dive.app as app_module

    calls: list[dict[str, object]] = []

    async def fake_invoke_m3_evidence(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "known": ["k"], "missing": [], "conflicts": [], "queries": [], "done": True}

    monkeypatch.setattr(app_module, "invoke_m3_evidence", fake_invoke_m3_evidence)
    code = "result = await m3_evidence(question='q', evidence='e', max_queries=2, timeout=30.0); result['done']"
    assert asyncio.run(gpt_dive.code_mode(code)) == {"result": True}
    assert calls == [{
        "question": "q",
        "evidence": "e",
        "round_number": 1,
        "max_rounds": 3,
        "max_queries": 2,
        "timeout": 30.0,
        "output_tokens_limit": 2048,
    }]


def test_bare_is_registry_capability(monkeypatch) -> None:
    import gpt_dive
    import gpt_dive.app as app_module

    calls: list[dict[str, object]] = []

    async def fake_invoke_bare(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "model": kwargs["model"], "output": "BARE_OK"}

    monkeypatch.setattr(app_module, "invoke_bare", fake_invoke_bare)
    code = (
        "result = await bare(provider='aiapiflow', model='claude-opus-5', "
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
    import gpt_dive.app as app_module

    calls: list[dict[str, object]] = []

    async def fake_search_repo(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "engine": "probe", "count": 1, "results": []}

    monkeypatch.setattr(app_module, "search_repo", fake_search_repo)
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
    import gpt_dive.app as app_module

    async def fake_invoke_subagent(**kwargs):
        return {
            "ok": False,
            "model": kwargs["model"],
            "provider": "openai-codex",
            "error": "SUBAGENT_FAILED",
            "stderr": "worker detail",
        }

    monkeypatch.setattr(app_module, "invoke_subagent", fake_invoke_subagent)
    result = asyncio.run(
        gpt_dive.code_mode("await subagent_call(model='luna', task='fail', timeout=30.0)")
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
    import gpt_dive.app as app_module

    calls: list[dict[str, object]] = []

    async def fake_invoke_subagent(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "model": kwargs["model"], "output": "WORKSPACE_OK"}

    monkeypatch.setattr(app_module, "invoke_subagent", fake_invoke_subagent)
    code = "result = await subagent_call(model='terra', task='edit file', timeout=30.0); result['output']"
    assert asyncio.run(gpt_dive.code_mode(code, cwd=str(tmp_path))) == {
        "result": "WORKSPACE_OK"
    }
    assert calls[0]["workspace_dir"] == str(tmp_path)


def test_council_emit_is_registry_capability(monkeypatch, tmp_path: Path) -> None:
    import gpt_dive.app as app_module

    calls: list[tuple[str, str, str | None]] = []

    def fake_emit(council_dir: str, message: str, expected_head: str | None = None):
        calls.append((council_dir, message, expected_head))
        return {"ok": True, "commit": "abc123"}

    monkeypatch.setattr(app_module, "emit_sol_response", fake_emit)
    code = (
        f"await council_emit(council_dir={str(tmp_path)!r}, "
        'message="SOL_OK", expected_head="deadbeef")'
    )
    result = asyncio.run(code_mode(code))["result"]
    assert result == {"ok": True, "commit": "abc123"}
    assert calls == [(str(tmp_path), "SOL_OK", "deadbeef")]


def _wait_code_mode_job(job_id: str, timeout: float = 4.0) -> dict[str, object]:
    import time

    import gpt_dive

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = asyncio.run(gpt_dive.code_mode(action="status", job_id=job_id))
        if state["status"] != "running":
            return state
        time.sleep(0.03)
    raise AssertionError("background Code Mode job did not finish")


def test_code_mode_background_lifecycle_and_stdout(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode(
                'await run_command("sleep 0.15")\nprint("BG_STDOUT")\n1 + 2',
                background=True,
            )
        )
        assert started["status"] == "running"
        assert "result" not in started

        state = _wait_code_mode_job(str(started["job_id"]))
        assert state["status"] == "completed"
        result = asyncio.run(
            gpt_dive.code_mode(action="result", job_id=str(started["job_id"]))
        )
        assert result["job_id"] == started["job_id"]
        assert result["result"] == 3
        assert result["stdout"] == "BG_STDOUT\n"
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_code_mode_background_exposes_background_flag(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False

        started = asyncio.run(gpt_dive.code_mode("BACKGROUND", background=True))
        _wait_code_mode_job(str(started["job_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(action="result", job_id=str(started["job_id"]))
        )
        assert result["result"] is True
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_code_mode_background_preserves_payload(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False

        payload = "BG_PAYLOAD ' \" ` $() <<EOF\n"
        started = asyncio.run(
            gpt_dive.code_mode(
                'PAYLOAD',
                payload=payload,
                background=True,
            )
        )
        _wait_code_mode_job(str(started["job_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(action="result", job_id=str(started["job_id"]))
        )
        assert result["result"] == payload
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_background_result_preserves_nested_subagent_failure(monkeypatch) -> None:
    import json

    import gpt_dive.app as app_module

    failure = {"ok": False, "model": "luna", "error": "SUBAGENT_FAILED"}
    envelope = {"v": app_module.CODE_MODE_WORKER_PROTOCOL, "ok": True, "result": {"result": failure}}
    monkeypatch.setattr(
        app_module.jobs,
        "result",
        lambda _job_id: {
            "job_id": "job",
            "ready": True,
            "status": "completed",
            "exit_code": 0,
            "stdout": json.dumps(envelope),
            "stderr": "",
        },
    )
    monkeypatch.setattr(app_module, "_cleanup_code_mode_request", lambda _job_id: None)

    assert app_module._background_code_mode_result("job")["result"] == failure


def test_code_mode_background_exception_is_structured(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode('raise ValueError("BG_BOOM")', background=True)
        )
        _wait_code_mode_job(str(started["job_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(action="result", job_id=str(started["job_id"]))
        )
        assert result["exit_code"] != 0
        assert result["error"]["code"] == "background_execution_error"
        assert "BG_BOOM" in result["error"]["message"]
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_code_mode_background_rejects_non_json_result(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False

        started = asyncio.run(gpt_dive.code_mode('float("nan")', background=True))
        _wait_code_mode_job(str(started["job_id"]))
        result = asyncio.run(
            gpt_dive.code_mode(action="result", job_id=str(started["job_id"]))
        )
        assert result["exit_code"] != 0
        assert result["error"]["code"] == "non_json_result"
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_code_mode_background_cancel(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False

        started = asyncio.run(
            gpt_dive.code_mode(
                'await run_command("sleep 30")\n"never"',
                background=True,
            )
        )
        asyncio.run(gpt_dive.code_mode(action="cancel", job_id=str(started["job_id"])))
        state = _wait_code_mode_job(str(started["job_id"]))
        assert state["status"] == "cancelled"
        payload_dir = gpt_dive.jobs.root.parent / "code-mode-inputs"
        assert not list(payload_dir.glob("*.json"))
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_code_mode_background_jobs_and_internal_gather_overlap(tmp_path: Path) -> None:
    import gpt_dive

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path / "jobs"
        gpt_dive.jobs.root.mkdir()
        gpt_dive.jobs._systemd_available = False
        code = """
import asyncio
a, b = await asyncio.gather(
    run_command("sleep 0.25; printf a"),
    run_command("sleep 0.25; printf b"),
)
[a, b]
"""
        first = asyncio.run(gpt_dive.code_mode(code, background=True))
        second = asyncio.run(gpt_dive.code_mode(code, background=True))
        first_while_second_running = asyncio.run(
            gpt_dive.code_mode(action="status", job_id=str(first["job_id"]))
        )
        assert first_while_second_running["status"] == "running"
        _wait_code_mode_job(str(first["job_id"]))
        _wait_code_mode_job(str(second["job_id"]))
        for started in (first, second):
            result = asyncio.run(
                gpt_dive.code_mode(action="result", job_id=str(started["job_id"]))
            )
            assert all(marker in output for marker, output in zip(("a", "b"), result["result"], strict=True))
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_code_mode_validates_background_lifecycle_fields() -> None:
    import pytest

    import gpt_dive

    with pytest.raises(ValueError, match="requires code"):
        asyncio.run(gpt_dive.code_mode())
    with pytest.raises(ValueError, match="mutually exclusive"):
        asyncio.run(gpt_dive.code_mode("1 + 2", action="status", job_id="x"))
    with pytest.raises(ValueError, match="requires job_id"):
        asyncio.run(gpt_dive.code_mode(action="status"))
    with pytest.raises(ValueError, match="unsupported code_mode action"):
        asyncio.run(gpt_dive.code_mode(action="future", job_id="x"))
    with pytest.raises(ValueError, match="payload is only valid"):
        asyncio.run(gpt_dive.code_mode(action="status", job_id="x", payload="payload"))


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

    monkeypatch.setattr(app_module, "search_repo", fake_search_repo)
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
        code = f'await write_file("target.txt", "changed", expected_hash={stale_hash!r})'
        with pytest.raises(Exception, match=r"Conflict: file .*target\.txt.* has changed"):
            asyncio.run(code_mode(code, cwd=str(workspace)))
        assert target.read_text() == "external"


def test_harness_filesystem_edit_rejects_stale_expected_hash() -> None:
    with tempfile.TemporaryDirectory(dir=Path.home()) as td:
        workspace = Path(td)
        target = workspace / "target.txt"
        stale_hash = hashlib.sha256(b"original").hexdigest()[:12]
        target.write_text("external")
        code = f'await edit_file("target.txt", "external", "changed", expected_hash={stale_hash!r})'
        with pytest.raises(Exception, match=r"Conflict: file .*target\.txt.* has changed"):
            asyncio.run(code_mode(code, cwd=str(workspace)))
        assert target.read_text() == "external"


def test_harness_shell_run_command_uses_workspace_guard_and_strips_provider_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-shell")
    monkeypatch.setenv("MINIMAX_API_KEY", "must-not-reach-shell")
    monkeypatch.setenv("AIAPIFLOW_CLAUDE_KEY", "must-not-reach-shell")
    code = r"""
pwd = await run_command("pwd")
secret = await run_command("printf '%s|%s|%s' \"$OPENAI_API_KEY\" \"$MINIMAX_API_KEY\" \"$AIAPIFLOW_CLAUDE_KEY\"")
python = await run_command("python --version")
{"pwd": pwd, "secret": secret, "python": python}
"""
    result = asyncio.run(code_mode(code, cwd=str(tmp_path)))["result"]
    assert str(tmp_path) in result["pwd"]
    assert "must-not-reach-shell" not in result["secret"]
    assert "[stdout]\n||" in result["secret"]
    assert "Python 3.14" in result["python"]
    assert "auto-reroute" in result["python"]


def test_harness_shell_background_start_check_stop(tmp_path: Path) -> None:
    code = r"""
started = await start_command("bash -c 'echo READY; sleep 30'")
command_id = started.split("ID: ", 1)[1]
await run_command("sleep 0.1")
checked = await check_command(command_id)
stopped = await stop_command(command_id)
{"started": started, "checked": checked, "stopped": stopped}
"""
    result = asyncio.run(code_mode(code, cwd=str(tmp_path)))["result"]
    assert "ID: " in result["started"]
    assert "READY" in result["checked"]
    assert "[status: running]" in result["checked"]
    assert "[stopped]" in result["stopped"]


def test_harness_shell_background_is_cleaned_at_code_mode_end(tmp_path: Path) -> None:
    code = r"""
started = await start_command("bash -c 'echo $$ > shell.pid; exec sleep 30'")
await run_command("sleep 0.1")
started
"""
    asyncio.run(code_mode(code, cwd=str(tmp_path)))
    pid = int((tmp_path / "shell.pid").read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_harness_shell_direct_registry_preserves_output_cap() -> None:
    result = asyncio.run(
        code_mode(
            'r = await run_command(PAYLOAD)\n{"length": len(r), "prefix": r[:80]}',
            payload="python -c \"print('x'*60000)\"",
        )
    )["result"]
    assert result["length"] == 50_000
    assert result["prefix"].startswith("[... output truncated, showing last ")
