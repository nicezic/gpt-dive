from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path

import pytest

import gpt_dive.agy_worker as agy_worker_module
from gpt_dive.agy_worker import (
    DEFAULT_MODEL,
    _build_command,
    _extract_stream_metadata,
    _parse_stream_json,
    invoke_agy_worker,
)


def test_build_command_uses_safe_plan_mode() -> None:
    command = _build_command(
        task="review this",
        model=DEFAULT_MODEL,
        timeout=12.2,
        workspace_dir="/tmp/workspace",
    )

    assert command[0].endswith("/.local/bin/agy")
    assert command[1:3] == ["-p", "review this"]
    assert command[command.index("--model") + 1] == "gemini-3.7-flash-high"
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--mode") + 1] == "plan"
    assert command[command.index("--print-timeout") + 1] == "13s"
    assert "--disable-slash-commands" not in command
    assert "--dangerously-skip-permissions" in command
    assert "--conversation" not in command
    assert command[command.index("--add-dir") + 1] == "/tmp/workspace"


def test_build_command_resumes_exact_conversation() -> None:
    command = _build_command(
        task="continue review",
        model=DEFAULT_MODEL,
        timeout=30.0,
        conversation_id="conversation-123",
    )

    assert command[command.index("--conversation") + 1] == "conversation-123"


def test_parse_stream_json_returns_terminal_result() -> None:
    stdout = "\n".join(
        [
            json.dumps({"event": "init", "conversation_id": "c1"}),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {"step_type": "agent_response", "text_delta": "OK"},
                }
            ),
            json.dumps(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": "c1",
                        "status": "SUCCESS",
                        "response": "OK\n",
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    },
                }
            ),
        ]
    )

    result = _parse_stream_json(stdout)
    assert result["status"] == "SUCCESS"
    assert result["response"] == "OK\n"
    assert result["usage"]["input_tokens"] == 10


def test_parse_stream_json_requires_terminal_result() -> None:
    with pytest.raises(ValueError, match="terminal result"):
        _parse_stream_json(json.dumps({"event": "init"}))



def test_extract_stream_metadata_tolerates_incomplete_stream() -> None:
    stdout = "\n".join(
        [
            json.dumps({"event": "init", "conversation_id": "c-partial"}),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "c-partial",
                        "step_type": "tool",
                    },
                }
            ),
            '{"event":"truncated"',
        ]
    )

    conversation_id, terminal = _extract_stream_metadata(stdout)
    assert conversation_id == "c-partial"
    assert terminal is None


def test_invoke_agy_worker_timeout_preserves_partial_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_agy = tmp_path / "agy"
    fake_agy.write_text("fake")
    monkeypatch.setattr(agy_worker_module, "AGY", fake_agy)

    stdout = "\n".join(
        [
            json.dumps({"event": "init", "conversation_id": "c-timeout"}),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "c-timeout",
                        "step_type": "tool",
                    },
                }
            ),
        ]
    ).encode()

    class FakeProcess:
        pid = 4242

        def __init__(self) -> None:
            self.done = agy_worker_module.asyncio.Event()

        async def communicate(self) -> tuple[bytes, bytes]:
            await self.done.wait()
            return stdout, b"partial stderr"

    proc = FakeProcess()

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        return proc

    async def fake_wait_for(awaitable: object, timeout: float) -> object:
        raise TimeoutError

    def fake_killpg(pid: int, sig: int) -> None:
        assert pid == 4242
        proc.done.set()

    monkeypatch.setattr(
        agy_worker_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(agy_worker_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(agy_worker_module.os, "killpg", fake_killpg)

    result = asyncio.run(invoke_agy_worker(task="research", timeout=120.0))

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["conversation_id"] == "c-timeout"
    assert "c-timeout" in result["stdout"]
    assert result["stderr"] == "partial stderr"



def test_invoke_agy_worker_cancellation_terminates_and_reaps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_agy = tmp_path / "agy"
    fake_agy.write_text("fake")
    monkeypatch.setattr(agy_worker_module, "AGY", fake_agy)

    class FakeProcess:
        pid = 5150
        returncode: int | None = None

        def __init__(self) -> None:
            self.started = agy_worker_module.asyncio.Event()
            self.done = agy_worker_module.asyncio.Event()
            self.reaped = False

        async def communicate(self) -> tuple[bytes, bytes]:
            self.started.set()
            await self.done.wait()
            self.reaped = True
            self.returncode = -signal.SIGTERM
            return b"", b""

    proc = FakeProcess()
    killed: list[tuple[int, int]] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        return proc

    def fake_killpg(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        proc.done.set()

    monkeypatch.setattr(
        agy_worker_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(agy_worker_module.os, "killpg", fake_killpg)

    async def scenario() -> None:
        task = asyncio.create_task(invoke_agy_worker(task="research", timeout=120.0))
        await proc.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert killed == [(5150, signal.SIGTERM)]
    assert proc.reaped is True
