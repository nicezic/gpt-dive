from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import redis

from .events import DEFAULT_LOG, DEFAULT_REDIS_URL, DEFAULT_STREAM, append_event_ndjson


def main() -> None:
    url = os.environ.get("CONDUIT_REDIS_URL", DEFAULT_REDIS_URL)
    stream = os.environ.get("CONDUIT_REDIS_STREAM", DEFAULT_STREAM)
    output = Path(os.environ.get("CONDUIT_NDJSON_PATH", str(DEFAULT_LOG))).expanduser()
    client = redis.Redis.from_url(url, decode_responses=True)
    last_id = os.environ.get("CONDUIT_LOG_START_ID", "$")

    while True:
        batches = cast(
            list[tuple[str, list[tuple[str, dict[str, str]]]]],
            client.xread({stream: last_id}, block=1000, count=100),
        )
        for _, entries in batches:
            for redis_id, fields in entries:
                event_json = fields.get("event")
                if event_json is None:
                    raise ValueError("Conduit stream entry is missing event field")
                append_event_ndjson(output, str(redis_id), str(event_json))
                last_id = str(redis_id)


if __name__ == "__main__":
    main()
