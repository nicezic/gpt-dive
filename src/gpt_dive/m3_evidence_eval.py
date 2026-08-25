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


def score_result(
    case: dict[str, Any], result: dict[str, Any]
) -> tuple[bool, list[str]]:
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
        items = result.get(field, [])
        count = len(items)
        minimum = expect.get(f"{field}_min")
        maximum = expect.get(f"{field}_max")
        if minimum is not None and count < minimum:
            errors.append(f"{field}: expected >= {minimum}, got {count}")
        if maximum is not None and count > maximum:
            errors.append(f"{field}: expected <= {maximum}, got {count}")

        required_substrings = expect.get(f"{field}_contains", [])
        haystack = "\n".join(str(item) for item in items).casefold()
        for required in required_substrings:
            needle = str(required).casefold()
            if needle not in haystack:
                errors.append(f"{field}: missing required substring {required!r}")
    return not errors, errors


async def run_cases(
    cases: list[dict[str, Any]], *, timeout: float, repeat: int = 1
) -> dict[str, Any]:
    if repeat <= 0:
        raise ValueError("repeat must be greater than 0")

    rows: list[dict[str, Any]] = []
    for run in range(1, repeat + 1):
        for case in cases:
            started = time.monotonic()
            result = await invoke_m3_evidence(
                question=case["question"],
                evidence=case["evidence"],
                round_number=case.get("round_number", 1),
                max_rounds=case.get("max_rounds", 3),
                max_queries=case.get("max_queries", 3),
                timeout=timeout,
            )
            passed, errors = score_result(case, result)
            rows.append(
                {
                    "name": case["name"],
                    "run": run,
                    "passed": passed,
                    "errors": errors,
                    "attempts": result.get("attempts", 1),
                    "done": result.get("done"),
                    "query_count": len(result.get("queries", [])),
                    "latency_ms": round((time.monotonic() - started) * 1000),
                }
            )

    case_stats: list[dict[str, Any]] = []
    flaky_cases: list[str] = []
    for case in cases:
        name = case["name"]
        samples = [row for row in rows if row["name"] == name]
        passed_for_case = sum(1 for row in samples if row["passed"])
        failed_for_case = len(samples) - passed_for_case
        if passed_for_case and failed_for_case:
            flaky_cases.append(name)
        case_stats.append(
            {
                "name": name,
                "runs": len(samples),
                "passed": passed_for_case,
                "failed": failed_for_case,
                "pass_rate": passed_for_case / len(samples) if samples else 0.0,
                "retry_runs": sum(1 for row in samples if row["attempts"] > 1),
            }
        )

    run_stats: list[dict[str, Any]] = []
    for run in range(1, repeat + 1):
        samples = [row for row in rows if row["run"] == run]
        passed_for_run = sum(1 for row in samples if row["passed"])
        run_stats.append(
            {
                "run": run,
                "passed": passed_for_run,
                "failed": len(samples) - passed_for_run,
                "pass_rate": passed_for_run / len(samples) if samples else 0.0,
                "retry_samples": sum(1 for row in samples if row["attempts"] > 1),
                "mean_latency_ms": round(
                    sum(row["latency_ms"] for row in samples) / len(samples)
                )
                if samples
                else 0,
            }
        )

    passed = sum(1 for row in rows if row["passed"])
    return {
        "cases": len(cases),
        "repeat": repeat,
        "samples": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": passed / len(rows) if rows else 0.0,
        "retry_samples": sum(1 for row in rows if row["attempts"] > 1),
        "retry_cases": sum(1 for stat in case_stats if stat["retry_runs"] > 0),
        "flaky_cases": flaky_cases,
        "run_stats": run_stats,
        "case_stats": case_stats,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the fixed live MiniMax-M3 evidence-controller eval set."
    )
    parser.add_argument(
        "--cases", type=Path, default=Path("tests/fixtures/m3_evidence_eval.json")
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run the fixed case set N times sequentially.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        required=True,
        help="Per M3 evidence call timeout in seconds.",
    )
    args = parser.parse_args()
    report = asyncio.run(
        run_cases(load_cases(args.cases), timeout=args.timeout, repeat=args.repeat)
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
