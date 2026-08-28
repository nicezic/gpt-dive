from __future__ import annotations

from pathlib import Path

from gpt_dive.runtime_env import build_runtime_path


def test_build_runtime_path_adds_stable_user_bins_without_duplicates() -> None:
    guard_bin = "/tmp/guard-bin"
    bun_bin = str(Path.home() / ".bun" / "bin")

    entries = build_runtime_path(
        guard_bin,
        inherited=f"/usr/bin:{bun_bin}:/bin",
    ).split(":")

    assert entries[0] == guard_bin
    assert str(Path.home() / ".local" / "share" / "pnpm" / "bin") in entries
    assert str(Path.home() / ".local" / "share" / "pnpm") in entries
    assert bun_bin in entries
    assert str(Path.home() / ".local" / "bin") in entries
    assert str(Path.home() / ".cargo" / "bin") in entries
    assert entries.count(bun_bin) == 1
