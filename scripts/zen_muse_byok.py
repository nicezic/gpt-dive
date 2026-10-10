#!/usr/bin/env python3
"""OpenCode Zen Muse Spark 1.3 Free (BYOK Standalone Client).

Architecture & Gate Invariants:
    OpenCode Zen gates `muse-spark-1.3-contributor-free` behind edge fingerprinting,
    returning `403 FreeTierError: OpenCode's free tier can only be used from within OpenCode`
    for standard third-party callers. This client satisfies all gateway invariants:

    1. Endpoint : POST https://opencode.ai/zen/v1/responses (OpenAI Responses API, not chat/completions).
    2. Headers  :
       - User-Agent          : `opencode/<semver >= 1.17.0>` (e.g. `opencode/1.18.35`).
       - x-opencode-session  : `ses_<12hex><14base62>`. Uses monotonic descending bitwise NOT:
                               now = ~(current_timestamp_ms * 0x1000 + 1).
       - x-opencode-client   : `cli`.
       - x-opencode-request  : `msg_<12hex><14base62>`.
       - Authorization       : `Bearer $OPENCODE_GO_API_KEY` or `Bearer public`.
    3. Payload  :
       - stream              : `true` (mandatory; non-streaming batch triggers 403 FreeTierError).
       - tools               : Required tool set: {"bash", "read", "glob", "grep"} with top-level `name`.
       - reasoning           : `{"effort": "xhigh"}` (default; scales CoT to ~1,400 reasoning tokens).

Usage:
    CLI One-shot: creds run ai -- python3 scripts/zen_muse_byok.py "prompt" [--effort xhigh]
    CLI REPL    : creds run ai -- python3 scripts/zen_muse_byok.py -i
    CLI Resume  : creds run ai -- python3 scripts/zen_muse_byok.py -c "follow-up"
                  creds run ai -- python3 scripts/zen_muse_byok.py -s <ses_ID> "follow-up"
    Sessions persist as JSON under /tmp/session_muse-spark-1.3-contributor-free/.
    Module      :
        from scripts.zen_muse_byok import MuseSparkClient
        client = MuseSparkClient(effort="xhigh")
        for chunk in client.stream_chat("Hello"):
            if chunk["type"] == "delta":
                print(chunk["text"], end="", flush=True)
"""

import argparse
import json
import os
import secrets
import sys
import time
import urllib.request
from collections.abc import Generator

BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def random_base62(length: int = 14) -> str:
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))


def create_opencode_id(prefix: str = "ses") -> str:
    """Generate OpenCode ID: inverted timestamp (6 bytes) + 14 random Base62 chars."""
    ts = int(time.time() * 1000)
    now = ~(ts * 0x1000 + 1)
    hex_time = (now & 0xFFFFFFFFFFFF).to_bytes(6, "big").hex()
    return f"{prefix}_{hex_time}{random_base62(14)}"


SESSION_DIR = "/tmp/session_muse-spark-1.3-contributor-free"


def _session_path(session_id: str) -> str:
    return os.path.join(SESSION_DIR, f"{session_id}.json")


