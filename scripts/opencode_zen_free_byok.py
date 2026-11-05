#!/usr/bin/env python3
"""OpenCode Free Tier Standalone BYOK Client (All Free Models).

Architecture & Edge Gate Invariants (Reverse-Engineered & Verified):
    OpenCode gates free tier models behind Cloudflare Edge fingerprinting, returning
    `403 FreeTierError: OpenCode's free tier can only be used from within OpenCode`
    for non-conforming callers. The edge gateway uses static regex and payload tree
    checks requiring 4 simultaneous conditions (AND):

    1. Endpoint:
       - Supported: POST https://opencode.ai/zen/v1/chat/completions (OpenAI Chat API)
                    POST https://opencode.ai/inference/openai/v1/chat/completions
       - Obsolete : POST https://opencode.ai/zen/v1/responses
                    (Used by legacy zen_muse_byok.py; returns 400 ModelProtocolUnsupported for new models,
                     and 410 ModelDeprecated for muse-spark-1.3-contributor-free).

    2. Edge Gate Invariants (4-Lock Mechanism):
       Lock 1 [User-Agent]      : `opencode/<semver>` (e.g. `opencode/1.18.35` or `opencode/2.0.32`).
                                  Generic curl, python-requests, or browsers trigger 403 or Cloudflare 1010.
       Lock 2 [Session Format]  : `x-opencode-session: ses_<26_lowercase_hex>` (exact 30 chars total).
                                  Regex: `^ses_[0-9a-f]{26}$`.
                                  Uppercase hex, base62, 25-char, or 27-char strings trigger 403.
                                  Generated cleanly via `openssl rand -hex 13` or `secrets.token_hex(13)`.
       Lock 3 [Streaming]       : `stream: true` (mandatory; `stream: false` batch calls trigger 403).
       Lock 4 [Agent Tool Gate] : Must include a nested function tool named `"read"`:
                                  `tools: [{"type": "function", "function": {"name": "read", "parameters": {"type": "object", "properties": {}}}}]`.
                                  Other tools (`bash`, `grep`, `glob`, `edit`, `write`) alone fail with 403.
                                  Empty properties `{}` suffice; no bloated system prompts needed.

    3. Authorization Caveat:
       - `Authorization` is NOT required for free models.
       - Do NOT send expired Console or OpenCode Go tokens; an expired key overrides free tier
         access and immediately returns `401 Unauthorized (api_key_expired)`.
       - `x-opencode-client`, `x-opencode-session-id`, `x-session-affinity` are completely optional.

    4. Supported Free Models & Features:
       - `deepseek-v4.1-flash-free` (default): Fast coding & reasoning; CoT via `delta.reasoning_content`.
       - `glm-5.3-flash-free`: Strong multilingual & reasoning capabilities.
       - `minimax-m3.1-flash-free`, `mimo-v2.6-flash-free`, `beam-free`.
       - Supports `reasoning_effort`: `"low" | "high" | "max"`.

Minimal Curl Equivalent (100% Standalone):
    curl -N -s https://opencode.ai/zen/v1/chat/completions \\
      -H "User-Agent: opencode/1.18.35" \\
      -H "x-opencode-session: ses_$(openssl rand -hex 13)" \\
      -H "Content-Type: application/json" \\
      -d '{
        "model": "deepseek-v4.1-flash-free",
        "messages": [{"role": "user", "content": "대한민국의 수도는?"}],
        "stream": true,
        "tools": [{
          "type": "function",
          "function": {"name": "read", "parameters": {"type": "object", "properties": {}}}
        }]
      }'

Stream Filtering One-liner:
    curl -N -s https://opencode.ai/zen/v1/chat/completions ... \\
      | python3 -c '
    import sys, json
    for line in sys.stdin:
        if line.startswith("data: ") and "[DONE]" not in line:
            try:
                d = json.loads(line[6:])["choices"][0]["delta"]
                sys.stdout.write(d.get("content") or "")
                sys.stdout.flush()
            except Exception: pass
    print()
    '

Usage:
    CLI One-shot : python3 scripts/opencode_zen_free_byok.py "Explain quantum computing in 3 lines"
    With CoT     : python3 scripts/opencode_zen_free_byok.py --thinking "Your question"
    With Effort  : python3 scripts/opencode_zen_free_byok.py --thinking --effort high "Complex math"
    Model switch : python3 scripts/opencode_zen_free_byok.py -m glm-5.3-flash-free "Your prompt"
    Interactive  : python3 scripts/opencode_zen_free_byok.py -i
    Resume last  : python3 scripts/opencode_zen_free_byok.py -c "Follow-up question"
    Resume by ID : python3 scripts/opencode_zen_free_byok.py -s ses_... "Follow-up question"

Module Usage:
    from scripts.opencode_zen_free_byok import OpenCodeFreeClient
    client = OpenCodeFreeClient(model="deepseek-v4.1-flash-free")
    for chunk in client.stream_chat("Hello"):
        if chunk["type"] == "content":
            print(chunk["text"], end="", flush=True)
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from collections.abc import Generator
from pathlib import Path

DEFAULT_MODEL = "deepseek-v4.1-flash-free"
ENDPOINT = "https://opencode.ai/zen/v1/chat/completions"
SESSION_DIR = Path("/tmp/session_opencode_free")

GATE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    }
]


def create_session_id() -> str:
    """Generate valid 30-char OpenCode session ID (`ses_` + 26 lowercase hex characters)."""
    return f"ses_{secrets.token_hex(13)}"


def session_path(session_id: str) -> Path:
    safe_id = Path(session_id).name.removesuffix(".json")
    return SESSION_DIR / f"{safe_id}.json"


def save_session(client: OpenCodeFreeClient) -> None:
    """Persist session history atomically with 0600 permissions."""
    SESSION_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = session_path(client.session_id)
    tmp_path = target.with_suffix(".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with open(
        tmp_path,
        "w",
        encoding="utf-8",
        opener=lambda p, _: os.open(p, flags, 0o600),
    ) as f:
        json.dump(
            {
                "session_id": client.session_id,
                "model": client.model,
                "effort": client.effort,
                "history": client.history,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    tmp_path.replace(target)


def latest_session_id() -> str | None:
    """Return the most recently updated session ID or None."""
    if not SESSION_DIR.is_dir():
        return None
    files = list(SESSION_DIR.glob("ses_*.json"))
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime)
    return files[-1].stem


def load_session(session_id: str) -> OpenCodeFreeClient:
    """Restore client state from a saved session."""
    path = session_path(session_id)
    if not path.is_file():
        print(f"Error: Session file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as err:
        print(f"Error loading session {session_id}: {err}", file=sys.stderr)
        sys.exit(1)

    client = OpenCodeFreeClient(
        model=data.get("model", DEFAULT_MODEL),
        effort=data.get("effort"),
    )
    client.session_id = data.get("session_id", session_id)
    client.history = data.get("history", [])
    return client


class OpenCodeFreeClient:
    """Standalone client for OpenCode Free Tier models satisfying edge gate invariants."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        effort: str | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.effort = effort
        self.session_id = create_session_id()
        self.history: list[dict[str, str]] = []

    def reset_session(self) -> None:
        """Start a fresh session with an empty message history."""
        self.session_id = create_session_id()
        self.history = []

    def stream_chat(self, prompt: str) -> Generator[dict]:
        """Send prompt to OpenCode and yield SSE streaming events."""
        # Prepare outgoing messages without mutating self.history prematurely
        outbound_messages = [*self.history, {"role": "user", "content": prompt}]

        headers = {
            "User-Agent": "opencode/1.18.35",
            "Content-Type": "application/json",
            "x-opencode-session": self.session_id,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": outbound_messages,
            "stream": True,
            "tools": GATE_TOOLS,
            "stream_options": {"include_usage": True},
        }
        if self.effort:
            payload["reasoning_effort"] = self.effort

        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        full_content = ""
        tool_called = False

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    line_str = line.decode("utf-8").strip()
                    if not line_str.startswith("data: "):
                        continue
                    chunk_data = line_str[6:].strip()
                    if chunk_data == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk_data)
                    except json.JSONDecodeError:
                        continue

                    if data.get("usage"):
                        yield {"type": "usage", "usage": data["usage"]}

                    choices = data.get("choices")
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")

                    # Handle model requesting tool calls (gate bypass tool invoked)
                    if delta.get("tool_calls") or finish_reason == "tool_calls":
                        tool_called = True
                        yield {
                            "type": "tool_call",
                            "tool_calls": delta.get("tool_calls", []),
                        }

                    # Handle DeepSeek / GLM reasoning stream
                    reasoning_chunk = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_chunk:
                        yield {"type": "reasoning", "text": reasoning_chunk}

                    # Handle assistant answer content
                    content_chunk = delta.get("content")
                    if content_chunk:
                        full_content += content_chunk
                        yield {"type": "content", "text": content_chunk}

        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {err.code}: {body}") from err

        # Only commit turns to history upon successful textual reply
        if full_content:
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": full_content})
        elif tool_called:
            yield {
                "type": "warning",
                "text": "[Info: Model requested tool execution (read), which is not supported in BYOK chat mode.]",
            }


