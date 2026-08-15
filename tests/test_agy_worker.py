from __future__ import annotations

import json

import pytest

from gpt_dive.agy_worker import DEFAULT_MODEL, _build_command, _parse_stream_json


def test_build_command_uses_safe_plan_mode() -> None:
    command = _build_command(task="review this", model=DEFAULT_MODEL, timeout=12.2)

    assert command[0].endswith("/.local/bin/agy")
    assert command[1:3] == ["-p", "review this"]
    assert command[command.index("--model") + 1] == "gemini-3.7-flash-high"
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--mode") + 1] == "plan"
    assert command[command.index("--print-timeout") + 1] == "13s"
    assert "--disable-slash-commands" not in command
    assert "--dangerously-skip-permissions" not in command


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
