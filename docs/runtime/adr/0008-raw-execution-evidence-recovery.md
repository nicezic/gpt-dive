---
title: ADR - Raw Execution Evidence Recovery
created: 2026-08-30
type: decision
status: proposed
---

# ADR 0008 — Raw Execution Evidence Recovery

> ADR 0005 Phase 2에서 분리한 후속 decision placeholder. **아직 결정하지 않았다.**

정상 경로는 compact `output`만 model context에 넣고, 결과가 이상할 때만 `execution_id`를 사용해 정확한 raw evidence를 다시 조회한다.

이 ADR은 retained artifact의 authority, 조회 surface, retention/TTL을 결정한다. 현재 `~/.local/state/gpt-dive/executions-v2/<execution_id>/`를 자연스러운 후보로 보며, 별도 SQLite blob 저장소를 기본 전제로 두지 않는다.

Source: `docs/runtime/adr/0005-code-mode-output-contract.md`