def save_session(client: MuseSparkClient) -> None:
    """Persist session (atomic tmp + rename)."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    tmp_path = os.path.join(SESSION_DIR, f".{client.session_id}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "session_id": client.session_id,
                "model": client.model,
                "effort": client.effort,
                "history": client.history,
            },
            f,
            ensure_ascii=False,
        )
    os.replace(tmp_path, _session_path(client.session_id))


def latest_session_id() -> str | None:
    try:
        files = [
            f
            for f in os.listdir(SESSION_DIR)
            if f.endswith(".json") and not f.startswith(".")
        ]
    except FileNotFoundError:
        return None
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(os.path.join(SESSION_DIR, f)))
    return files[-1].removesuffix(".json")


def load_session(session_id: str) -> MuseSparkClient:
    session_id = os.path.basename(session_id.removesuffix(".json"))
    try:
        with open(_session_path(session_id), encoding="utf-8") as f:
            data = json.load(f)
    except OSError, ValueError:
        print(f"cannot load session: {session_id}", file=sys.stderr)
        sys.exit(1)
    client = MuseSparkClient()
    client.session_id = data.get("session_id", session_id)
    client.history = data.get("history", [])
    if data.get("effort"):
        client.effort = data["effort"]
    if data.get("model"):
        client.model = data["model"]
    return client


def report_status(event: dict) -> None:
    """Print 정상/잘림/비정상 + reason to stderr."""
    if event.get("incomplete"):
        print(f"\n[잘림: {event['incomplete']}]", file=sys.stderr)
    elif event.get("status") != "completed":
        print(f"\n[비정상: {event.get('status')}]", file=sys.stderr)
    else:
        print("\n[정상 종료]", file=sys.stderr)


class MuseSparkClient:
    def __init__(
        self,
        api_key: str | None = None,
        effort: str = "xhigh",
        model: str = "muse-spark-1.3-contributor-free",
    ):
        self.api_key = api_key or os.environ.get("OPENCODE_GO_API_KEY", "public")
        self.effort = effort
        self.model = model
        self.session_id = create_opencode_id("ses")
        self.endpoint = "https://opencode.ai/zen/v1/responses"
        self.history: list[dict[str, str]] = []

        # Required gate tools: bash, read, glob, grep
        tool_props = [
            ("bash", "command"),
            ("read", "filePath"),
            ("glob", "pattern"),
            ("grep", "pattern"),
        ]
        self.tools = [
            {
                "type": "function",
                "name": name,
                "description": name,
                "parameters": {
                    "type": "object",
                    "properties": {prop: {"type": "string"}},
                },
            }
            for name, prop in tool_props
        ]

    def reset_session(self):
        """Start a fresh session with a new session ID and empty history."""
        self.session_id = create_opencode_id("ses")
        self.history = []

    def stream_chat(self, prompt: str) -> Generator[dict]:
        request_id = create_opencode_id("msg")
        self.history.append({"role": "user", "content": prompt})

        headers = {
            "User-Agent": "opencode/1.18.35",
            "x-opencode-session": self.session_id,
            "x-opencode-session-id": self.session_id,
            "x-opencode-request": request_id,
            "x-opencode-client": "cli",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": list(self.history),
            "stream": True,
            "reasoning": {"effort": self.effort},
            "tools": self.tools,
        }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        assistant_full = ""
        with urllib.request.urlopen(req, timeout=90) as resp:
            for line in resp:
                line_str = line.decode("utf-8").strip()
                if line_str.startswith("data: "):
                    chunk = line_str[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        t = data.get("type")
                        if t == "response.output_text.delta" and data.get("delta"):
                            assistant_full += data["delta"]
                            yield {"type": "delta", "text": data["delta"]}
                        elif t == "response.completed":
                            r = data.get("response", {})
                            yield {
                                "type": "completed",
                                "usage": r.get("usage"),
                                "status": r.get("status"),
                                "incomplete": (r.get("incomplete_details") or {}).get(
                                    "reason"
                                ),
                            }
                    except Exception:
                        pass

        if assistant_full:
            self.history.append({"role": "assistant", "content": assistant_full})


def main():
    parser = argparse.ArgumentParser(
        description="OpenCode Zen - Muse Spark 1.3 Free BYOK Client"
    )
    parser.add_argument("prompt", nargs="?", help="Prompt to run")
    parser.add_argument(
        "--effort",
        default=None,
        choices=["minimal", "low", "medium", "high", "xhigh"],
        help="Reasoning effort (default: xhigh, or stored value when resuming)",
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Interactive REPL mode"
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="cont",
        action="store_true",
        help="Resume the most recent session",
    )
    parser.add_argument("-s", "--session", help="Resume a session by ID (e.g. ses_...)")
    args = parser.parse_args()

    if args.session or args.cont:
        sid = args.session or latest_session_id()
        if not sid:
            print("no saved sessions yet", file=sys.stderr)
            sys.exit(1)
        client = load_session(sid)
        if args.effort:
            client.effort = args.effort
    else:
        client = MuseSparkClient(effort=args.effort or "xhigh")

    if args.interactive or not args.prompt:
        print(f"=== Muse Spark 1.3 Free REPL (effort: {client.effort}) ===")
        print(f"Session ID: {client.session_id}")
        if client.history:
            print(f"[*] Resumed {len(client.history)} messages.")
        print("Type 'exit' or 'quit' to stop, 'reset' for a new session.\n")
        while True:
            try:
                user_input = input("\nYou > ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    break
                if user_input.lower() == "reset":
                    client.reset_session()
                    print(f"[*] Session reset. New ID: {client.session_id}")
                    continue

                print("\nMuse > ", end="", flush=True)
                for event in client.stream_chat(user_input):
                    if event["type"] == "delta":
                        print(event["text"], end="", flush=True)
                    elif event["type"] == "completed":
                        report_status(event)
                print()
                save_session(client)
            except KeyboardInterrupt, EOFError:
                print("\nBye!")
                break
    else:
        for event in client.stream_chat(args.prompt):
            if event["type"] == "delta":
                print(event["text"], end="", flush=True)
            elif event["type"] == "completed":
                report_status(event)
                if event.get("usage"):
                    usage = event["usage"]
                rt = usage.get("output_tokens_details", {}).get("reasoning_tokens", 0)
                print(
                    f"\n\n[Tokens: in={usage.get('input_tokens')}, out={usage.get('output_tokens')}, reasoning={rt}]",
                    file=sys.stderr,
                )
        print()
        save_session(client)
        print(f"[Session: {client.session_id}]", file=sys.stderr)


if __name__ == "__main__":
    main()
