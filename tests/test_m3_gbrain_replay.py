from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import gpt_dive.m3_gbrain_replay as replay_module


def test_load_capture_rows_reads_ndjson(tmp_path: Path) -> None:
    path = tmp_path / "capture.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"],"retrieved_chunk_ids":[11],"created_at":"2026-08-16T16:10:20.070Z","as_of_ts":null}\n'
        '{"schema_version":1,"id":2,"tool_name":"query","query":"q2","source_ids":["pydantic-ai","pydantic-ai-harness"],"retrieved_slugs":["docs/b"],"retrieved_chunk_ids":[22],"created_at":"2026-08-16T16:10:29.252Z","as_of_ts":null}\n'
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


def test_load_capture_rows_rejects_misaligned_chunk_hashes(tmp_path: Path) -> None:
    path = tmp_path / "bad-hashes.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"],"retrieved_chunk_ids":[11,12],"retrieved_chunk_hashes":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],"created_at":"2026-08-16T16:10:20.070Z","as_of_ts":null}\n'
    )
    try:
        replay_module.load_capture_rows(path)
    except ValueError as exc:
        assert "retrieved_chunk_hashes" in str(exc)
    else:
        raise AssertionError("misaligned chunk hashes must fail closed")


def test_empty_chunk_hashes_are_legacy_provenance(tmp_path: Path) -> None:
    path = tmp_path / "legacy-empty-hashes.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"],"retrieved_chunk_ids":[11],"retrieved_chunk_hashes":[],"created_at":"2026-08-16T16:10:20.070Z","as_of_ts":null}\n'
    )
    row = replay_module.load_capture_rows(path)[0]
    assert replay_module.verify_captured_chunk_hashes(
        row, [{"id": 11, "chunk_text": "current"}], chunk_limit=4
    ) is False


def test_build_evidence_packet_labels_captured_chunks() -> None:
    packet = replay_module.build_evidence_packet(
        [
            {
                "id": 11,
                "source_id": "pydantic-ai",
                "slug": "docs/agent",
                "title": "Agent API",
                "effective_date": "2026-08-15",
                "effective_date_source": "published",
                "chunk_text": "alpha",
            },
            {
                "id": 22,
                "source_id": "pydantic-ai-harness",
                "slug": "docs/harness",
                "title": "Harness Guide",
                "effective_date": None,
                "effective_date_source": None,
                "chunk_text": "beta",
            },
        ]
    )
    assert packet == (
        '[E1] chunk_id=11 source=pydantic-ai slug=docs/agent title="Agent API" '
        'effective_date=2026-08-15 effective_date_source=published\nalpha\n\n'
        '[E2] chunk_id=22 source=pydantic-ai-harness slug=docs/harness title="Harness Guide"\nbeta'
    )


def test_build_evidence_packet_omits_fallback_date_value() -> None:
    packet = replay_module.build_evidence_packet(
        [
            {
                "id": 33,
                "source_id": "pydantic-ai",
                "slug": "docs/fallback",
                "title": "Fallback Date",
                "effective_date": "2026-08-16",
                "effective_date_source": "fallback",
                "chunk_text": "gamma",
            }
        ]
    )
    assert "effective_date=2026-08-16" not in packet
    assert "effective_date_source=fallback" in packet


def test_verify_captured_chunk_hashes_accepts_exact_text() -> None:
    row = {
        "retrieved_chunk_ids": [11, 22],
        "retrieved_chunk_hashes": [
            hashlib.sha256(b"alpha").hexdigest(),
            hashlib.sha256(b"beta").hexdigest(),
        ],
    }
    chunks = [{"id": 11, "chunk_text": "alpha"}, {"id": 22, "chunk_text": "beta"}]
    assert replay_module.verify_captured_chunk_hashes(row, chunks, chunk_limit=4) is True


def test_verify_captured_chunk_hashes_rejects_text_drift() -> None:
    row = {
        "retrieved_chunk_ids": [11],
        "retrieved_chunk_hashes": [hashlib.sha256(b"old").hexdigest()],
    }
    chunks = [{"id": 11, "chunk_text": "new"}]
    try:
        replay_module.verify_captured_chunk_hashes(row, chunks, chunk_limit=4)
    except RuntimeError as exc:
        assert "hash drift" in str(exc)
        assert "11" in str(exc)
    else:
        raise AssertionError("changed chunk text must fail exact replay")


