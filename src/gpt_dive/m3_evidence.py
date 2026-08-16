from __future__ import annotations

import json
from typing import Any

from .bare import invoke_bare

_REQUIRED_LIST_FIELDS = ("known", "missing", "conflicts", "queries")


def _prompt(*, question: str, evidence: str, round_number: int, max_queries: int) -> str:
    return f"""You are an evidence controller for a local code/research workflow.
Do not call tools. You only analyze the evidence packet below.

Goal:
- Answer whether the evidence is sufficient for the question.
- Separate confirmed facts, missing evidence, and conflicts.
- If more evidence is needed, propose at most maximum {max_queries} concise independent retrieval queries.
- Do not invent facts that are not supported by the packet.
- Prefer queries that can be run in parallel. Only encode a dependency when a later query truly requires an earlier result.
- Stop when the evidence is sufficient; do not generate queries merely to appear thorough.

Return ONLY one JSON object with exactly these keys:
{{"known":["..."],"missing":["..."],"conflicts":["..."],"queries":["..."],"done":true}}

round: {round_number}
question:
{question}

evidence packet:
{evidence}
"""


def _validate_payload(value: Any, *, max_queries: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("top-level JSON must be an object")
    expected = {*_REQUIRED_LIST_FIELDS, "done"}
    if set(value) != expected:
        raise ValueError(f"JSON keys must be exactly {sorted(expected)}")
    for field in _REQUIRED_LIST_FIELDS:
        items = value[field]
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError(f"{field} must be a list of strings")
    if not isinstance(value["done"], bool):
        raise TypeError("done must be a boolean")
    if len(value["queries"]) > max_queries:
        raise ValueError(
            f"queries returned {len(value['queries'])} items, exceeding max_queries={max_queries}"
        )
    return value


async def invoke_m3_evidence(
    *,
    question: str,
    evidence: str,
    round_number: int = 1,
    max_queries: int = 3,
    timeout: float = 120.0,
    output_tokens_limit: int = 2048,
) -> dict[str, Any]:
    """Analyze a bounded evidence packet with tool-less MiniMax-M3."""
    if not question.strip():
        raise ValueError("question must not be empty")
    if not evidence.strip():
        raise ValueError("evidence must not be empty")
    if round_number <= 0:
        raise ValueError("round_number must be greater than 0")
    if not 0 <= max_queries <= 8:
        raise ValueError("max_queries must be between 0 and 8")

    bare = await invoke_bare(
        model="m3",
        prompt=_prompt(
            question=question,
            evidence=evidence,
            round_number=round_number,
            max_queries=max_queries,
        ),
        timeout=timeout,
        output_tokens_limit=output_tokens_limit,
    )
    if not bare.get("ok"):
        return bare

    raw = str(bare.get("output", ""))
    try:
        parsed = json.loads(raw)
        validated = _validate_payload(parsed, max_queries=max_queries)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "model": bare.get("model", "m3"),
            "provider": bare.get("provider", "minimax"),
            "error": "invalid m3 evidence JSON" if isinstance(exc, json.JSONDecodeError) else str(exc),
            "raw_output": raw,
        }

    return {
        "ok": True,
        "model": bare.get("model", "m3"),
        "provider": bare.get("provider", "minimax"),
        **validated,
        "usage": bare.get("usage", {}),
    }
