from __future__ import annotations

import asyncio
from pathlib import Path

from gpt_dive import code_mode


def test_code_mode_returns_expression_result() -> None:
    assert asyncio.run(code_mode("1 + 2")) == {"result": 3}


def test_code_mode_can_read_and_write_local_filesystem(tmp_path: Path) -> None:
    target = tmp_path / "monty-rw.txt"
    code = f'''\nfrom pathlib import Path\np = Path({str(target)!r})\np.write_text("DIVE_RW_OK")\np.read_text()\n'''
    assert asyncio.run(code_mode(code)) == {"result": "DIVE_RW_OK"}
    assert target.read_text() == "DIVE_RW_OK"


def test_local_exec_works_and_preserves_guard_bin() -> None:
    code = '''\nok = await local_exec(command="printf 'LOCAL_EXEC_OK\\n'")\nblocked = await local_exec(command="python --version")\n{"ok": ok, "blocked": blocked}\n'''
    result = asyncio.run(code_mode(code))["result"]
    assert result["ok"]["exit_code"] == 0
    assert result["ok"]["stdout"] == "LOCAL_EXEC_OK\n"
    assert result["blocked"]["exit_code"] != 0
    assert "prohibited" in result["blocked"]["stderr"]


def test_local_exec_calls_can_overlap() -> None:
    code = '''\nimport asyncio\ncmd = "date +%s%N; sleep 0.35; date +%s%N"\na, b = await asyncio.gather(local_exec(command=cmd), local_exec(command=cmd))\n[a["stdout"], b["stdout"]]\n'''
    outputs = asyncio.run(code_mode(code))["result"]
    intervals = [tuple(map(int, output.split())) for output in outputs]
    starts = [start for start, _ in intervals]
    ends = [end for _, end in intervals]
    assert max(starts) < min(ends)


def test_large_local_exec_output_can_be_aggregated_before_return(tmp_path: Path) -> None:
    source = tmp_path / "large.txt"
    source.write_text("alpha\n" * 20_000)
    code = f'''\nr = await local_exec(command="cat {source}")\n{{"bytes": len(r["stdout"]), "lines": r["stdout"].count("\\n")}}\n'''
    result = asyncio.run(code_mode(code))
    assert result == {"result": {"bytes": 120_000, "lines": 20_000}}
    assert "alpha" not in str(result)


def test_local_start_reuses_job_manager_and_default_cwd(monkeypatch, tmp_path: Path) -> None:
    import gpt_dive

    calls: list[tuple[str, str | None, float]] = []

    def fake_start(command: str, cwd: str | None = None, timeout: float = 600.0) -> dict[str, object]:
        calls.append((command, cwd, timeout))
        return {"job_id": f"job-{command}", "status": "running"}

    monkeypatch.setattr(gpt_dive.jobs, "start", fake_start)
    code = '''\nimport asyncio\na, b = await asyncio.gather(\n    local_start(command="first", timeout=11),\n    local_start(command="second"),\n)\n[a["job_id"], b["job_id"]]\n'''

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
    code = '''\nimport asyncio\nids = ["ok", "bad"]\nstatuses = await asyncio.gather(*[local_status(job_id=x) for x in ids])\nresults = await asyncio.gather(*[local_result(job_id=x) for x in ids])\n{\n    "statuses": {x["job_id"]: x["status"] for x in statuses},\n    "failed": [x["job_id"] for x in results if x["exit_code"] != 0],\n}\n'''
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

    calls: list[dict[str, object]] = []

    async def fake_invoke_subagent(**kwargs):
        calls.append(kwargs)
        return {
            'ok': True,
            'model': kwargs['model'],
            'output': 'SUBAGENT_OK',
        }

    monkeypatch.setattr(gpt_dive, 'invoke_subagent', fake_invoke_subagent)
    code = '''\nresult = await subagent_call(\n    model='terra',\n    task='review this',\n    timeout=17,\n    output_tokens_limit=321,\n)\n{'ok': result['ok'], 'model': result['model'], 'output': result['output']}\n'''
    assert asyncio.run(gpt_dive.code_mode(code)) == {
        'result': {'ok': True, 'model': 'terra', 'output': 'SUBAGENT_OK'}
    }
    assert calls == [
        {
            'model': 'terra',
            'task': 'review this',
            'timeout': 17,
            'output_tokens_limit': 321,
        }
    ]
