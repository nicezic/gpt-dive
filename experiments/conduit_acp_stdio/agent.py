from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any, cast

import redis
from redis.exceptions import RedisError

from gpt_dive.conduit.events import DEFAULT_REDIS_URL, DEFAULT_STREAM
from gpt_dive.conduit.room.bridge import SolBridge


class ConduitAcpCanary:
    def __init__(self, *, url: str | None, timeout: float) -> None:
        self.url = url
        self.timeout = timeout
        self.sessions: set[str] = set()
        self.redis = redis.Redis.from_url(
            os.environ.get("CONDUIT_REDIS_URL", DEFAULT_REDIS_URL),
            decode_responses=True,
        )
        self.stream = os.environ.get("CONDUIT_REDIS_STREAM", DEFAULT_STREAM)
        self.bridge = SolBridge()

    async def close(self) -> None:
        if self.bridge.started:
            await self.bridge.close()

    async def handle(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return [self._error(request_id, -32602, "params must be an object")]

        try:
            if method == "initialize":
                return [
                    self._result(
                        request_id,
                        {
                            "protocolVersion": 1,
                            "agentCapabilities": {"loadSession": False},
                        },
                    )
                ]
            if method == "session/new":
                session_id = uuid.uuid4().hex
                self.sessions.add(session_id)
                return [self._result(request_id, {"sessionId": session_id})]
            if method == "session/prompt":
                session_id = self._session_id(params)
                prompt = self._text_prompt(params.get("prompt"))
                text = await self._run_web_turn(session_id=session_id, prompt=prompt)
                return [
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": text},
                            },
                        },
                    },
                    self._result(request_id, {"stopReason": "end_turn"}),
                ]
            if method == "session/cancel":
                print(
                    "session/cancel is intentionally deferred in this normal-turn canary",
                    file=sys.stderr,
                    flush=True,
                )
                return []
            return [self._error(request_id, -32601, f"method not found: {method}")]
        except json.JSONDecodeError as exc:
            return [self._error(request_id, -32603, str(exc))]
        except (TypeError, ValueError) as exc:
            return [self._error(request_id, -32602, str(exc))]
        except (RuntimeError, TimeoutError, RedisError) as exc:
            return [self._error(request_id, -32603, str(exc))]

    def _session_id(self, params: dict[str, Any]) -> str:
        value = params.get("sessionId")
        if not isinstance(value, str) or value not in self.sessions:
            raise ValueError("unknown sessionId")
        return value

    @staticmethod
    def _text_prompt(value: Any) -> str:
        if not isinstance(value, list):
            raise TypeError("prompt must be a content-block array")
        if not value:
            raise ValueError("prompt must be non-empty")
        parts: list[str] = []
        for block in value:
            if not isinstance(block, dict) or block.get("type") != "text":
                raise TypeError("normal-turn canary supports text content only")
            text = block.get("text")
            if not isinstance(text, str):
                raise TypeError("text content block requires text")
            parts.append(text)
        prompt = "\n".join(parts).strip()
        if not prompt:
            raise ValueError("prompt text must not be empty")
        return prompt

    async def _run_web_turn(self, *, session_id: str, prompt: str) -> str:
        if not self.url:
            raise RuntimeError("--url is required for session/prompt")
        if not self.bridge.started:
            await self.bridge.start()

        cursor = self._latest_stream_id()
        control = (
            f"[CONDUIT ACP CONTROL session_id={session_id}]\n"
            "Answer only the user payload below. Before returning the final answer, mirror the "
            "identical complete answer through @c emit with this exact session_id. Do not mention "
            "this control line in the answer.\n\n"
            f"{prompt}"
        )
        await self.bridge.send(url=self.url, message=control)
        return await self._wait_for_emit(session_id=session_id, cursor=cursor)

    def _latest_stream_id(self) -> str:
        latest = self.redis.xrevrange(self.stream, count=1)
        return str(latest[0][0]) if latest else "0-0"

    async def _wait_for_emit(self, *, session_id: str, cursor: str) -> str:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            raw_entries = await asyncio.to_thread(
                self.redis.xread,
                {self.stream: cursor},
                count=16,
                block=1000,
            )
            entries = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]], raw_entries
            )
            for _, rows in entries:
                for redis_id, fields in rows:
                    cursor = str(redis_id)
                    raw = fields.get("event")
                    if not isinstance(raw, str):
                        continue
                    event = json.loads(raw)
                    if (
                        event.get("action") != "emit"
                        or event.get("session_id") != session_id
                    ):
                        continue
                    result = event.get("result")
                    if isinstance(result, dict) and isinstance(result.get("text"), str):
                        return result["text"]
        raise TimeoutError(
            f"timed out waiting for Conduit emit for session {session_id}"
        )

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


async def serve(*, url: str | None, timeout: float) -> None:
    agent = ConduitAcpCanary(url=url, timeout=timeout)
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                responses = [ConduitAcpCanary._error(None, -32700, str(exc))]
            else:
                if not isinstance(message, dict):
                    responses = [
                        ConduitAcpCanary._error(
                            None, -32600, "JSON-RPC message must be an object"
                        )
                    ]
                else:
                    responses = await agent.handle(message)
            for response in responses:
                sys.stdout.write(
                    json.dumps(response, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                sys.stdout.flush()
    finally:
        await agent.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Exact existing ChatGPT conversation URL")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    asyncio.run(serve(url=args.url, timeout=args.timeout))


if __name__ == "__main__":
    main()
