"""Replay captured real GBrain queries through the bounded M3 evidence controller."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .m3_evidence import invoke_m3_evidence
from .runtime_env import build_runtime_path

_PYDANTIC_SOURCES = {"pydantic-ai", "pydantic-ai-harness"}
_CURRENT_QUERY_RE = re.compile(r"\b(current|currently|latest|now|today)\b|현재|최신|지금|오늘", re.IGNORECASE)
_EVIDENCE_LABEL_RE = re.compile(r"\[E[1-9][0-9]*\]")
_DYNAMIC_VALIDATION_ERROR_PATTERNS = (
    (re.compile(r"^(known|conflicts) item must cite an evidence label:.*$"), r"\1 item must cite an evidence label"),
    (re.compile(r"^(known|conflicts) item cites unknown evidence label\(s\):.*$"), r"\1 item cites unknown evidence label(s)"),
    (re.compile(r"^queries returned \d+ items, exceeding max_queries=\d+$"), "queries exceed max_queries"),
)


def validation_error_invariant(error: str) -> str:
    """Collapse dynamic validation payloads into stable batch-level invariant keys."""
    for pattern, replacement in _DYNAMIC_VALIDATION_ERROR_PATTERNS:
        if pattern.search(error):
            return pattern.sub(replacement, error)
    return error


def _validated_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"capture has no valid {field}")
    timestamp = value.strip()
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ValueError(f"capture has invalid {field}: {timestamp!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"capture {field} must include a timezone")
    return timestamp


def replay_boundary(row: dict[str, Any]) -> tuple[str, datetime, str]:
    """Return the explicit as-of boundary, otherwise the query capture time."""
    as_of = row.get("as_of_ts")
    if as_of is not None:
        boundary = _validated_timestamp(as_of, field="as_of_ts")
        label = "captured as-of time"
    else:
        boundary = _validated_timestamp(row.get("created_at"), field="created_at")
        label = "captured query time"
    return boundary, datetime.fromisoformat(boundary), label


def replay_question(row: dict[str, Any]) -> str:
    """Anchor relative-time language to the captured historical query boundary."""
    query = str(row["query"]).strip()
    boundary, _, label = replay_boundary(row)
    return (
        f"{query}\n\n"
        f"Historical replay boundary: interpret current/latest/now relative to {boundary} ({label})."
    )


def reject_post_capture_page_updates(row: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
    """Fail closed when a captured chunk's page was rewritten after query capture.

    GBrain upserts chunks by ``(page_id, chunk_index)`` and can update
    ``chunk_text`` in place, preserving the chunk id. An id-only replay would
    then silently read newer text than the model originally received.
    """
    capture_time = datetime.fromisoformat(_validated_timestamp(row.get("created_at"), field="created_at"))
    changed_ids: list[int] = []
    for chunk in chunks:
        updated_raw = chunk.get("page_updated_at")
        if not isinstance(updated_raw, str) or not updated_raw.strip():
            raise RuntimeError(f"captured GBrain chunk {chunk.get('id', '?')} has no page update watermark")
        try:
            updated_at = datetime.fromisoformat(updated_raw.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"captured GBrain chunk {chunk.get('id', '?')} has invalid page update watermark"
            ) from exc
        if updated_at.tzinfo is None:
            raise RuntimeError(f"captured GBrain chunk {chunk.get('id', '?')} page update watermark has no timezone")
        if updated_at > capture_time:
            chunk_id = chunk.get("id")
            if isinstance(chunk_id, int):
                changed_ids.append(chunk_id)
    if changed_ids:
        raise RuntimeError(
            f"captured GBrain chunk pages were updated after capture; historical text is no longer provable: {changed_ids}"
        )


def verify_captured_chunk_hashes(
    row: dict[str, Any], chunks: list[dict[str, Any]], *, chunk_limit: int | None
) -> bool:
    """Verify exact captured evidence text when SHA-256 provenance is available."""
    captured = row.get("retrieved_chunk_hashes")
    if captured is None or captured == []:
        return False
    if not isinstance(captured, list):
        raise TypeError("captured chunk hash provenance is invalid")
    chunk_ids = row.get("retrieved_chunk_ids")
    if not isinstance(chunk_ids, list) or len(captured) != len(chunk_ids):
        raise RuntimeError("captured chunk hash provenance is not aligned with retrieved_chunk_ids")
    expected = captured if chunk_limit is None else captured[:chunk_limit]
    if len(expected) != len(chunks):
        raise RuntimeError("captured chunk hash provenance does not cover materialized chunks")
    changed_ids: list[int] = []
    for expected_hash, chunk in zip(expected, chunks, strict=True):
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise RuntimeError("captured chunk hash provenance contains an invalid SHA-256 value")
        text = chunk.get("chunk_text")
        if not isinstance(text, str):
            raise TypeError(f"captured GBrain chunk {chunk.get('id', '?')} has no text for hash verification")
        current_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if current_hash != expected_hash:
            chunk_id = chunk.get("id")
            if isinstance(chunk_id, int):
                changed_ids.append(chunk_id)
    if changed_ids:
        raise RuntimeError(f"captured GBrain chunk text hash drift: {changed_ids}")
    return True


def filter_future_temporal_evidence(
    row: dict[str, Any], chunks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Exclude post-boundary content dates only for current/latest-style historical questions."""
    if not _CURRENT_QUERY_RE.search(str(row.get("query", ""))):
        return chunks, 0
    _, boundary, _ = replay_boundary(row)
    kept: list[dict[str, Any]] = []
    excluded = 0
    for chunk in chunks:
        date = chunk.get("effective_date")
        source = chunk.get("effective_date_source")
        if isinstance(date, str) and date and source != "fallback":
            try:
                effective = datetime.fromisoformat(date)
            except ValueError:
                effective = None
            if effective is not None and effective.date() > boundary.date():
                excluded += 1
                continue
        kept.append(chunk)
    if not kept:
        raise RuntimeError("all captured evidence is dated after the historical replay boundary")
    return kept, excluded


