"""Replay captured real GBrain queries through the bounded M3 evidence controller."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .m3_evidence import invoke_m3_evidence
from .runtime_env import build_runtime_path

_PYDANTIC_SOURCES = {"pydantic-ai", "pydantic-ai-harness"}


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
    `SELECT c.id, p.source_id, p.slug, p.title, p.effective_date::date::text AS effective_date, p.effective_date_source, c.chunk_text FROM content_chunks c JOIN pages p ON p.id = c.page_id WHERE c.id IN (${placeholders})`,
    ids,
  );
  console.log(JSON.stringify(rows));
} finally {
  await engine.disconnect();
}
"""


async def read_captured_chunks(row: dict[str, Any], *, chunk_limit: int) -> list[dict[str, Any]]:
    """Materialize captured chunk IDs exactly, without issuing a new retrieval query."""
    if chunk_limit <= 0:
        raise ValueError("chunk_limit must be greater than 0")
    chunk_ids = list(row["retrieved_chunk_ids"])[:chunk_limit]
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
    chunk_limit: int = 4,
    max_queries: int = 3,
) -> dict[str, Any]:
    """Run captured Pydantic queries through their exact captured chunks and M3 analysis."""
    results: list[dict[str, Any]] = []
    for row in rows:
        chunks = await read_captured_chunks(row, chunk_limit=chunk_limit)
        controller = await invoke_m3_evidence(
            question=str(row["query"]),
            evidence=build_evidence_packet(chunks),
            max_queries=max_queries,
        )
        results.append(
            {
                "capture_id": row.get("id"),
                "query": row["query"],
                "source_ids": row["source_ids"],
                "chunk_count": len(chunks),
                "controller": controller,
            }
        )

    ok_results = [item for item in results if item["controller"].get("ok")]
    return {
        "rows": len(results),
        "done_rows": sum(1 for item in ok_results if item["controller"].get("done") is True),
        "unresolved_rows": sum(1 for item in ok_results if item["controller"].get("done") is False),
        "retry_rows": sum(1 for item in ok_results if item["controller"].get("attempts", 1) > 1),
        "proposed_queries": sum(len(item["controller"].get("queries", [])) for item in ok_results),
        "controller_failures": len(results) - len(ok_results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay exported real GBrain Pydantic queries through their exact captured chunks and MiniMax-M3."
    )
    parser.add_argument("--against", type=Path, required=True, help="NDJSON from `gbrain eval export`.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum captured query rows to replay.")
    parser.add_argument("--chunk-limit", type=int, default=4, help="Maximum captured chunks supplied to M3 per query.")
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
