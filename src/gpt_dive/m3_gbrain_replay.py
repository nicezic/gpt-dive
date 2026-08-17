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


async def verify_schema_pack_provenance(row: dict[str, Any]) -> bool:
    """Fail closed on pack drift for new captures; legacy captures without provenance remain replayable."""
    captured = row.get("schema_pack_per_source")
    if captured is None:
        return False
    if not isinstance(captured, dict):
        raise TypeError("captured schema-pack provenance is invalid")
    current = await read_current_schema_pack_snapshot(row)
    if current != captured:
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
) -> dict[str, Any]:
    """Run captured Pydantic queries through their exact captured chunks and M3 analysis."""
    results: list[dict[str, Any]] = []
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
                "capture_id": row.get("id"),
                "query": row["query"],
                "source_ids": row["source_ids"],
                "chunk_count": len(chunks),
                "excluded_future_chunks": excluded_future_chunks,
                "schema_pack_checked": schema_pack_checked,
                "chunk_hashes_checked": chunk_hashes_checked,
                "controller": controller,
            }
        )

    ok_results = [item for item in results if item["controller"].get("ok")]
    validation_error_counts: dict[str, int] = {}
    for item in results:
        errors = item["controller"].get("validation_errors", [])
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, str) and error:
                    validation_error_counts[error] = validation_error_counts.get(error, 0) + 1
    return {
        "rows": len(results),
        "done_rows": sum(1 for item in ok_results if item["controller"].get("done") is True),
        "unresolved_rows": sum(1 for item in ok_results if item["controller"].get("done") is False),
        "retry_rows": sum(1 for item in ok_results if item["controller"].get("attempts", 1) > 1),
        "proposed_queries": sum(len(item["controller"].get("queries", [])) for item in ok_results),
        "controller_failures": len(results) - len(ok_results),
        "validation_error_counts": dict(sorted(validation_error_counts.items())),
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
    args = parser.parse_args()
    if args.limit <= 0:
        raise ValueError("limit must be greater than 0")
    rows = load_capture_rows(args.against)[: args.limit]
    report = asyncio.run(run_replay(rows, chunk_limit=args.chunk_limit, max_queries=args.max_queries))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["controller_failures"] == 0 else 1)


if __name__ == "__main__":
    main()