def load_capture_rows(path: Path) -> list[dict[str, Any]]:
    """Load query rows from `gbrain eval export` NDJSON."""
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError(f"line {line_number} is not a gbrain eval export row")
        if value.get("tool_name") != "query":
            continue
        query = value.get("query")
        source_ids = value.get("source_ids")
        slugs = value.get("retrieved_slugs")
        chunk_ids = value.get("retrieved_chunk_ids")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"line {line_number} has no query text")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
            raise ValueError(f"line {line_number} has invalid source_ids")
        if not source_ids or not set(source_ids) <= _PYDANTIC_SOURCES:
            raise ValueError(f"line {line_number} is outside the supported Pydantic sources")
        if not isinstance(slugs, list) or not all(isinstance(item, str) for item in slugs):
            raise ValueError(f"line {line_number} has invalid retrieved_slugs")
        if not isinstance(chunk_ids, list) or not all(isinstance(item, int) and item > 0 for item in chunk_ids):
            raise ValueError(
                f"line {line_number} has no valid retrieved_chunk_ids; "
                "re-export a current GBrain capture for exact evidence replay"
            )
        chunk_hashes = value.get("retrieved_chunk_hashes")
        if chunk_hashes not in (None, []) and (
            not isinstance(chunk_hashes, list)
            or len(chunk_hashes) != len(chunk_ids)
            or not all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) for item in chunk_hashes)
        ):
            raise ValueError(f"line {line_number} has invalid retrieved_chunk_hashes")
        try:
            _validated_timestamp(value.get("created_at"), field="created_at")
            if value.get("as_of_ts") is not None:
                _validated_timestamp(value.get("as_of_ts"), field="as_of_ts")
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
        if not slugs or not chunk_ids:
            continue
        rows.append(value)
    if not rows:
        raise ValueError("capture contains no replayable Pydantic query rows")
    return rows


def build_evidence_packet(chunks: list[dict[str, Any]]) -> str:
    """Convert captured GBrain chunks into an unambiguous labeled M3 packet."""
    items: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_text = str(chunk.get("chunk_text", "")).strip()
        if not chunk_text:
            continue
        header_parts = [
            f"[E{index}]",
            f"chunk_id={chunk.get('id', '?')}",
            f"source={chunk.get('source_id', '?')}",
            f"slug={chunk.get('slug', '?')}",
        ]
        title = chunk.get("title")
        if isinstance(title, str) and title.strip():
            header_parts.append(f"title={json.dumps(title.strip(), ensure_ascii=False)}")
        effective_date = chunk.get("effective_date")
        effective_date_source = chunk.get("effective_date_source")
        if (
            isinstance(effective_date, str)
            and effective_date
            and effective_date_source != "fallback"
        ):
            header_parts.append(f"effective_date={effective_date}")
        if isinstance(effective_date_source, str) and effective_date_source:
            header_parts.append(f"effective_date_source={effective_date_source}")
        items.append(f"{' '.join(header_parts)}\n{chunk_text}")
    if not items:
        raise ValueError("captured chunks contain no textual evidence")
    return "\n\n".join(items)