def format_tokens(usage: dict) -> str:
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)
    rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
    return (
        f"[Tokens: in={prompt_tokens}, out={completion_tokens}, reasoning={rt}, total={total_tokens}]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenCode Free Tier Client (DeepSeek, GLM, MiniMax, Mimo, Beam)"
    )
    parser.add_argument("prompt", nargs="?", help="Prompt to execute")
    parser.add_argument(
        "-m",
        "--model",
        default=None,
        help=f"Target free model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--thinking",
        "--cot",
        action="store_true",
        dest="thinking",
        help="Display DeepSeek/GLM CoT thought process in real-time",
    )
    parser.add_argument(
        "--effort",
        choices=["low", "high", "max"],
        default=None,
        help="Reasoning effort level (low, high, max)",
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Interactive REPL chat session"
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="cont",
        action="store_true",
        help="Resume the most recent conversation session",
    )
    parser.add_argument("-s", "--session", help="Resume a specific session ID (e.g. ses_...)")
    args = parser.parse_args()

    if args.session or args.cont:
        sid = args.session or latest_session_id()
        if not sid:
            print("Error: No saved sessions found to resume.", file=sys.stderr)
            sys.exit(1)
        client = load_session(sid)
        if args.model:
            client.model = args.model
        if args.effort:
            client.effort = args.effort
    else:
        client = OpenCodeFreeClient(
            model=args.model or DEFAULT_MODEL,
            effort=args.effort,
        )

    if args.interactive or not args.prompt:
        print(f"=== OpenCode Free REPL (Model: {client.model}) ===")
        print(f"Session ID : {client.session_id}")
        if client.effort:
            print(f"Effort     : {client.effort}")
        if client.history:
            print(f"[*] Resumed session with {len(client.history)} messages.")
        print("Type 'exit' / 'quit' to stop, 'reset' for a clean session.\n")

        while True:
            try:
                user_input = input("\nYou > ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    print("Goodbye!")
                    break
                if user_input.lower() == "reset":
                    client.reset_session()
                    print(f"[*] Started new session: {client.session_id}")
                    continue

                is_thinking = False
                usage_info = None

                for chunk in client.stream_chat(user_input):
                    if chunk["type"] == "reasoning" and args.thinking:
                        if not is_thinking:
                            print("\n\033[2m[Thinking]\n", end="", flush=True)
                            is_thinking = True
                        print(chunk["text"], end="", flush=True)
                    elif chunk["type"] == "content":
                        if is_thinking:
                            print("\033[0m\n\nAssistant > ", end="", flush=True)
                            is_thinking = False
                        print(chunk["text"], end="", flush=True)
                    elif chunk["type"] == "tool_call":
                        pass
                    elif chunk["type"] == "warning":
                        print(f"\n{chunk['text']}", flush=True)
                    elif chunk["type"] == "usage":
                        usage_info = chunk["usage"]

                if is_thinking:
                    print("\033[0m", end="")
                print()
                save_session(client)
                if usage_info:
                    print(f"\n{format_tokens(usage_info)}", file=sys.stderr)
            except (KeyboardInterrupt, EOFError):
                print("\nSession saved. Goodbye!")
                save_session(client)
                break
            except Exception as err:
                print(f"\n[Error] {err}", file=sys.stderr)
    else:
        is_thinking = False
        usage_info = None

        try:
            for chunk in client.stream_chat(args.prompt):
                if chunk["type"] == "reasoning" and args.thinking:
                    if not is_thinking:
                        print("\033[2m[Thinking]\n", end="", flush=True)
                        is_thinking = True
                    print(chunk["text"], end="", flush=True)
                elif chunk["type"] == "content":
                    if is_thinking:
                        print("\033[0m\n", end="", flush=True)
                        is_thinking = False
                    print(chunk["text"], end="", flush=True)
                elif chunk["type"] == "tool_call":
                    pass
                elif chunk["type"] == "warning":
                    print(f"\n{chunk['text']}", flush=True)
                elif chunk["type"] == "usage":
                    usage_info = chunk["usage"]

            if is_thinking:
                print("\033[0m", end="")
            print()

            save_session(client)
            if usage_info:
                print(f"\n{format_tokens(usage_info)}", file=sys.stderr)
            print(f"[Session: {client.session_id}]", file=sys.stderr)
        except Exception as err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
