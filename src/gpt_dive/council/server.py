from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Protocol

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from .bridge import SolBridge
from .opus import retry_opus_turn, run_opus_turn
from .repo import context_commit, head
from .sol import reconcile_sol_response, retry_sol_turn, run_sol_turn

Target = Literal["SOL", "OPUS"]
TurnRunner = Callable[..., Awaitable[dict[str, Any]]]


class BridgeLike(Protocol):
    @property
    def started(self) -> bool: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def send(self, *, url: str, message: str) -> dict[str, Any]: ...


def _parse_turns(chat: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for raw in chat.split("\n---\n"):
        block = raw.strip()
        if not block:
            continue
        heading, separator, body = block.partition("\n")
        if not separator or heading not in {"# USER", "# SOL", "# OPUS"}:
            continue
        turns.append({"speaker": heading[2:], "text": body.strip()})
    return turns


def _title_from_init(init_text: str) -> str:
    for line in init_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return "Council"


class CouncilRoom:
    def __init__(
        self,
        council_dir: str | Path,
        *,
        sol_url: str,
        bridge: BridgeLike | None = None,
        opus_runner: TurnRunner = run_opus_turn,
        opus_retry_runner: TurnRunner = retry_opus_turn,
        sol_runner: TurnRunner = run_sol_turn,
        sol_retry_runner: TurnRunner = retry_sol_turn,
    ) -> None:
        self.repo = Path(council_dir).expanduser().resolve()
        if not self.repo.is_dir():
            raise ValueError(f"council_dir is not a directory: {self.repo}")
        if not (self.repo / ".git").is_dir():
            raise ValueError(f"council_dir is not a Git repository: {self.repo}")
        if (
            not (self.repo / "init.md").is_file()
            or not (self.repo / "chat.md").is_file()
        ):
            raise ValueError("Council repo requires init.md and chat.md")
        self.sol_url = sol_url.strip()
        if not self.sol_url:
            raise ValueError("sol_url must not be empty")
        self.bridge = bridge or SolBridge()
        self._opus_runner = opus_runner
        self._opus_retry_runner = opus_retry_runner
        self._sol_runner = sol_runner
        self._sol_retry_runner = sol_retry_runner
        self._turn_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.bridge.close()

    def state(self) -> dict[str, Any]:
        init_text = (self.repo / "init.md").read_text(encoding="utf-8")
        chat = (self.repo / "chat.md").read_text(encoding="utf-8")
        return {
            "ok": True,
            "title": _title_from_init(init_text),
            "init": init_text,
            "chat": chat,
            "turns": _parse_turns(chat),
            "head": head(self.repo),
            "contexts": {
                "SOL": context_commit(self.repo, "SOL"),
                "OPUS": context_commit(self.repo, "OPUS"),
            },
            "bridge_started": self.bridge.started,
        }

    async def _ensure_sol_bridge(self) -> None:
        if not self.bridge.started:
            await self.bridge.start()

    async def send(self, target: Target, message: str) -> dict[str, Any]:
        text = message.strip()
        if not text:
            raise ValueError("message must not be empty")
        async with self._turn_lock:
            if target == "OPUS":
                return await self._opus_runner(self.repo, text)
            if target == "SOL":
                try:
                    await self._ensure_sol_bridge()
                except RuntimeError as exc:
                    return {"ok": False, "participant": "SOL", "error": str(exc)}
                return await self._sol_runner(
                    self.repo,
                    text,
                    url=self.sol_url,
                    bridge=self.bridge,
                )
            raise ValueError(f"invalid target: {target}")

    async def retry(self, target: Target) -> dict[str, Any]:
        async with self._turn_lock:
            if target == "OPUS":
                return await self._opus_retry_runner(self.repo)
            if target == "SOL":
                recovered = reconcile_sol_response(self.repo)
                if recovered is not None:
                    return recovered
                try:
                    await self._ensure_sol_bridge()
                except RuntimeError as exc:
                    return {"ok": False, "participant": "SOL", "error": str(exc)}
                return await self._sol_retry_runner(
                    self.repo,
                    url=self.sol_url,
                    bridge=self.bridge,
                )
            raise ValueError(f"invalid target: {target}")


def create_app(room: CouncilRoom, *, static_dir: str | Path | None = None) -> Starlette:
    async def api_state(_: Request) -> JSONResponse:
        return JSONResponse(room.state())

    async def api_turn(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            target = str(body.get("target", "")).upper()
            if target not in {"SOL", "OPUS"}:
                raise ValueError(f"invalid target: {target}")
            result = await room.send(target, str(body.get("message", "")))  # type: ignore[arg-type]
            return JSONResponse(result)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    async def api_retry(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            target = str(body.get("target", "")).upper()
            if target not in {"SOL", "OPUS"}:
                raise ValueError(f"invalid target: {target}")
            result = await room.retry(target)  # type: ignore[arg-type]
            return JSONResponse(result)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @asynccontextmanager
    async def lifespan(_: Starlette):
        try:
            yield
        finally:
            await room.close()

    routes: list[BaseRoute] = [
        Route("/api/state", api_state, methods=["GET"]),
        Route("/api/turn", api_turn, methods=["POST"]),
        Route("/api/retry", api_retry, methods=["POST"]),
    ]
    if static_dir is not None:
        static_path = Path(static_dir).expanduser().resolve()
        if not (static_path / "index.html").is_file():
            raise ValueError(f"built Council UI not found: {static_path}")
        routes.append(
            Mount("/", app=StaticFiles(directory=static_path, html=True), name="web")
        )
    return Starlette(routes=routes, lifespan=lifespan)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local GPT Dive Council room.")
    parser.add_argument("--council-dir", type=Path, required=True)
    parser.add_argument(
        "--sol-url",
        required=True,
        help="Exact existing ChatGPT Web SOL conversation URL",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument(
        "--static-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "web" / "dist",
    )
    args = parser.parse_args()

    room = CouncilRoom(args.council_dir, sol_url=args.sol_url)
    app = create_app(room, static_dir=args.static_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