_CHUNK_READER = r"""
import { loadConfig, toEngineConfig } from './src/core/config.ts';
import { createEngine } from './src/core/engine-factory.ts';
const ids = JSON.parse(process.env.GPT_DIVE_GBRAIN_CHUNK_IDS ?? '[]');
if (!Array.isArray(ids) || ids.length === 0 || !ids.every(Number.isInteger)) throw new Error('invalid chunk ids');
const config = loadConfig();
if (!config) throw new Error('no GBrain config');
const engineConfig = toEngineConfig(config);
const engine = await createEngine(engineConfig);
await engine.connect(engineConfig);
try {
  const placeholders = ids.map((_, i) => `$${i + 1}`).join(', ');
  const rows = await engine.executeRaw(
    `SELECT c.id, p.source_id, p.slug, p.title, p.updated_at::text AS page_updated_at, p.effective_date::date::text AS effective_date, p.effective_date_source, c.chunk_text FROM content_chunks c JOIN pages p ON p.id = c.page_id WHERE c.id IN (${placeholders})`,
    ids,
  );
  console.log(JSON.stringify(rows));
} finally {
  await engine.disconnect();
}
"""


_SCHEMA_PACK_READER = r"""
import { loadConfig, toEngineConfig } from './src/core/config.ts';
import { createEngine } from './src/core/engine-factory.ts';
import { buildSchemaPackPerSourceSnapshot } from './src/core/eval-capture.ts';
const sourceIds = JSON.parse(process.env.GPT_DIVE_GBRAIN_SOURCE_IDS ?? '[]');
const remote = process.env.GPT_DIVE_GBRAIN_REMOTE === '1';
if (!Array.isArray(sourceIds) || sourceIds.length === 0 || !sourceIds.every(x => typeof x === 'string')) throw new Error('invalid source ids');
const config = loadConfig();
if (!config) throw new Error('no GBrain config');
const engineConfig = toEngineConfig(config);
const engine = await createEngine(engineConfig);
await engine.connect(engineConfig);
try {
  const snapshot = await buildSchemaPackPerSourceSnapshot(engine, sourceIds, remote, config);
  console.log(JSON.stringify(snapshot));
} finally {
  await engine.disconnect();
}
"""


