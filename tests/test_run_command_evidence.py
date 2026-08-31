from __future__ import annotations

import asyncio
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

import gpt_dive.command_runtime as command_runtime_module
from gpt_dive.command_runtime import (
    RuntimeRecord,
    materialize_run_command_stream,
    run_command,
    runtime_record,
)
from gpt_dive.execution_store import ExecutionStore, generate_execution_id


@pytest.fixture
def execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[ExecutionStore, str, RuntimeRecord]]:
    monkeypatch.setattr(
        command_runtime_module,
        "_run_command_root",
        lambda: tmp_path / "run-command",
    )
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    execution_id = generate_execution_id()
    store.create(
        execution_id=execution_id,
        kind="test",
        label="run evidence",
        cwd=str(tmp_path),
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=60.0,
        cleanup_timeout_seconds=10.0,
        request_path=tmp_path / "request.json",
        artifact_dir=tmp_path / "artifacts",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        outcome_path=tmp_path / "outcome.json",
    )
    record = runtime_record(store.get(execution_id), store=store)
    yield store, execution_id, record


def stream_path(execution_id: str, run_ordinal: int, stream: str) -> Path:
    return (
        command_runtime_module._run_command_root()
        / execution_id
        / str(run_ordinal)
        / stream
    )


def test_terminal_run_keeps_private_tmp_and_persists_same_bytes(
    tmp_path: Path,
    execution: tuple[ExecutionStore, str, RuntimeRecord],
) -> None:
    store, execution_id, record = execution

    result = asyncio.run(
        run_command(
            "printf stdout-data; printf stderr-data >&2",
            cwd=str(tmp_path),
            record=record,
        )
    )

    stdout_path = stream_path(execution_id, 1, "stdout")
    stderr_path = stream_path(execution_id, 1, "stderr")
    evidence = store.get_run_command_evidence(execution_id, 1)

    assert result["stdout"] == "stdout-data"
    assert result["stderr"] == "stderr-data"
    assert "spill_path" not in result
    assert stdout_path.read_bytes() == evidence["stdout"] == b"stdout-data"
    assert stderr_path.read_bytes() == evidence["stderr"] == b"stderr-data"
    assert stat.S_IMODE(stdout_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(stderr_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(stdout_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(stdout_path.parent.parent.stat().st_mode) == 0o700


def test_existing_tmp_recovers_even_when_sqlite_persistence_failed(
    tmp_path: Path,
    execution: tuple[ExecutionStore, str, RuntimeRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, execution_id, record = execution

    def fail_persistence(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("sqlite unavailable")

    monkeypatch.setattr(store, "persist_run_command_evidence", fail_persistence)
    result = asyncio.run(
        run_command("printf tmp-only", cwd=str(tmp_path), record=record)
    )

    assert result["exit_code"] == 0
    with pytest.raises(KeyError):
        store.get_run_command_evidence(execution_id, 1)

    path = materialize_run_command_stream(record, 1, "stdout")
    assert path == stream_path(execution_id, 1, "stdout")
    assert path.read_bytes() == b"tmp-only"

    path.unlink()
    with pytest.raises(KeyError):
        materialize_run_command_stream(record, 1, "stdout")


def test_missing_tmp_is_restored_from_sqlite_to_same_path(
    tmp_path: Path,
    execution: tuple[ExecutionStore, str, RuntimeRecord],
) -> None:
    _store, execution_id, record = execution
    asyncio.run(run_command("printf retained", cwd=str(tmp_path), record=record))
    path = stream_path(execution_id, 1, "stdout")
    path.unlink()

    restored = materialize_run_command_stream(record, 1, "stdout")

    assert restored == path
    assert restored.read_bytes() == b"retained"
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600


def test_run_ordinals_follow_invocation_order(
    tmp_path: Path,
    execution: tuple[ExecutionStore, str, RuntimeRecord],
) -> None:
    store, execution_id, record = execution

    async def scenario() -> None:
        await asyncio.gather(
            run_command("sleep 0.05; printf slow", cwd=str(tmp_path), record=record),
            run_command("printf fast", cwd=str(tmp_path), record=record),
        )

    asyncio.run(scenario())

    assert store.get_run_command_evidence(execution_id, 1)["stdout"] == b"slow"
    assert store.get_run_command_evidence(execution_id, 2)["stdout"] == b"fast"
