from __future__ import annotations

import asyncio

import gpt_dive.m3_evidence as evidence_module


def test_invoke_m3_evidence_uses_bare_m3_and_validates_contract(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_invoke_bare(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '{"known":["a [E1]"],"missing":["b"],"conflicts":[],"queries":["q1","q2"],"done":false}',
            "usage": {"requests": 1},
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(
        evidence_module.invoke_m3_evidence(
            question="How does X work?",
            evidence="[E1] source evidence",
            round_number=1,
            max_queries=2,
            timeout=17,
            output_tokens_limit=321,
        )
    )

    assert result["ok"] is True
    assert result["known"] == ["a [E1]"]
    assert result["missing"] == ["b"]
    assert result["queries"] == ["q1", "q2"]
    assert result["done"] is False
    assert result["usage"] == {"requests": 1}
    assert calls[0]["model"] == "m3"
    assert calls[0]["timeout"] == 17
    assert calls[0]["output_tokens_limit"] == 321
    prompt = str(calls[0]["prompt"])
    assert "How does X work?" in prompt
    assert "[E1] source evidence" in prompt
    assert "Do not call tools" in prompt
    assert "maximum 2" in prompt
    assert "exact question asked" in prompt
    assert "optional implementation details" in prompt
    assert "every explicitly requested aspect" in prompt


def test_invoke_m3_evidence_accepts_single_json_code_fence(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '```json\n{"known":[],"missing":[],"conflicts":[],"queries":[],"done":true}\n```',
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="e"))

    assert result["ok"] is True
    assert result["done"] is True
    assert result["queries"] == []


def test_invoke_m3_evidence_rejects_invalid_json(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {"ok": True, "model": "m3", "provider": "minimax", "output": "not-json"}

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="e"))

    assert result["ok"] is False
    assert result["error"] == "invalid m3 evidence JSON"
    assert result["raw_output"] == "not-json"


def test_invoke_m3_evidence_rejects_query_overflow(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '{"known":[],"missing":[],"conflicts":[],"queries":["a","b","c"],"done":false}',
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(
        evidence_module.invoke_m3_evidence(question="q", evidence="e", max_queries=2)
    )

    assert result["ok"] is False
    assert "max_queries=2" in result["error"]


def test_invoke_m3_evidence_rejects_queries_when_done(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '{"known":[],"missing":[],"conflicts":[],"queries":["extra search"],"done":true}',
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="e"))

    assert result["ok"] is False
    assert "empty when done is true" in result["error"]


def test_invoke_m3_evidence_rejects_empty_or_duplicate_queries(monkeypatch) -> None:
    empty_output = '{"known":[],"missing":[],"conflicts":[],"queries":["   "],"done":false}'
    duplicate_output = (
        '{"known":[],"missing":[],"conflicts":[],"queries":["Find X"," find x "],"done":false}'
    )
    outputs = iter([empty_output, empty_output, duplicate_output, duplicate_output])

    async def fake_invoke_bare(**kwargs):
        return {"ok": True, "model": "m3", "provider": "minimax", "output": next(outputs)}

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    empty = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="e"))
    duplicate = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="e"))

    assert empty["ok"] is False
    assert "empty strings" in empty["error"]
    assert duplicate["ok"] is False
    assert "must be distinct" in duplicate["error"]


def test_invoke_m3_evidence_requires_known_provenance_when_packet_is_labeled(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '{"known":["supported fact"],"missing":[],"conflicts":[],"queries":[],"done":true}',
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(
        evidence_module.invoke_m3_evidence(question="q", evidence="[E1] authoritative evidence")
    )

    assert result["ok"] is False
    assert "must cite an evidence label" in result["error"]


def test_invoke_m3_evidence_rejects_unknown_evidence_label(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '{"known":["supported fact [E2]"],"missing":[],"conflicts":[],"queries":[],"done":true}',
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(
        evidence_module.invoke_m3_evidence(question="q", evidence="[E1] authoritative evidence")
    )

    assert result["ok"] is False
    assert "unknown evidence label" in result["error"]


def test_invoke_m3_evidence_unlabeled_packet_remains_backward_compatible(monkeypatch) -> None:
    async def fake_invoke_bare(**kwargs):
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": '{"known":["supported fact"],"missing":[],"conflicts":[],"queries":[],"done":true}',
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="plain evidence"))

    assert result["ok"] is True
    assert result["known"] == ["supported fact"]


def test_invoke_m3_evidence_retries_one_invalid_structured_output(monkeypatch) -> None:
    outputs = iter(
        [
            {
                "ok": True,
                "model": "m3",
                "provider": "minimax",
                "output": "not-json",
                "usage": {"requests": 1, "output_tokens": 5},
            },
            {
                "ok": True,
                "model": "m3",
                "provider": "minimax",
                "output": '{"known":["fact"],"missing":[],"conflicts":[],"queries":[],"done":true}',
                "usage": {"requests": 1, "output_tokens": 7},
            },
        ]
    )

    async def fake_invoke_bare(**kwargs):
        return next(outputs)

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="plain evidence"))

    assert result["ok"] is True
    assert result["done"] is True
    assert result["attempts"] == 2
    assert result["usage"] == {"requests": 2, "output_tokens": 12}


def test_invoke_m3_evidence_stops_after_two_invalid_structured_outputs(monkeypatch) -> None:
    calls = 0

    async def fake_invoke_bare(**kwargs):
        nonlocal calls
        calls += 1
        return {
            "ok": True,
            "model": "m3",
            "provider": "minimax",
            "output": "still-not-json",
            "usage": {"requests": 1},
        }

    monkeypatch.setattr(evidence_module, "invoke_bare", fake_invoke_bare)
    result = asyncio.run(evidence_module.invoke_m3_evidence(question="q", evidence="e"))

    assert calls == 2
    assert result["ok"] is False
    assert result["attempts"] == 2
    assert result["usage"] == {"requests": 2}
    assert result["raw_output"] == "still-not-json"
