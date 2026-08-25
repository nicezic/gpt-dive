from __future__ import annotations

import json
from pathlib import Path

EVENT_LOG = Path("/tmp/conduit-events.ndjson")


def latest_emit(path: Path) -> dict[str, object]:
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for event in reversed(events):
        if event.get("action") == "emit":
            return event
    raise RuntimeError("no Conduit emit event found")


def main() -> None:
    event = latest_emit(EVENT_LOG)
    result = event.get("result")
    if not isinstance(result, dict):
        raise TypeError("emit result must be an object")
    text = result.get("text")
    if not isinstance(text, str) or not text:
        raise TypeError("emit result.text must be non-empty text")

    session_id = event.get("session_id")
    report = {
        "projection_probe": "PASS",
        "raw_event_direct_projection": "PASS"
        if isinstance(session_id, str) and session_id
        else "FAIL",
        "acp_target": {"protocolVersion": 1, "schema_artifact": "v1.20.0"},
        "observed": {
            "assistant_text": True,
            "session_id": isinstance(session_id, str) and bool(session_id),
            "timestamp": isinstance(event.get("ts"), str),
            "redis_id": isinstance(event.get("redis_id"), str),
            "tasks_snapshot": isinstance(event.get("tasks"), list),
        },
        "deterministic_mapping": {
            "session/update.sessionId": "event.session_id",
            "session/update.agent_message_chunk.content.text": "event.result.text",
            "session/prompt.stopReason": "end_turn because Conduit emit is a complete Mirrored Full Output",
        },
        "missing_from_legacy_emit_event": (
            [] if isinstance(session_id, str) and session_id else ["session_id"]
        ),
        "owned_by_acp_ingress_adapter": [
            "user prompt content/direction",
            "session creation and active-prompt state",
        ],
        "deferred_separate_acceptance": [
            "session cancellation correlation and real Web cancellation"
        ],
        "excluded_from_conversation_domain_without_more_evidence": [
            "redis_id",
            "transport timestamp",
            "automatic tasks snapshot",
        ],
        "first_canary_streaming_policy": "one complete emit maps to one agent_message_chunk, then end_turn",
        "source_emit": {
            "redis_id": event.get("redis_id"),
            "text_chars": len(text),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
