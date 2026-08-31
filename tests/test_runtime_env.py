from __future__ import annotations

from pathlib import Path

from gpt_dive.runtime_env import build_runtime_path


def test_build_runtime_path_prefers_guard_then_mise_without_legacy_toolchains() -> None:
    home = Path.home()
    guard_bin = "/tmp/guard-bin"
    mise_shims = str(home / ".local" / "share" / "mise" / "shims")

    entries = build_runtime_path(
        guard_bin,
        inherited=f"/usr/bin:{mise_shims}:/bin",
    ).split(":")

    assert entries[:2] == [guard_bin, mise_shims]
    assert str(home / ".local" / "share" / "pnpm" / "bin") not in entries
    assert str(home / ".local" / "share" / "pnpm") not in entries
    assert str(home / ".bun" / "bin") not in entries
    assert str(home / ".local" / "bin") in entries
    assert str(home / ".cargo" / "bin") in entries
    assert entries.count(mise_shims) == 1
