---
title: ADR - Code Mode Bootstrap and Model Guidance
created: 2026-08-30
type: decision
status: proposed
---

# ADR 0007 — Code Mode Bootstrap and Model Guidance

> ADR 0005에서 분리한 후속 decision placeholder. **아직 결정하지 않았다.**

모델이 Code Mode를 안정적으로 사용하려면 최소한 `Monty != arbitrary CPython`, `CAPABILITIES`, `PAYLOAD`, independent work의 `asyncio.gather()`, `print() = console/progress`, final expression = compact `output`을 알아야 한다.

이 ADR은 bootstrap/MCP description/wiki 중 어떤 surface가 어떤 지식을 책임질지 결정한다. Runtime output semantics 자체는 ADR 0005의 권위로 유지한다.

Source: `docs/runtime/adr/0005-code-mode-output-contract.md`