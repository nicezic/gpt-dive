from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from gpt_dive.council import append_turn, initialize_council
from gpt_dive.council.server import CouncilRoom, create_app


class FakeBridge:
    def __init__(self) -> None:
        self.started = False
        self.start_count = 0
        self.closed = False

    async def start(self) -> None:
        self.started = True
        self.start_count += 1

    async def close(self) -> None:
        self.closed = True
        self.started = False

    async def send(self, *, url: str, message: str) -> dict[str, Any]:
        return {"ok": True, "url": url}


def test_room_state_reads_git_backed_transcript(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Architecture Review\n\nWhy")
    append_turn(repo, "USER", "Question")
    room = CouncilRoom(repo, sol_url="https://chatgpt.com/c/test", bridge=FakeBridge())

    state = room.state()

    assert state["title"] == "Architecture Review"
    assert state["turns"] == [{"speaker": "USER", "text": "Question"}]
    assert state["bridge_started"] is False


def test_room_routes_opus_and_sol_and_starts_bridge_lazily(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    bridge = FakeBridge()
    calls: list[tuple[str, str]] = []

    async def opus_runner(council_dir: Path, message: str, **_: Any) -> dict[str, Any]:
        calls.append(("OPUS", message))
        append_turn(council_dir, "USER", message)
        append_turn(council_dir, "OPUS", "opus-ok")
        return {"ok": True, "participant": "OPUS"}

    async def sol_runner(council_dir: Path, message: str, **_: Any) -> dict[str, Any]:
        calls.append(("SOL", message))
        append_turn(council_dir, "USER", message)
        append_turn(council_dir, "SOL", "sol-ok")
        return {"ok": True, "participant": "SOL"}

    room = CouncilRoom(
        repo,
        sol_url="https://chatgpt.com/c/test",
        bridge=bridge,
        opus_runner=opus_runner,
        sol_runner=sol_runner,
    )

    opus = asyncio.run(room.send("OPUS", "ask opus"))
    sol = asyncio.run(room.send("SOL", "ask sol"))

    assert opus["ok"] is True
    assert sol["ok"] is True
    assert calls == [("OPUS", "ask opus"), ("SOL", "ask sol")]
    assert bridge.start_count == 1


def test_http_api_exposes_state_turn_and_retry(tmp_path: Path) -> None:
    repo = tmp_path / "council"
    initialize_council(repo, "# Council")
    bridge = FakeBridge()

    async def opus_runner(council_dir: Path, message: str, **_: Any) -> dict[str, Any]:
        append_turn(council_dir, "USER", message)
        append_turn(council_dir, "OPUS", "answer")
        return {"ok": True, "participant": "OPUS"}

    async def opus_retry(council_dir: Path, **_: Any) -> dict[str, Any]:
        return {"ok": True, "participant": "OPUS", "retried": True}

    room = CouncilRoom(
        repo,
        sol_url="https://chatgpt.com/c/test",
        bridge=bridge,
        opus_runner=opus_runner,
        opus_retry_runner=opus_retry,
    )
    app = create_app(room)

    with TestClient(app) as client:
        assert client.get("/api/state").json()["turns"] == []
        turn = client.post("/api/turn", json={"target": "OPUS", "message": "Question"})
        assert turn.status_code == 200
        assert turn.json()["ok"] is True
        state = client.get("/api/state").json()
        assert [turn["speaker"] for turn in state["turns"]] == ["USER", "OPUS"]
        retry = client.post("/api/retry", json={"target": "OPUS"})
        assert retry.json()["retried"] is True
        bad = client.post("/api/turn", json={"target": "NOPE", "message": "x"})
        assert bad.status_code == 400

    assert bridge.closed is True


def test_room_retry_reconciles_late_sol_commit_before_bridge_start(
    tmp_path: Path,
) -> None:
    from gpt_dive.council import emit_sol_response

    repo = tmp_path / "council"
    initialized = initialize_council(repo, "# Council")
    bridge = FakeBridge()
    user = append_turn(repo, "USER", "Slow question")
    late = emit_sol_response(repo, "Late answer", expected_head=user["commit"])
    room = CouncilRoom(repo, sol_url="https://chatgpt.com/c/test", bridge=bridge)

    result = asyncio.run(room.retry("SOL"))

    assert result["ok"] is True
    assert result["recovered_late_response"] is True
    assert result["response_commit"] == late["commit"]
    assert result["context_before"] == initialized["initial_commit"]
    assert bridge.start_count == 0
