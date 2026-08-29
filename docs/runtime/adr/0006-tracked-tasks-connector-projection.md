---
title: ADR - TrackedTasks Connector Projection
created: 2026-08-30
type: decision
status: proposed
---

# ADR 0006 — TrackedTasks Connector Projection

> ADR 0005에서 분리한 후속 decision placeholder. **아직 결정하지 않았다.**

현재 서버 middleware는 primary MCP result에 TrackedTasks awareness를 additive하게 append하지만, ChatGPT connector에서 그 awareness가 보이지 않는 현상이 관찰됐다.

이 ADR은 connector/transport projection에서 awareness가 어디서 사라지는지, 어떤 surface로 노출해야 하는지 결정한다. **Code Mode final `output` contract를 이 문제의 보상책으로 변형하지 않는다.**

Source: `docs/runtime/adr/0005-code-mode-output-contract.md`