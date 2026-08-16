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
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"line {line_number} has no query text")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
            raise ValueError(f"line {line_number} has invalid source_ids")
        if not source_ids or not set(source_ids) <= _PYDANTIC_SOURCES:
            raise ValueError(f"line {line_number} is outside the supported Pydantic sources")
        if not isinstance(slugs, list) or not all(isinstance(item, str) for item in slugs):
            raise ValueError(f"line {line_number} has invalid retrieved_slugs")
        if not slugs:
            continue
        rows.append(value)
    if not rows:
        raise ValueError("capture contains no replayable Pydantic query rows")
    return rows


def build_evidence_packet(pages: list[dict[str, Any]]) -> str:
    """Convert captured GBrain pages into an unambiguous labeled M3 packet."""
    items: list[str] = []
    for index, page in enumerate(pages, start=1):
        page_text = str(page.get("page_text", "")).strip()
        if not page_text:
            continue
        header = f"[E{index}] source={page.get('source_id', '?')} slug={page.get('slug', '?')}"
        items.append(f"{header}\n{page_text}")
    if not items:
        raise ValueError("captured pages contain no textual evidence")
    return "\n\n".join(items)


async def _read_page(slug: str, source_ids: list[str]) -> dict[str, Any]:
    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))
    errors: list[str] = []
    for source_id in source_ids:
        proc = await asyncio.create_subprocess_exec(
            "gbrain",
            "get",
            slug,
            "--source",
            source_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return {"source_id": source_id, "slug": slug, "page_text": stdout.decode(errors="replace")}
        errors.append(stderr.decode(errors="replace").strip())
    raise RuntimeError(f"captured page not found in sources {source_ids}: {slug}; {' | '.join(errors)}")


async def read_captured_pages(row: dict[str, Any], *, page_limit: int) -> list[dict[str, Any]]:
    """Materialize the exact captured slug set without issuing new retrieval queries."""
    if page_limit <= 0:
        raise ValueError("page_limit must be greater than 0")
    slugs = list(row["retrieved_slugs"])[:page_limit]
    source_ids = list(row["source_ids"])
    return list(
        await asyncio.gather(*(_read_page(str(slug), source_ids) for slug in slugs))
    )


async def run_replay(
    rows: list[dict[str, Any]],
    *,
    page_limit: int = 4,
    max_queries: int = 3,
) -> dict[str, Any]:
    """Run captured Pydantic queries through their captured pages and M3 analysis."""
    results: list[dict[str, Any]] = []
    for row in rows:
        pages = await read_captured_pages(row, page_limit=page_limit)
        controller = await invoke_m3_evidence(
            question=str(row["query"]),
            evidence=build_evidence_packet(pages),
            max_queries=max_queries,
        )
        results.append(
            {
                "capture_id": row.get("id"),
                "query": row["query"],
                "source_ids": row["source_ids"],
                "page_count": len(pages),
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
        description="Replay exported real GBrain Pydantic queries through their captured pages and MiniMax-M3."
    )
    parser.add_argument("--against", type=Path, required=True, help="NDJSON from `gbrain eval export`.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum captured query rows to replay.")
    parser.add_argument("--page-limit", type=int, default=4, help="Maximum captured pages supplied to M3 per query.")
    parser.add_argument("--max-queries", type=int, default=3, help="Maximum M3 follow-up queries per row.")
    args = parser.parse_args()
    if args.limit <= 0:
        raise ValueError("limit must be greater than 0")
    rows = load_capture_rows(args.against)[: args.limit]
    report = asyncio.run(run_replay(rows, page_limit=args.page_limit, max_queries=args.max_queries))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["controller_failures"] == 0 else 1)


if __name__ == "__main__":
    main()
