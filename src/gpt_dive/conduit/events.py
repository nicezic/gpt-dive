from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import redis

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_STREAM = "conduit:events"
DEFAULT_LOG = Path("/tmp/conduit-events.ndjson")


class RedisEventPublisher:
    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str | None = None,
        stream: str | None = None,
    ) -> None:
        self.client = client or redis.Redis.from_url(
            url or os.environ.get("CONDUIT_REDIS_URL", DEFAULT_REDIS_URL),
            decode_responses=True,
        )
        self.stream = stream or os.environ.get("CONDUIT_REDIS_STREAM", DEFAULT_STREAM)

    def publish(self, event: dict[str, object]) -> str:
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        event_id = self.client.xadd(self.stream, {"event": payload})
        if isinstance(event_id, bytes):
            return event_id.decode()
        return str(event_id)


def append_event_ndjson(path: Path, redis_id: str, event_json: str) -> None:
    event = json.loads(event_json)
    if not isinstance(event, dict):
        raise TypeError("Conduit Redis event must be a JSON object")
    record = {"redis_id": redis_id, **event}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
