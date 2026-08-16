from __future__ import annotations

import json
from pathlib import Path

from gpt_dive.conduit.events import RedisEventPublisher, append_event_ndjson


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.calls.append((stream, fields))
        return "123-0"


def test_redis_publisher_uses_one_json_event_field() -> None:
    redis = FakeRedis()
    publisher = RedisEventPublisher(client=redis, stream="conduit:test")
    event = {"v": 1, "action": "emit", "data": {"text": "hello"}}

    event_id = publisher.publish(event)

    assert event_id == "123-0"
    assert redis.calls == [
        ("conduit:test", {"event": json.dumps(event, ensure_ascii=False, separators=(",", ":"))})
    ]


def test_append_event_ndjson_adds_redis_id(tmp_path: Path) -> None:
    output = tmp_path / "events.ndjson"
    append_event_ndjson(output, "10-2", '{"v":1,"action":"emit"}')

    line = json.loads(output.read_text())
    assert line == {"redis_id": "10-2", "v": 1, "action": "emit"}
