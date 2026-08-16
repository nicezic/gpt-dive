from __future__ import annotations

import asyncio
from pathlib import Path

import gpt_dive.m3_gbrain_replay as replay_module


def test_load_capture_rows_reads_ndjson(tmp_path: Path) -> None:
    path = tmp_path / "capture.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"],"retrieved_chunk_ids":[11]}\n'
        '{"schema_version":1,"id":2,"tool_name":"query","query":"q2","source_ids":["pydantic-ai","pydantic-ai-harness"],"retrieved_slugs":["docs/b"],"retrieved_chunk_ids":[22]}\n'
    )
    rows = replay_module.load_capture_rows(path)
    assert [row["id"] for row in rows] == [1, 2]


def test_load_capture_rows_rejects_old_export_without_chunk_ids(tmp_path: Path) -> None:
    path = tmp_path / "old-capture.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"]}\n'
    )
    try:
        replay_module.load_capture_rows(path)
    except ValueError as exc:
        assert "retrieved_chunk_ids" in str(exc)
    else:
        raise AssertionError("old capture without chunk ids must fail closed")


def test_build_evidence_packet_labels_captured_chunks() -> None:
    packet = replay_module.build_evidence_packet(
        [
            {"id": 11, "source_id": "pydantic-ai", "slug": "docs/agent", "chunk_text": "alpha"},
            {"id": 22, "source_id": "pydantic-ai-harness", "slug": "docs/harness", "chunk_text": "beta"},
        ]
    )
    assert packet == (
        "[E1] chunk_id=11 source=pydantic-ai slug=docs/agent\nalpha\n\n"
        "[E2] chunk_id=22 source=pydantic-ai-harness slug=docs/harness\nbeta"
    )


def test_run_replay_reports_controller_metrics(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        assert chunk_limit == 4
        return [{"id": 31, "source_id": "pydantic-ai", "slug": "s", "chunk_text": "fact"}]

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

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    report = asyncio.run(
        replay_module.run_replay(
            [{"schema_version": 1, "id": 7, "tool_name": "query", "query": "How does X work?", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"], "retrieved_chunk_ids": [31]}],
            chunk_limit=4,
        )
    )
    assert report["rows"] == 1
    assert report["done_rows"] == 0
    assert report["unresolved_rows"] == 1
    assert report["retry_rows"] == 1
    assert report["proposed_queries"] == 1
    assert report["controller_failures"] == 0
    assert report["results"][0]["capture_id"] == 7
    assert report["results"][0]["chunk_count"] == 1
