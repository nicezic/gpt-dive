from __future__ import annotations

import asyncio
from typing import Any

import pytest

from gpt_dive.conduit.room.bridge import SolBridge, _send_script, _session_is_open


def test_session_is_open_matches_named_open_session_only() -> None:
    output = """### Browsers
abc:
- other:
  - status: open
- msedge:
  - status: open
  - browser-type: chrome (attached)
"""

    assert _session_is_open(output, "msedge") is True
    assert _session_is_open(output, "missing") is False


def test_bridge_start_reuses_existing_open_cli_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = SolBridge()
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def fake_run(*args: str, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return "### Browsers\nabc:\n- msedge:\n  - status: open\n"

    monkeypatch.setattr(bridge, "_run_cli", fake_run)

    asyncio.run(bridge.start())

    assert bridge.started is True
    assert len(calls) == 1
    assert calls[0][0] == ("list", "--all")


def test_bridge_start_attaches_extension_when_session_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = SolBridge()
    outputs = iter(
        [
            "  (no browsers)\n",
            "### Session `msedge` created, attached to `chrome`.\n",
            "### Browsers\nabc:\n- msedge:\n  - status: open\n",
        ]
    )
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def fake_run(*args: str, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return next(outputs)

    monkeypatch.setattr(bridge, "_run_cli", fake_run)

    asyncio.run(bridge.start())

    assert bridge.started is True
    assert calls[1][0] == ("attach", "--extension=chrome", "--session=msedge")
    assert calls[1][1]["with_creds"] is True
    assert calls[1][1]["env"]["PLAYWRIGHT_MCP_EXECUTABLE_PATH"].endswith("msedge.exe")


def test_bridge_probe_requires_started_bridge() -> None:
    bridge = SolBridge()

    with pytest.raises(RuntimeError, match="not started"):
        asyncio.run(bridge.probe(url="https://chatgpt.com/c/test"))


def test_bridge_probe_accepts_compact_composer_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = SolBridge()
    bridge._started = True

    async def fake_run_code(code: str, *, timeout: float) -> dict[str, Any]:
        assert "chrome.tabs.query" in code
        assert "#prompt-textarea" in code
        assert timeout == 15.0
        return {
            "ok": True,
            "state": "BUSY",
            "reason": "generating",
            "empty": True,
            "tabId": 7,
        }

    monkeypatch.setattr(bridge, "_run_code", fake_run_code)

    result = asyncio.run(bridge.probe(url="https://chatgpt.com/c/test"))

    assert result["state"] == "BUSY"
    assert result["reason"] == "generating"


def test_send_script_embeds_ready_gate_and_message_safely() -> None:
    script = _send_script(
        "https://chatgpt.com/c/test",
        'line 1\n"quoted"',
        ready_timeout=12.5,
        ack_timeout=3.0,
    )

    assert '"readyTimeoutMs": 12500' in script
    assert '"ackTimeoutMs": 3000' in script
    assert 'line 1\\n\\"quoted\\"' in script
    assert 'before.state !== "READY"' in script
    assert "expression: args.stateExpr" in script
    assert "expression: stateExpr" not in script
    assert "Input.insertText" in script
    assert "Input.dispatchKeyEvent" in script
    assert "after.empty" in script


def test_bridge_send_returns_acknowledged_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = SolBridge(ready_timeout=2.0, ack_timeout=1.0)
    bridge._started = True

    async def fake_run_code(code: str, *, timeout: float) -> dict[str, Any]:
        assert "https://chatgpt.com/c/test" in code
        assert timeout == 18.0
        return {
            "ok": True,
            "accepted": True,
            "preState": "READY",
            "postState": "BUSY",
            "postReason": "generating",
            "tabId": 9,
        }

    monkeypatch.setattr(bridge, "_run_code", fake_run_code)

    result = asyncio.run(bridge.send(url="https://chatgpt.com/c/test", message="hello"))

    assert result["accepted"] is True
    assert result["preState"] == "READY"
    assert result["postState"] == "BUSY"
