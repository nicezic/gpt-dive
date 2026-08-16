from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from .m3_evidence import invoke_m3_evidence


def load_cases(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text())
    if not isinstance(value, list) or not value:
        raise ValueError("eval cases must be a non-empty JSON array")
    return value


def score_result(case: dict[str, Any], result: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    expect = case.get("expect", {})
    if not result.get("ok"):
        return False, [str(result.get("error", "model/controller failure"))]
    checks = {
        "done": result.get("done"),
        "missing_empty": not result.get("missing"),
        "queries_empty": not result.get("queries"),
        "conflicts_empty": not result.get("conflicts"),
    }
    for key, actual in checks.items():
        if key in expect and actual != expect[key]:
            errors.append(f"{key}: expected {expect[key]!r}, got {actual!r}")
    for field in ("known", "missing", "conflicts", "queries"):
        count = len(result.get(field, []))
        minimum = expect.get(f"{field}_min")
        maximum = expect.get(f"{field}_max")
        if minimum is not None and count < minimum:
            errors.append(f"{field}: expected >= {minimum}, got {count}")
        if maximum is not None and count > maximum:
            errors.append(f"{field}: expected <= {maximum}, got {count}")
    return not errors, errors


async def run_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        started = time.monotonic()
        result = await invoke_m3_evidence(
            question=case["question"],
            evidence=case["evidence"],
            round_number=case.get("round_number", 1),
            max_rounds=case.get("max_rounds", 3),
            max_queries=case.get("max_queries", 3),
        )
        passed, errors = score_result(case, result)
        rows.append({
            "name": case["name"],
            "passed": passed,
            "errors": errors,
            "attempts": result.get("attempts", 1),
            "done": result.get("done"),
            "query_count": len(result.get("queries", [])),
            "latency_ms": round((time.monotonic() - started) * 1000),
        })
    passed = sum(1 for row in rows if row["passed"])
    return {
        "cases": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": passed / len(rows) if rows else 0.0,
        "retry_cases": sum(1 for row in rows if row["attempts"] > 1),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fixed live MiniMax-M3 evidence-controller eval set.")
    parser.add_argument("--cases", type=Path, default=Path("tests/fixtures/m3_evidence_eval.json"))
    args = parser.parse_args()
    report = asyncio.run(run_cases(load_cases(args.cases)))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
