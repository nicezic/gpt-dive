#!/usr/bin/env python3
"""Run OpenCode's DeepSeek V4.1 Flash Free model through the official CLI.

The free tier rejects direct third-party HTTP clients. Install and connect the
official OpenCode CLI before using this wrapper.

Examples:
    python3 scripts/zen_deepseek_byok.py "Hello"
    python3 scripts/zen_deepseek_byok.py --effort high "Hello"
    python3 scripts/zen_deepseek_byok.py -c "Follow up"
    python3 scripts/zen_deepseek_byok.py -s ses_ID "Follow up"
    python3 scripts/zen_deepseek_byok.py -i
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL = "opencode/deepseek-v4.1-flash-free"


def run_prompt(
    executable: str,
    prompt: str,
    *,
    effort: str,
    session: str | None = None,
    cont: bool = False,
) -> str:
    """Print the model's text and return its OpenCode session ID."""
    command = [
        executable,
        "run",
        "--format",
        "json",
        "--model",
        MODEL,
        "--agent",
        "plan",
        "--variant",
        effort,
    ]
    if session:
        command.extend(["--session", session])
    elif cont:
        command.append("--continue")
    command.append(prompt)

    session_id = session
    text_seen = False
    event_error = None
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("sessionID"):
                    session_id = event["sessionID"]
                if event.get("type") == "text":
                    message = (event.get("part") or {}).get("text")
                    if message:
                        print(message, end="", flush=True)
                        text_seen = True
                elif event.get("type") == "error":
                    event_error = str(event.get("error") or event)[:500]
            exit_code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise

        stderr_file.seek(0)
        stderr = stderr_file.read(1000).strip()

    if exit_code != 0 or event_error or not text_seen:
        details = event_error or stderr or "OpenCode returned no answer text"
        raise RuntimeError(f"OpenCode failed (exit={exit_code}): {details}")

    print()
    if session_id:
        print(f"[Session: {session_id}]", file=sys.stderr)
    return session_id or ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DeepSeek V4.1 Flash Free via official OpenCode CLI"
    )
    parser.add_argument("prompt", nargs="?")
    parser.add_argument("--effort", choices=["low", "high", "max"], default="high")
    parser.add_argument("-i", "--interactive", action="store_true")
    parser.add_argument("-c", "--continue", dest="cont", action="store_true")
    parser.add_argument("-s", "--session", help="OpenCode session ID")
    args = parser.parse_args()

    executable = shutil.which("opencode") or shutil.which(
        "opencode", path=str(Path.home() / ".local/share/pnpm/bin")
    )
    if not executable:
        print(
            "OpenCode CLI is not installed. Install the official 'opencode-ai' "
            "CLI and authenticate it, then retry. See https://opencode.ai/docs/",
            file=sys.stderr,
        )
        return 1

    try:
        if args.interactive or args.prompt is None:
            print(f"DeepSeek V4.1 Flash Free (effort: {args.effort})")
            print("Type exit/quit to stop, reset to start a new session.")
            session = args.session
            cont = args.cont
            while True:
                try:
                    prompt = input("\nYou > ").strip()
                except EOFError, KeyboardInterrupt:
                    print()
                    break
                if prompt.lower() in {"exit", "quit"}:
                    break
                if prompt.lower() == "reset":
                    session, cont = None, False
                    print("[New session]")
                elif prompt:
                    session = (
                        run_prompt(
                            executable,
                            prompt,
                            effort=args.effort,
                            session=session,
                            cont=cont,
                        )
                        or None
                    )
                    cont = False
        else:
            run_prompt(
                executable,
                args.prompt,
                effort=args.effort,
                session=args.session,
                cont=args.cont,
            )
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