async def read_current_schema_pack_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Resolve the current per-source schema-pack snapshot using GBrain's canonical resolver."""
    source_ids = row.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids or not all(isinstance(item, str) for item in source_ids):
        raise RuntimeError("capture has invalid source_ids for schema-pack verification")
    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))
    env["GPT_DIVE_GBRAIN_SOURCE_IDS"] = json.dumps(source_ids)
    env["GPT_DIVE_GBRAIN_REMOTE"] = "1" if row.get("remote") is True else "0"
    gbrain_repo = Path(env.get("GPT_DIVE_GBRAIN_REPO", Path.home() / "gbrain"))
    proc = await asyncio.create_subprocess_exec(
        "bun",
        "-",
        cwd=gbrain_repo,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate(_SCHEMA_PACK_READER.encode())
    if proc.returncode != 0:
        raise RuntimeError(
            f"failed to resolve current GBrain schema-pack provenance: {stderr.decode(errors='replace').strip()}"
        )
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise TypeError("current GBrain schema-pack snapshot is unavailable")
    return value


def _schema_pack_semantics(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return only schema-pack semantics, excluding informational source revision lineage."""
    normalized: dict[str, Any] = {}
    for source_id, value in snapshot.items():
        if isinstance(value, dict):
            normalized[source_id] = {key: item for key, item in value.items() if key != "source_commit"}
        else:
            normalized[source_id] = value
    return normalized


def captured_source_commits(row: dict[str, Any]) -> dict[str, str | None]:
    """Expose source revisions recorded with a capture without turning them into a replay gate."""
    captured = row.get("schema_pack_per_source")
    if not isinstance(captured, dict):
        return {}
    commits: dict[str, str | None] = {}
    for source_id, value in captured.items():
        if not isinstance(source_id, str) or not isinstance(value, dict) or "source_commit" not in value:
            continue
        commit = value.get("source_commit")
        if commit is not None and not isinstance(commit, str):
            raise TypeError("captured source commit provenance is invalid")
        commits[source_id] = commit
    return dict(sorted(commits.items()))


async def verify_schema_pack_provenance(row: dict[str, Any]) -> bool:
    """Fail closed on pack-semantic drift; source revision lineage is informational."""
    captured = row.get("schema_pack_per_source")
    if captured is None:
        return False
    if not isinstance(captured, dict):
        raise TypeError("captured schema-pack provenance is invalid")
    current = await read_current_schema_pack_snapshot(row)
    if _schema_pack_semantics(current) != _schema_pack_semantics(captured):
        raise RuntimeError("schema-pack provenance drift: current active pack differs from the captured replay snapshot")
    return True


async def read_captured_chunks(row: dict[str, Any], *, chunk_limit: int | None) -> list[dict[str, Any]]:
    """Materialize captured chunk IDs exactly, without issuing a new retrieval query."""
    if chunk_limit is not None and chunk_limit <= 0:
        raise ValueError("chunk_limit must be greater than 0")
    chunk_ids = list(row["retrieved_chunk_ids"])
    if chunk_limit is not None:
        chunk_ids = chunk_ids[:chunk_limit]
    source_ids = set(row["source_ids"])
    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))
    env["GPT_DIVE_GBRAIN_CHUNK_IDS"] = json.dumps(chunk_ids)
    gbrain_repo = Path(env.get("GPT_DIVE_GBRAIN_REPO", Path.home() / "gbrain"))
    proc = await asyncio.create_subprocess_exec(
        "bun",
        "-",
        cwd=gbrain_repo,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate(_CHUNK_READER.encode())
    if proc.returncode != 0:
        raise RuntimeError(f"failed to materialize captured GBrain chunks: {stderr.decode(errors='replace').strip()}")
    value = json.loads(stdout)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError("GBrain chunk reader returned invalid JSON")
    by_id = {int(item["id"]): item for item in value if isinstance(item.get("id"), int)}
    missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in by_id]
    if missing:
        raise RuntimeError(f"captured GBrain chunk IDs no longer exist: {missing}")
    chunks = [by_id[chunk_id] for chunk_id in chunk_ids]
    wrong_sources = [item for item in chunks if item.get("source_id") not in source_ids]
    if wrong_sources:
        raise RuntimeError("captured GBrain chunk resolved outside the captured source scope")
    return chunks


async def run_replay(
    rows: list[dict[str, Any]],
    *,
    chunk_limit: int | None = None,
    max_queries: int = 3,
    repeat: int = 1,
) -> dict[str, Any]:
    """Run captured Pydantic queries through their exact captured chunks and M3 analysis."""
    if repeat <= 0:
        raise ValueError("repeat must be greater than 0")

    results: list[dict[str, Any]] = []
    for run in range(1, repeat + 1):
        for row in rows:
            schema_pack_checked = await verify_schema_pack_provenance(row)
            captured_chunks = await read_captured_chunks(row, chunk_limit=chunk_limit)
            chunk_hashes_checked = verify_captured_chunk_hashes(row, captured_chunks, chunk_limit=chunk_limit)
            if not chunk_hashes_checked:
                reject_post_capture_page_updates(row, captured_chunks)
            chunks, excluded_future_chunks = filter_future_temporal_evidence(row, captured_chunks)
            controller = await invoke_m3_evidence(
                question=replay_question(row),
                evidence=build_evidence_packet(chunks),
                max_queries=max_queries,
            )
            results.append(
                {
                    "run": run,
                    "capture_id": row.get("id"),
                    "query": row["query"],
                    "source_ids": row["source_ids"],
                    "chunk_count": len(chunks),
                    "excluded_future_chunks": excluded_future_chunks,
                    "schema_pack_checked": schema_pack_checked,
                    "source_commits": captured_source_commits(row),
                    "chunk_hashes_checked": chunk_hashes_checked,
                    "controller": controller,
                }
            )

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        ok_items = [item for item in items if item["controller"].get("ok")]
        error_counts: dict[str, int] = {}
        for item in items:
            errors = item["controller"].get("validation_errors", [])
            if isinstance(errors, list):
                for error in errors:
                    if isinstance(error, str) and error:
                        invariant = validation_error_invariant(error)
                        error_counts[invariant] = error_counts.get(invariant, 0) + 1
        return {
            "done_rows": sum(1 for item in ok_items if item["controller"].get("done") is True),
            "unresolved_rows": sum(1 for item in ok_items if item["controller"].get("done") is False),
            "retry_rows": sum(1 for item in ok_items if item["controller"].get("attempts", 1) > 1),
            "proposed_queries": sum(len(item["controller"].get("queries", [])) for item in ok_items),
            "controller_failures": len(items) - len(ok_items),
            "validation_error_counts": dict(sorted(error_counts.items())),
        }

    summary = summarize(results)
    run_stats = [
        {"run": run, **summarize([item for item in results if item["run"] == run])}
        for run in range(1, repeat + 1)
    ]
    capture_stability = []
    for row in rows:
        capture_id = row.get("id")
        samples = [item for item in results if item["capture_id"] == capture_id]
        ok_samples = [item for item in samples if item["controller"].get("ok")]
        done_values = [item["controller"].get("done") for item in ok_samples]
        known_counts = [len(item["controller"].get("known", [])) for item in ok_samples]
        missing_counts = [len(item["controller"].get("missing", [])) for item in ok_samples]
        query_counts = [len(item["controller"].get("queries", [])) for item in ok_samples]
        known_evidence_label_sets = sorted(
            {
                tuple(
                    sorted(
                        {
                            label
                            for known in item["controller"].get("known", [])
                            if isinstance(known, str)
                            for label in _EVIDENCE_LABEL_RE.findall(known)
                        }
                    )
                )
                for item in ok_samples
            }
        )
        count_ranges = {
            "known_count_range": [min(known_counts), max(known_counts)] if known_counts else [0, 0],
            "missing_count_range": [min(missing_counts), max(missing_counts)] if missing_counts else [0, 0],
            "query_count_range": [min(query_counts), max(query_counts)] if query_counts else [0, 0],
        }
        capture_stability.append(
            {
                "capture_id": capture_id,
                "samples": len(samples),
                "successful_samples": len(ok_samples),
                "done_true": sum(value is True for value in done_values),
                "done_false": sum(value is False for value in done_values),
                "completion_stable": len(set(done_values)) <= 1 and len(ok_samples) == len(samples),
                "known_evidence_label_sets": [list(labels) for labels in known_evidence_label_sets],
                "known_evidence_coverage_stable": (
                    len(known_evidence_label_sets) <= 1 and len(ok_samples) == len(samples)
                ),
                **count_ranges,
                "decision_shape_stable": (
                    len(ok_samples) == len(samples)
                    and all(low == high for low, high in count_ranges.values())
                ),
            }
        )
    stability_drift_counts = {
        "completion": sum(
            item["done_true"] > 0 and item["done_false"] > 0 for item in capture_stability
        ),
        "known_count": sum(item["known_count_range"][0] != item["known_count_range"][1] for item in capture_stability),
        "known_evidence_coverage": sum(
            len(item["known_evidence_label_sets"]) > 1 for item in capture_stability
        ),
        "missing_count": sum(item["missing_count_range"][0] != item["missing_count_range"][1] for item in capture_stability),
        "query_count": sum(item["query_count_range"][0] != item["query_count_range"][1] for item in capture_stability),
        "decision_shape": sum(not item["decision_shape_stable"] for item in capture_stability),
        "controller_failure": sum(
            item["successful_samples"] != item["samples"] for item in capture_stability
        ),
    }
    return {
        "rows": len(rows),
        "repeat": repeat,
        "samples": len(results),
        **summary,
        "run_stats": run_stats,
        "capture_stability": capture_stability,
        "stability_drift_counts": stability_drift_counts,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay exported real GBrain Pydantic queries through their exact captured chunks and MiniMax-M3."
    )
    parser.add_argument("--against", type=Path, required=True, help="NDJSON from `gbrain eval export`.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum captured query rows to replay.")
    parser.add_argument(
        "--chunk-limit",
        type=int,
        default=None,
        help="Optional maximum captured chunks supplied to M3 per query; default preserves all captured chunks.",
    )
    parser.add_argument("--max-queries", type=int, default=3, help="Maximum M3 follow-up queries per row.")
    parser.add_argument("--repeat", type=int, default=1, help="Replay the same capture set N times sequentially.")
    args = parser.parse_args()
    if args.limit <= 0:
        raise ValueError("limit must be greater than 0")
    rows = load_capture_rows(args.against)[: args.limit]
    report = asyncio.run(
        run_replay(rows, chunk_limit=args.chunk_limit, max_queries=args.max_queries, repeat=args.repeat)
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["controller_failures"] == 0 else 1)


if __name__ == "__main__":
    main()
