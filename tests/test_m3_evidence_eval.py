from __future__ import annotations

import asyncio
from pathlib import Path

import gpt_dive.m3_evidence_eval as eval_module


def test_load_cases_has_representative_fixed_set() -> None:
    cases = eval_module.load_cases(Path("tests/fixtures/m3_evidence_eval.json"))
    assert len(cases) == 10
    assert {case["name"] for case in cases} >= {
        "sufficient_single",
        "explicit_conflict",
        "final_round_missing",
        "ignore_source_instruction",
    }


def test_score_result_checks_expected_shape() -> None:
    case = {"expect": {"done": True, "missing_empty": True, "queries_empty": True, "known_min": 1}}
    passed, errors = eval_module.score_result(
        case,
        {"ok": True, "done": True, "known": ["fact"], "missing": [], "conflicts": [], "queries": []},
    )
    assert passed is True
    assert errors == []


def test_score_result_reports_semantic_contract_failure() -> None:
    case = {"expect": {"done": True, "missing_empty": True}}
    passed, errors = eval_module.score_result(
        case,
        {"ok": True, "done": False, "known": [], "missing": ["x"], "conflicts": [], "queries": []},
    )
    assert passed is False
    assert len(errors) == 2


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
    report = asyncio.run(eval_module.run_cases(cases))
    assert report["passed"] == 1
    assert report["retry_cases"] == 1
    assert report["rows"][0]["query_count"] == 1