def test_reject_post_capture_page_updates_detects_rewritten_chunk_text() -> None:
    row = {"created_at": "2026-08-16T16:10:20.070Z"}
    chunks = [
        {"id": 11, "page_updated_at": "2026-08-16T16:10:20.000+00:00"},
        {"id": 22, "page_updated_at": "2026-08-16T16:11:00.000+00:00"},
    ]
    try:
        replay_module.reject_post_capture_page_updates(row, chunks)
    except RuntimeError as exc:
        assert "22" in str(exc)
        assert "updated after capture" in str(exc)
    else:
        raise AssertionError("post-capture page update must fail historical replay")


def test_reject_post_capture_page_updates_accepts_original_snapshot() -> None:
    row = {"created_at": "2026-08-16T16:10:20.070Z"}
    chunks = [
        {"id": 11, "page_updated_at": "2026-08-15T10:00:00.000+00:00"},
        {"id": 22, "page_updated_at": "2026-08-16T16:10:20.000+00:00"},
    ]
    replay_module.reject_post_capture_page_updates(row, chunks)


def test_run_replay_reports_controller_metrics(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        assert chunk_limit == 4
        return [
            {
                "id": 31,
                "source_id": "pydantic-ai",
                "slug": "s",
                "title": "Source Title",
                # Page-level metadata changed after capture, but the exact chunk
                # text is unchanged. New hash provenance must avoid a false rejection.
                "page_updated_at": "2026-08-16T17:00:00.000+00:00",
                "effective_date": "2026-08-16",
                "effective_date_source": "published",
                "chunk_text": "fact",
            }
        ]

    async def fake_m3(**kwargs):
        assert kwargs["question"] == (
            "How does X work?\n\n"
            "Historical replay boundary: interpret current/latest/now relative to "
            "2026-08-16T16:10:29.252Z (captured query time)."
        )
        assert kwargs["evidence"].startswith("[E1]")
        return {
            "ok": True,
            "done": False,
            "known": ["fact [E1]"],
            "missing": ["one detail"],
            "conflicts": [],
            "queries": ["find detail"],
            "attempts": 2,
            "validation_errors": ["missing must be empty when done is true"],
        }

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    report = asyncio.run(
        replay_module.run_replay(
            [{"schema_version": 1, "id": 7, "tool_name": "query", "query": "How does X work?", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"], "retrieved_chunk_ids": [31], "retrieved_chunk_hashes": [hashlib.sha256(b"fact").hexdigest()], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}],
            chunk_limit=4,
        )
    )
    assert report["rows"] == 1
    assert report["done_rows"] == 0
    assert report["unresolved_rows"] == 1
    assert report["retry_rows"] == 1
    assert report["proposed_queries"] == 1
    assert report["controller_failures"] == 0
    assert report["validation_error_counts"] == {"missing must be empty when done is true": 1}
    assert report["capture_stability"] == [{"capture_id": 7, "samples": 1, "successful_samples": 1, "done_true": 0, "done_false": 1, "completion_stable": True, "known_evidence_label_sets": [["[E1]"]], "known_evidence_coverage_stable": True, "critical_evidence_labels": [], "critical_evidence_scored_runs": 0, "critical_evidence_recall_range": None, "critical_evidence_omission_runs": 0, "known_count_range": [1, 1], "missing_count_range": [1, 1], "query_count_range": [1, 1], "decision_shape_stable": True}]
    assert report["results"][0]["capture_id"] == 7
    assert report["results"][0]["chunk_count"] == 1
    assert report["results"][0]["excluded_future_chunks"] == 0
    assert report["results"][0]["schema_pack_checked"] is False
    assert report["results"][0]["chunk_hashes_checked"] is True


def test_validation_error_counts_group_dynamic_messages_by_invariant(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        return [{
            "id": row["retrieved_chunk_ids"][0],
            "source_id": "pydantic-ai",
            "slug": "s",
            "page_updated_at": "2026-08-16T15:00:00+00:00",
            "effective_date": None,
            "effective_date_source": None,
            "chunk_text": "fact",
        }]

    outputs = iter([
        {
            "ok": True, "done": True, "known": ["a [E1]"], "missing": [],
            "conflicts": [], "queries": [], "attempts": 2,
            "validation_errors": ["known item must cite an evidence label: 'first fact'"],
        },
        {
            "ok": True, "done": True, "known": ["b [E1]"], "missing": [],
            "conflicts": [], "queries": [], "attempts": 2,
            "validation_errors": ["known item must cite an evidence label: 'different fact'"],
        },
    ])

    async def fake_m3(**kwargs):
        return next(outputs)

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    rows = [
        {
            "schema_version": 1, "id": i, "tool_name": "query", "query": f"q{i}",
            "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"],
            "retrieved_chunk_ids": [i], "retrieved_chunk_hashes": [],
            "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None,
        }
        for i in (1, 2)
    ]
    report = asyncio.run(replay_module.run_replay(rows))

    assert report["validation_error_counts"] == {"known item must cite an evidence label": 2}
    assert report["results"][0]["controller"]["validation_errors"] == [
        "known item must cite an evidence label: 'first fact'"
    ]



def test_run_replay_repeat_reports_serving_window_stats(monkeypatch) -> None:
    calls = 0

    async def fake_read(row, *, chunk_limit):
        return [{
            "id": row["retrieved_chunk_ids"][0],
            "source_id": "pydantic-ai",
            "slug": "s",
            "page_updated_at": "2026-08-16T15:00:00+00:00",
            "effective_date": None,
            "effective_date_source": None,
            "chunk_text": "fact",
        }]

    async def fake_m3(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return {
                "ok": True,
                "done": False,
                "known": ["fact [E1]"],
                "missing": ["detail"],
                "conflicts": [],
                "queries": ["find detail"],
                "attempts": 2,
                "validation_errors": ["known item must cite an evidence label: 'fact'"],
            }
        return {
            "ok": True,
            "done": True,
            "known": ["fact [E1]"],
            "missing": [],
            "conflicts": [],
            "queries": [],
            "attempts": 1,
            "validation_errors": [],
        }

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {
        "schema_version": 1,
        "id": 7,
        "tool_name": "query",
        "query": "q",
        "source_ids": ["pydantic-ai"],
        "retrieved_slugs": ["s"],
        "retrieved_chunk_ids": [31],
        "retrieved_chunk_hashes": [],
        "created_at": "2026-08-16T16:10:29.252Z",
        "as_of_ts": None,
    }

    report = asyncio.run(replay_module.run_replay([row], repeat=3))

    assert report["rows"] == 1
    assert report["repeat"] == 3
    assert report["samples"] == 3
    assert report["done_rows"] == 2
    assert report["unresolved_rows"] == 1
    assert report["retry_rows"] == 1
    assert report["validation_error_counts"] == {"known item must cite an evidence label": 1}
    assert [item["run"] for item in report["results"]] == [1, 2, 3]
    assert report["run_stats"] == [
        {
            "run": 1,
            "done_rows": 1,
            "unresolved_rows": 0,
            "retry_rows": 0,
            "proposed_queries": 0,
            "controller_failures": 0,
            "validation_error_counts": {},
        },
        {
            "run": 2,
            "done_rows": 0,
            "unresolved_rows": 1,
            "retry_rows": 1,
            "proposed_queries": 1,
            "controller_failures": 0,
            "validation_error_counts": {"known item must cite an evidence label": 1},
        },
        {
            "run": 3,
            "done_rows": 1,
            "unresolved_rows": 0,
            "retry_rows": 0,
            "proposed_queries": 0,
            "controller_failures": 0,
            "validation_error_counts": {},
        },
    ]


def test_run_replay_preserves_all_captured_chunks_by_default(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        assert chunk_limit is None
        return [
            {
                "id": i,
                "source_id": "pydantic-ai",
                "slug": f"s{i}",
                "page_updated_at": "2026-08-16T15:00:00+00:00",
                "effective_date": None,
                "effective_date_source": None,
                "chunk_text": f"fact {i}",
            }
            for i in range(1, 7)
        ]

    async def fake_m3(**kwargs):
        for i in range(1, 7):
            assert f"[E{i}]" in kwargs["evidence"]
        return {
            "ok": True,
            "done": True,
            "known": ["all facts"],
            "missing": [],
            "conflicts": [],
            "queries": [],
            "attempts": 1,
        }

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {
        "schema_version": 1,
        "id": 8,
        "tool_name": "query",
        "query": "q",
        "source_ids": ["pydantic-ai"],
        "retrieved_slugs": [f"s{i}" for i in range(1, 7)],
        "retrieved_chunk_ids": list(range(1, 7)),
        "retrieved_chunk_hashes": [],
        "created_at": "2026-08-16T16:10:29.252Z",
        "as_of_ts": None,
    }
    report = asyncio.run(replay_module.run_replay([row]))
    assert report["results"][0]["chunk_count"] == 6

def test_replay_question_prefers_explicit_as_of_ts() -> None:
    row = {
        "query": "Which version is current?",
        "created_at": "2026-08-16T16:10:29.252Z",
        "as_of_ts": "2026-08-15T12:00:00.000Z",
    }
    assert replay_module.replay_question(row) == (
        "Which version is current?\n\n"
        "Historical replay boundary: interpret current/latest/now relative to "
        "2026-08-15T12:00:00.000Z (captured as-of time)."
    )


def test_load_capture_rows_rejects_invalid_created_at(tmp_path: Path) -> None:
    path = tmp_path / "bad-time.ndjson"
    path.write_text(
        '{"schema_version":1,"id":1,"tool_name":"query","query":"q1","source_ids":["pydantic-ai"],"retrieved_slugs":["docs/a"],"retrieved_chunk_ids":[11],"created_at":"not-a-time","as_of_ts":null}\n'
    )
    try:
        replay_module.load_capture_rows(path)
    except ValueError as exc:
        assert "invalid created_at" in str(exc)
    else:
        raise AssertionError("invalid created_at must fail closed")


def test_filter_future_temporal_evidence_excludes_post_boundary_content() -> None:
    row = {
        "query": "Which version is current?",
        "created_at": "2026-08-16T00:00:00Z",
        "as_of_ts": None,
    }
    chunks = [
        {"id": 1, "effective_date": "2026-08-15", "effective_date_source": "published"},
        {"id": 2, "effective_date": "2026-08-17", "effective_date_source": "published"},
        {"id": 3, "effective_date": "2026-08-18", "effective_date_source": "fallback"},
    ]
    kept, excluded = replay_module.filter_future_temporal_evidence(row, chunks)
    assert [chunk["id"] for chunk in kept] == [1, 3]
    assert excluded == 1


def test_filter_future_temporal_evidence_keeps_non_temporal_question() -> None:
    row = {
        "query": "How does version selection work?",
        "created_at": "2026-08-16T00:00:00Z",
        "as_of_ts": None,
    }
    chunks = [{"id": 2, "effective_date": "2026-08-17", "effective_date_source": "published"}]
    kept, excluded = replay_module.filter_future_temporal_evidence(row, chunks)
    assert kept == chunks
    assert excluded == 0


def test_schema_pack_provenance_legacy_capture_skips_check() -> None:
    row = {"schema_pack_per_source": None}
    assert asyncio.run(replay_module.verify_schema_pack_provenance(row)) is False


def test_schema_pack_provenance_accepts_exact_match(monkeypatch) -> None:
    snapshot = {
        "pydantic-ai": {
            "pack_name": "gbrain-base-v2",
            "pack_version": "1.0.0",
            "manifest_sha8": "deadbeef",
            "alias_closure_resolved": {"note": ["memo", "note"]},
        }
    }

    async def fake_current(row):
        return snapshot

    monkeypatch.setattr(replay_module, "read_current_schema_pack_snapshot", fake_current)
    assert asyncio.run(replay_module.verify_schema_pack_provenance({"schema_pack_per_source": snapshot})) is True



def test_schema_pack_provenance_allows_source_commit_drift(monkeypatch) -> None:
    captured = {
        "pydantic-ai": {
            "pack_name": "gbrain-base-v2",
            "pack_version": "1.0.0",
            "manifest_sha8": "deadbeef",
            "alias_closure_resolved": {"note": ["memo", "note"]},
            "source_commit": "old123",
        }
    }
    current = {
        "pydantic-ai": {
            "pack_name": "gbrain-base-v2",
            "pack_version": "1.0.0",
            "manifest_sha8": "deadbeef",
            "alias_closure_resolved": {"note": ["memo", "note"]},
            "source_commit": "new456",
        }
    }

    async def fake_current(row):
        return current

    monkeypatch.setattr(replay_module, "read_current_schema_pack_snapshot", fake_current)
    row = {"schema_pack_per_source": captured}
    assert asyncio.run(replay_module.verify_schema_pack_provenance(row)) is True
    assert replay_module.captured_source_commits(row) == {"pydantic-ai": "old123"}

def test_schema_pack_provenance_rejects_current_pack_drift(monkeypatch) -> None:
    captured = {
        "pydantic-ai": {
            "pack_name": "gbrain-base-v2",
            "pack_version": "1.0.0",
            "manifest_sha8": "deadbeef",
            "alias_closure_resolved": {"note": ["memo", "note"]},
        }
    }
    current = {
        "pydantic-ai": {
            "pack_name": "gbrain-base-v2",
            "pack_version": "1.0.1",
            "manifest_sha8": "cafebabe",
            "alias_closure_resolved": {"note": ["memo", "note"]},
        }
    }

    async def fake_current(row):
        return current

    monkeypatch.setattr(replay_module, "read_current_schema_pack_snapshot", fake_current)
    try:
        asyncio.run(replay_module.verify_schema_pack_provenance({"schema_pack_per_source": captured}))
    except RuntimeError as exc:
        assert "schema-pack provenance drift" in str(exc)
    else:
        raise AssertionError("schema-pack drift must fail historical replay")


def test_capture_stability_detects_completion_flip_across_repeats(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        return [{"id": 31, "source_id": "pydantic-ai", "slug": "s", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact"}]

    outputs = iter([
        {"ok": True, "done": False, "known": ["fact [E1]"], "missing": ["detail"], "conflicts": [], "queries": ["detail"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": True, "known": ["fact [E1]"], "missing": [], "conflicts": [], "queries": [], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": ["fact [E1]"], "missing": ["detail"], "conflicts": [], "queries": ["detail"], "attempts": 1, "validation_errors": []},
    ])

    async def fake_m3(**kwargs):
        return next(outputs)

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {"schema_version": 1, "id": 7, "tool_name": "query", "query": "q", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"], "retrieved_chunk_ids": [31], "retrieved_chunk_hashes": [], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}

    report = asyncio.run(replay_module.run_replay([row], repeat=3))

    assert report["capture_stability"] == [{"capture_id": 7, "samples": 3, "successful_samples": 3, "done_true": 1, "done_false": 2, "completion_stable": False, "known_evidence_label_sets": [["[E1]"]], "known_evidence_coverage_stable": True, "critical_evidence_labels": [], "critical_evidence_scored_runs": 0, "critical_evidence_recall_range": None, "critical_evidence_omission_runs": 0, "known_count_range": [1, 1], "missing_count_range": [0, 1], "query_count_range": [0, 1], "decision_shape_stable": False}]


def test_capture_stability_detects_shape_drift_when_done_is_stable(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        return [{"id": 31, "source_id": "pydantic-ai", "slug": "s", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact"}]

    outputs = iter([
        {"ok": True, "done": False, "known": ["a [E1]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": ["a [E1]", "b [E1]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": [], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
    ])

    async def fake_m3(**kwargs):
        return next(outputs)

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {"schema_version": 1, "id": 20, "tool_name": "query", "query": "q", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"], "retrieved_chunk_ids": [31], "retrieved_chunk_hashes": [], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}

    report = asyncio.run(replay_module.run_replay([row], repeat=3))
    stability = report["capture_stability"][0]
    assert stability["completion_stable"] is True
    assert stability["known_count_range"] == [0, 2]
    assert stability["missing_count_range"] == [1, 1]
    assert stability["query_count_range"] == [1, 1]
    assert stability["decision_shape_stable"] is False
    assert report["stability_drift_counts"] == {
        "completion": 0,
        "known_count": 1,
        "known_evidence_coverage": 1,
        "missing_count": 0,
        "query_count": 0,
        "decision_shape": 1,
        "controller_failure": 0,
        "critical_evidence_omission": 0,
    }


def test_stability_drift_separates_controller_failure_from_completion_flip(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        return [{"id": 31, "source_id": "pydantic-ai", "slug": "s", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact"}]

    outputs = iter([
        {"ok": True, "done": False, "known": [], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": False, "error": "invalid m3 evidence JSON", "attempts": 2, "validation_errors": ["invalid m3 evidence JSON"]},
        {"ok": True, "done": False, "known": [], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
    ])

    async def fake_m3(**kwargs):
        return next(outputs)

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {"schema_version": 1, "id": 20, "tool_name": "query", "query": "q", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["s"], "retrieved_chunk_ids": [31], "retrieved_chunk_hashes": [], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}

    report = asyncio.run(replay_module.run_replay([row], repeat=3))

    assert report["capture_stability"][0]["completion_stable"] is False
    assert report["stability_drift_counts"]["completion"] == 0
    assert report["stability_drift_counts"]["known_evidence_coverage"] == 0
    assert report["stability_drift_counts"]["controller_failure"] == 1


def test_known_count_drift_can_preserve_evidence_coverage(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        return [
            {"id": 31, "source_id": "pydantic-ai", "slug": "a", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact a"},
            {"id": 32, "source_id": "pydantic-ai", "slug": "b", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact b"},
        ]

    outputs = iter([
        {"ok": True, "done": False, "known": ["combined [E1] [E2]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": ["a [E1]", "b [E2]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": ["a and b [E2] [E1]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
    ])

    async def fake_m3(**kwargs):
        return next(outputs)

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {"schema_version": 1, "id": 30, "tool_name": "query", "query": "q", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["a", "b"], "retrieved_chunk_ids": [31, 32], "retrieved_chunk_hashes": [], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}

    report = asyncio.run(replay_module.run_replay([row], repeat=3))
    stability = report["capture_stability"][0]

    assert stability["known_count_range"] == [1, 2]
    assert stability["known_evidence_label_sets"] == [["[E1]", "[E2]"]]
    assert stability["known_evidence_coverage_stable"] is True
    assert report["stability_drift_counts"]["known_count"] == 1
    assert report["stability_drift_counts"]["known_evidence_coverage"] == 0


def test_critical_evidence_qrels_measure_omission_without_changing_controller(monkeypatch, tmp_path) -> None:
    qrels_path = tmp_path / "critical.json"
    qrels_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "captures": [{"capture_id": 30, "critical_labels": ["[E1]", "[E2]"]}],
            }
        )
    )
    qrels = replay_module.load_critical_evidence_qrels(qrels_path)

    async def fake_read(row, *, chunk_limit):
        return [
            {"id": 31, "source_id": "pydantic-ai", "slug": "a", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact a"},
            {"id": 32, "source_id": "pydantic-ai", "slug": "b", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact b"},
        ]

    outputs = iter([
        {"ok": True, "done": False, "known": ["a [E1]", "b [E2]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": ["a [E1]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
        {"ok": True, "done": False, "known": ["a [E1]", "b [E2]"], "missing": ["x"], "conflicts": [], "queries": ["q"], "attempts": 1, "validation_errors": []},
    ])

    async def fake_m3(**kwargs):
        return next(outputs)

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {"schema_version": 1, "id": 30, "tool_name": "query", "query": "q", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["a", "b"], "retrieved_chunk_ids": [31, 32], "retrieved_chunk_hashes": [], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}

    report = asyncio.run(replay_module.run_replay([row], repeat=3, critical_evidence_qrels=qrels))
    stability = report["capture_stability"][0]
    assert stability["critical_evidence_labels"] == ["[E1]", "[E2]"]
    assert stability["critical_evidence_scored_runs"] == 3
    assert stability["critical_evidence_recall_range"] == [0.5, 1.0]
    assert stability["critical_evidence_omission_runs"] == 1
    assert report["stability_drift_counts"]["critical_evidence_omission"] == 1


def test_critical_evidence_reports_zero_scored_runs_when_controller_never_succeeds(monkeypatch) -> None:
    async def fake_read(row, *, chunk_limit):
        return [{"id": 31, "source_id": "pydantic-ai", "slug": "a", "page_updated_at": "2026-08-16T15:00:00+00:00", "effective_date": None, "effective_date_source": None, "chunk_text": "fact a"}]

    async def fake_m3(**kwargs):
        return {"ok": False, "model": "m3", "provider": "minimax", "error": "provider unavailable"}

    monkeypatch.setattr(replay_module, "read_captured_chunks", fake_read)
    monkeypatch.setattr(replay_module, "invoke_m3_evidence", fake_m3)
    row = {"schema_version": 1, "id": 30, "tool_name": "query", "query": "q", "source_ids": ["pydantic-ai"], "retrieved_slugs": ["a"], "retrieved_chunk_ids": [31], "retrieved_chunk_hashes": [], "created_at": "2026-08-16T16:10:29.252Z", "as_of_ts": None}

    report = asyncio.run(
        replay_module.run_replay([row], repeat=3, critical_evidence_qrels={30: frozenset({"[E1]"})})
    )
    stability = report["capture_stability"][0]

    assert stability["critical_evidence_scored_runs"] == 0
    assert stability["critical_evidence_recall_range"] is None
    assert stability["critical_evidence_omission_runs"] == 0
    assert stability["successful_samples"] == 0
