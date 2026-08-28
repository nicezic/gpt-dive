from __future__ import annotations

import os

from gpt_dive.process_identity import (
    process_matches,
    process_start_ticks,
    read_process_identity,
)


def test_live_process_identity_is_typed_and_prevents_pid_reuse() -> None:
    identity = read_process_identity(os.getpid())

    assert identity is not None
    assert identity.parent_pid > 0
    assert identity.start_ticks == process_start_ticks(os.getpid())
    assert process_matches(os.getpid(), identity.start_ticks)
    assert not process_matches(os.getpid(), identity.start_ticks + 1)
    assert read_process_identity(999_999_999) is None
