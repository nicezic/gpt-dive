from __future__ import annotations

import asyncio
from pathlib import Path

import gpt_dive.m3_gbrain_replay as replay_module


def test_load_capture_rows_reads_ndjson(tmp_path: Path) -> None:
    path = tmp_path / "capture.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"]}\n'
        '{"schema_version":1,"id":2,"tool_name":"query","query":"q2","source_ids":["pydantic-ai","pydantic-ai-harness"],"retrieved_slugs":["docs/b"]}\n'
    )
    rows = replay_module.load_capture_rows(path)
    assert [row["id"] for row in rows] == [1, 2]


def test_build_evidence_packet_labels_captured_pages() -> None:
    packet = replay_module.build_evidence_packet(
        [
            {"source_id": "pydantic-ai", "slug": "docs/agent", "page_text": "alpha"},
            {"source_id": "pydantic-ai-harness", "slug": "docs/harness", "page_text": "beta"},
        ]
    )
    assert packet == (
        "[E1] source=pydantic-ai slug=docs/agent\nalpha\n\n"
        "[E2] source=pydantic-ai-harness slug=docs/harness\nbeta"
    )


def test_run_replay_reports_controller_metrics(monkeypatch) -> None:
    async def fake_read(row, *, page_limit):
        assert page_limit == 4
        return [{"source_id": "pydantic-ai", "slug": "s", "page_text": "fact"}]

    async def fake_m3(**kwargs):
        assert kwargs["question"] == "How does X work?"
        assert kwargs["evidence"].startswith("[E1]")
        return {
            "ok": True,
            "done": False,
            "known": ["fact [E1]"],
            "missing": ["one detail"],
            "conflicts": [],
            "queries": ["find detail"],
            "attempts": 2,
        }

    monkeypatch.setattr(replay_module, "read_captured_pages", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    report = asyncio.run(
        replay_module.run_replay(
            [{"schema_version": 1, "id": 7, "tool_name": "query", "query": "How does X work?", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"]}],
            page_limit=4,
        )
    )
    assert report["rows"] == 1
    assert report["done_rows"] == 0
    assert report["unresolved_rows"] == 1
    assert report["retry_rows"] == 1
    assert report["proposed_queries"] == 1
    assert report["controller_failures"] == 0
    assert report["results"][0]["capture_id"] == 7
