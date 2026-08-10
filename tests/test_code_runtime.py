from __future__ import annotations

import asyncio
from pathlib import Path

from gpt_dive import code_mode


def test_code_mode_returns_expression_result() -> None:
    assert asyncio.run(code_mode("1 + 2")) == {"result": 3}


def test_code_mode_can_read_and_write_local_filesystem(tmp_path: Path) -> None:
    target = tmp_path / "monty-rw.txt"
    code = f"""\nfrom pathlib import Path\np = Path({str(target)!r})\np.write_text("DIVE_RW_OK")\np.read_text()\n"""
    assert asyncio.run(code_mode(code)) == {"result": "DIVE_RW_OK"}
    assert target.read_text() == "DIVE_RW_OK"


def test_local_exec_works_and_preserves_guard_bin() -> None:
    code = """\nok = await local_exec(command="printf 'LOCAL_EXEC_OK\\n'")\nblocked = await local_exec(command="python --version")\n{"ok": ok, "blocked": blocked}\n"""
    result = asyncio.run(code_mode(code))["result"]
    assert result["ok"]["exit_code"] == 0
    assert result["ok"]["stdout"] == "LOCAL_EXEC_OK\n"
    assert result["blocked"]["exit_code"] != 0
    assert "prohibited" in result["blocked"]["stderr"]


def test_local_exec_calls_can_overlap() -> None:
    code = """\nimport asyncio\ncmd = "date +%s%N; sleep 0.35; date +%s%N"\na, b = await asyncio.gather(local_exec(command=cmd), local_exec(command=cmd))\n[a["stdout"], b["stdout"]]\n"""
    outputs = asyncio.run(code_mode(code))["result"]
    intervals = [tuple(map(int, output.split())) for output in outputs]
    starts = [start for start, _ in intervals]
    ends = [end for _, end in intervals]
    assert max(starts) < min(ends)


def test_large_local_exec_output_can_be_aggregated_before_return(
    tmp_path: Path,
) -> None:
    source = tmp_path / "large.txt"
    source.write_text("alpha\n" * 20_000)
    code = f"""\nr = await local_exec(command="cat {source}")\n{{"bytes": len(r["stdout"]), "lines": r["stdout"].count("\\n")}}\n"""
    result = asyncio.run(code_mode(code))
    assert result == {"result": {"bytes": 120_000, "lines": 20_000}}
    assert "alpha" not in str(result)


def test_local_start_reuses_job_manager_and_default_cwd(
    monkeypatch, tmp_path: Path
) -> None:
    import gpt_dive

    calls: list[tuple[str, str | None, float]] = []

    def fake_start(
        command: str, cwd: str | None = None, timeout: float = 600.0
    ) -> dict[str, object]:
        calls.append((command, cwd, timeout))
        return {"job_id": f"job-{command}", "status": "running"}

    monkeypatch.setattr(gpt_dive.jobs, "start", fake_start)
    code = """\nimport asyncio\na, b = await asyncio.gather(\n    local_start(command="first", timeout=11),\n    local_start(command="second"),\n)\n[a["job_id"], b["job_id"]]\n"""

    assert asyncio.run(gpt_dive.code_mode(code, cwd=str(tmp_path))) == {
        "result": ["job-first", "job-second"]
    }
    assert sorted(calls) == sorted(
        [
            ("first", str(tmp_path), 11),
            ("second", str(tmp_path), 600.0),
        ]
    )


def test_capabilities_are_runtime_discoverable() -> None:
    result = asyncio.run(code_mode("CAPABILITIES"))["result"]
    assert set(result) == {
        "local_exec",
        "local_start",
        "local_status",
        "local_result",
        "local_cancel",
        "subagent_call",
    }
    assert "signature" in result["local_start"]
    assert "durable" in result["local_start"]["description"].lower()


def test_local_job_lifecycle_can_aggregate_without_raw_output(monkeypatch) -> None:
    import gpt_dive

    monkeypatch.setattr(
        gpt_dive.jobs,
        "status",
        lambda job_id: {"job_id": job_id, "status": "completed"},
    )
    monkeypatch.setattr(
        gpt_dive.jobs,
        "result",
        lambda job_id: {
            "job_id": job_id,
            "status": "completed",
            "exit_code": 0 if job_id == "ok" else 2,
            "stdout": "RAW_OUTPUT\n" * 10_000,
            "stderr": "",
        },
    )
    code = """\nimport asyncio\nids = ["ok", "bad"]\nstatuses = await asyncio.gather(*[local_status(job_id=x) for x in ids])\nresults = await asyncio.gather(*[local_result(job_id=x) for x in ids])\n{\n    "statuses": {x["job_id"]: x["status"] for x in statuses},\n    "failed": [x["job_id"] for x in results if x["exit_code"] != 0],\n}\n"""
    result = asyncio.run(gpt_dive.code_mode(code))
    assert result == {
        "result": {
            "statuses": {"ok": "completed", "bad": "completed"},
            "failed": ["bad"],
        }
    }
    assert "RAW_OUTPUT" not in str(result)


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
        }
    ]


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
                'await local_exec(command="sleep 0.15")\nprint("BG_STDOUT")\n1 + 2',
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
                'await local_exec(command="sleep 30")\n"never"',
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
    local_exec(command="sleep 0.25; printf a"),
    local_exec(command="sleep 0.25; printf b"),
)
[a["stdout"], b["stdout"]]
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
            assert result["result"] == ["a", "b"]
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
