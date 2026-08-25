from __future__ import annotations

import asyncio
from pathlib import Path

import gpt_dive.m3_evidence_eval as eval_module


def test_load_cases_has_representative_fixed_set() -> None:
    cases = eval_module.load_cases(Path("tests/fixtures/m3_evidence_eval.json"))
    assert len(cases) == 13
    assert {case["name"] for case in cases} >= {
        "sufficient_single",
        "explicit_conflict",
        "final_round_missing",
        "ignore_source_instruction",
        "multi_fact_retention",
        "multi_part_completion_coverage",
        "distractor_relevance_focus",
    }


def test_score_result_checks_expected_shape() -> None:
    case = {
        "expect": {
            "done": True,
            "missing_empty": True,
            "queries_empty": True,
            "known_min": 1,
        }
    }
    passed, errors = eval_module.score_result(
        case,
        {
            "ok": True,
            "done": True,
            "known": ["fact"],
            "missing": [],
            "conflicts": [],
            "queries": [],
        },
    )
    assert passed is True
    assert errors == []


def test_score_result_reports_semantic_contract_failure() -> None:
    case = {"expect": {"done": True, "missing_empty": True}}
    passed, errors = eval_module.score_result(
        case,
        {
            "ok": True,
            "done": False,
            "known": [],
            "missing": ["x"],
            "conflicts": [],
            "queries": [],
        },
    )
    assert passed is False
    assert len(errors) == 2


def test_score_result_checks_required_semantic_substrings() -> None:
    case = {
        "expect": {
            "known_contains": ["10,000", "[E1]"],
            "missing_contains": ["cleanup ttl"],
            "queries_contains": ["cleanup"],
        }
    }
    result = {
        "ok": True,
        "done": False,
        "known": ["The threshold is 8,000 characters [E1]."],
        "missing": ["Cleanup TTL is still required."],
        "conflicts": [],
        "queries": ["Find the cleanup policy."],
    }
    passed, errors = eval_module.score_result(case, result)
    assert passed is False
    assert errors == ["known: missing required substring '10,000'"]


def test_run_cases_collects_retry_and_query_metrics(monkeypatch) -> None:
    async def fake_invoke_m3_evidence(**kwargs):
        return {
            "ok": True,
            "done": False,
            "known": [],
            "missing": ["x"],
            "conflicts": [],
            "queries": ["q"],
            "attempts": 2,
        }

    monkeypatch.setattr(eval_module, "invoke_m3_evidence", fake_invoke_m3_evidence)
    cases = [
        {
            "name": "x",
            "question": "q",
            "evidence": "e",
            "expect": {"done": False, "missing_min": 1, "queries_min": 1},
        }
    ]
    report = asyncio.run(eval_module.run_cases(cases, timeout=30.0))
    assert report["passed"] == 1
    assert report["retry_cases"] == 1
    assert report["rows"][0]["query_count"] == 1


def test_run_cases_repeat_reports_per_case_stability(monkeypatch) -> None:
    calls = 0

    async def fake_invoke_m3_evidence(**kwargs):
        nonlocal calls
        calls += 1
        passed = calls != 2
        return {
            "ok": True,
            "done": passed,
            "known": ["fact"] if passed else [],
            "missing": [] if passed else ["x"],
            "conflicts": [],
            "queries": [],
            "attempts": 2 if calls == 3 else 1,
        }

    monkeypatch.setattr(eval_module, "invoke_m3_evidence", fake_invoke_m3_evidence)
    cases = [
        {
            "name": "x",
            "question": "q",
            "evidence": "e",
            "expect": {"done": True, "missing_empty": True, "known_min": 1},
        }
    ]
    report = asyncio.run(eval_module.run_cases(cases, timeout=30.0, repeat=3))
    assert report["repeat"] == 3
    assert report["samples"] == 3
    assert report["passed"] == 2
    assert report["failed"] == 1
    assert report["retry_samples"] == 1
    assert report["retry_cases"] == 1
    assert report["flaky_cases"] == ["x"]
    assert [
        {
            key: stat[key]
            for key in ("run", "passed", "failed", "pass_rate", "retry_samples")
        }
        for stat in report["run_stats"]
    ] == [
        {"run": 1, "passed": 1, "failed": 0, "pass_rate": 1.0, "retry_samples": 0},
        {"run": 2, "passed": 0, "failed": 1, "pass_rate": 0.0, "retry_samples": 0},
        {"run": 3, "passed": 1, "failed": 0, "pass_rate": 1.0, "retry_samples": 1},
    ]
    assert all(stat["mean_latency_ms"] >= 0 for stat in report["run_stats"])
    assert report["case_stats"] == [
        {
            "name": "x",
            "runs": 3,
            "passed": 2,
            "failed": 1,
            "pass_rate": 2 / 3,
            "retry_runs": 1,
        }
    ]
