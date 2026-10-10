from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _expand_env_path(value: str) -> Path:
    """Expand shell-style $HOME variables and ~ without invoking a shell."""
    return Path(os.path.expandvars(value)).expanduser()


def _wiki_path() -> Path:
    """Resolve the trusted wiki path used by Hermes, with ~/wiki fallback."""
    configured = os.environ.get("WIKI_PATH", "").strip()
    if not configured:
        hermes_env = Path.home() / ".hermes" / ".env"
        if hermes_env.is_file():
            for raw_line in hermes_env.read_text(errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "WIKI_PATH":
                    configured = value.strip().strip('"').strip("'")
                    break
    return _expand_env_path(configured or "$HOME/wiki").resolve()


def _parse_preload_files(preload_text: str) -> list[str]:
    """Extract preload file paths from JSON configuration."""
    try:
        data = json.loads(preload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed bootstrap preload JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise TypeError("bootstrap preload JSON must be an object")

    paths = data.get("preload_files")
    if paths is None:
        raise ValueError("bootstrap preload JSON missing 'preload_files' field")
    if not isinstance(paths, list):
        raise TypeError("bootstrap preload JSON 'preload_files' field must be a list")
    if not paths:
        raise ValueError(
            "bootstrap preload JSON 'preload_files' list must not be empty"
        )

    for path in paths:
        if not isinstance(path, str):
            raise TypeError("preload_files entries must be strings")
        if not path.strip():
            raise ValueError("preload_files entries must not be empty strings")

    return paths


def read_bootstrap_packet(wiki: Path) -> dict[str, Any]:
    """Assemble compact fresh-session orientation from the trusted Wiki preload map."""
    preload = wiki / "bootstrap" / "preload.json"
    if not preload.is_file():
        raise FileNotFoundError(f"bootstrap preload map not found: {preload}")

    preload_text = preload.read_text(errors="replace")
    preload_files = _parse_preload_files(preload_text)
    documents: list[dict[str, str]] = []
    warnings: list[str] = []

    for relative in preload_files:
        candidate = (wiki / relative).resolve()
        try:
            candidate.relative_to(wiki)
        except ValueError as exc:
            raise ValueError(
                f"bootstrap path escapes trusted wiki: {relative}"
            ) from exc

        if not candidate.is_file():
            warnings.append(f"missing preload document: {relative}")
            continue
        documents.append(
            {
                "path": relative,
                "content": candidate.read_text(errors="replace"),
            }
        )

    if not documents:
        raise RuntimeError(
            "bootstrap preload map resolved no readable preload documents"
        )

    preloaded_files = [doc["path"] for doc in documents]
    bootstrap_reminders = _read_reminder_sections(
        wiki, exclude_paths=set(preloaded_files)
    )
    chunks: list[str] = [f"$HOME = {Path.home()}"]
    for doc in documents:
        source = _display_source_path(wiki / doc["path"])
        chunks.append(f"---\n`$ cat {source}`\n\n{doc['content'].rstrip()}")
    if bootstrap_reminders:
        chunks.append(_format_reminder_sections(wiki, bootstrap_reminders))

    result: dict[str, Any] = {
        "wiki_path": str(wiki),
        "preload_path": str(preload),
        "preloaded_files": preloaded_files,
        "bootstrap_reminders": [
            {key: value for key, value in item.items() if key != "content"}
            for item in bootstrap_reminders
        ],
        "stdout": "\n\n".join(chunks) + "\n",
    }
    if warnings:
        result["warnings"] = warnings
    return result


_PERIODIC_REMINDER_CONFIG = "bootstrap/reminder.json"


def _parse_reminder_config(
    reminder_text: str,
) -> tuple[int, list[tuple[str, str | None]]]:
    """Parse reminder cadence plus ordered whole-file or Markdown section sources."""
    try:
        data = json.loads(reminder_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed reminder JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("reminder JSON must be an object")

    interval = data.get("interval")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError("reminder interval must be a positive integer")

    raw_files = data.get("reminder_files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("reminder_files must be a non-empty list")

    files: list[tuple[str, str | None]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise TypeError("reminder_files entries must be objects")
        path = item.get("path")
        section = item.get("section")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("reminder file path must be a non-empty string")
        if section is not None and (
            not isinstance(section, str) or not section.strip()
        ):
            raise ValueError(
                "reminder section must be a non-empty string when provided"
            )
        files.append((path, section))
    return interval, files


def read_periodic_reminder_config(
    wiki: Path,
) -> tuple[int, list[tuple[str, str | None]]]:
    path = wiki / _PERIODIC_REMINDER_CONFIG
    return _parse_reminder_config(path.read_text(errors="replace"))


def _read_reminder_sections(
    wiki: Path, *, exclude_paths: set[str] | None = None
) -> list[dict[str, str]]:
    """Read reminder sources in config order, optionally skipping whole source files."""
    _, files = read_periodic_reminder_config(wiki)
    excluded = exclude_paths or set()
    sections: list[dict[str, str]] = []
    for relative, heading in files:
        if relative in excluded:
            continue
        candidate = (wiki / relative).resolve()
        try:
            candidate.relative_to(wiki)
        except ValueError as exc:
            raise ValueError(f"reminder path escapes trusted wiki: {relative}") from exc
        text = candidate.read_text(errors="replace")
        if heading is None:
            sections.append({"path": relative, "content": text.rstrip()})
            continue
        match = re.search(
            rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## \S|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            raise ValueError(f"{relative} missing reminder section: {heading}")
        sections.append(
            {
                "path": relative,
                "section": heading,
                "content": f"## {heading}\n{match.group('body').rstrip()}",
            }
        )
    return sections


def _display_source_path(path: Path) -> str:
    """Render paths under the current home directory with a ~/ prefix."""
    resolved = path.resolve()
    home = Path.home().resolve()
    try:
        return f"~/{resolved.relative_to(home).as_posix()}"
    except ValueError:
        return str(resolved)


def _format_reminder_sections(wiki: Path, sections: list[dict[str, str]]) -> str:
    """Format reminder sections with one source-file marker per consecutive file group."""
    chunks: list[str] = []
    previous_path: str | None = None
    for item in sections:
        if item["path"] != previous_path:
            source = _display_source_path(wiki / item["path"])
            chunks.append(f"---\n`$ cat {source}`")
            previous_path = item["path"]
        chunks.append(item["content"])
    return "\n\n".join(chunks)


def read_periodic_reminder(wiki: Path) -> str:
    """Read every configured whole-file or section reminder in order."""
    return _format_reminder_sections(wiki, _read_reminder_sections(wiki))
