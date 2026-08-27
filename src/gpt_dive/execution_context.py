from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .execution_store import parse_time, utc_now


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Read-only runtime budget and artifact boundary inherited by capabilities."""

    execution_id: str
    work_deadline_monotonic: float
    artifact_dir: Path

    @classmethod
    def from_record(cls, record: dict[str, object]) -> ExecutionContext:
        remaining = max(
            0.0,
            (parse_time(str(record["work_deadline_at"])) - utc_now()).total_seconds(),
        )
        return cls(
            execution_id=str(record["execution_id"]),
            work_deadline_monotonic=time.monotonic() + remaining,
            artifact_dir=Path(str(record["artifact_dir"])),
        )

    @classmethod
    def for_test(
        cls, *, duration_seconds: float = 3590.0, artifact_dir: Path
    ) -> ExecutionContext:
        return cls(
            execution_id="test",
            work_deadline_monotonic=time.monotonic() + duration_seconds,
            artifact_dir=artifact_dir,
        )

    def remaining_seconds(self) -> float:
        return max(0.0, self.work_deadline_monotonic - time.monotonic())

    def child_budget(self, policy_seconds: float) -> float:
        if policy_seconds <= 0:
            raise ValueError("child capability policy must be greater than 0")
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise TimeoutError("Execution work budget is exhausted")
        return min(policy_seconds, remaining)

    def spill_path(self, *, prefix: str) -> Path:
        directory = self.artifact_dir / "capability-output"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / f"{prefix}-{uuid.uuid4().hex}.log"
