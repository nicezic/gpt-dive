---
title: ADR 0008 — Bounded Command Evidence and Recovery
created: 2026-08-30
updated: 2026-10-20
type: decision
status: proposed
---

# ADR 0008 — Bounded Command Evidence and Recovery

## Proposed decision

`run_command`의 stdout/stderr는 각 호출 단위로 제한해 내부 spool과 SQLite 증거에 저장한다. AI에게 전달하는 결과는 짧게 유지하고, command를 재실행하지 않고도 이미 수집된 근거를 조사할 수 있어야 한다. **이 문서는 제안의 전체 구현 완료를 뜻하지 않는다.**

- `run_ordinal`과 `execution_id`로 각 command의 원본 증거를 구분한다.
- 내부 spool과 SQLite는 증거/복구 저장소다. 둘 중 하나에 쓰지 못했다는 이유로 이미 끝난 명령을 다시 실행하지 않는다.
- 모델의 기본 결과에 원본 stdout을 전부 펼치지 않는다. `exit_code`, 실행 시간, 캡처 크기, 필요한 stderr 일부와 Monty의 처리된 최종 값만 표시한다.
- 보존·GC는 기존 Runtime의 cleanup을 재사용하며 별도 재시도/두 번째 작업 스케줄러를 도입하지 않는다.
- raw evidence 조회는 호출 단위에 한정한다. 모든 Capability 원문과 Monty 전체 transcript를 저장하려 하지 않는다.

## Why

AI 출력용으로 잘린 로그를 완전한 로그라 가정해 재조사할 수 있고, 같은 명령을 다시 실행하면 부작용이 중복된다. 증거 저장과 MCP 출력 제한은 서로 다른 경계다([ADR 0005](0005-code-mode-output-contract.md)).

## Rejected

- 복구를 위해 기존 `run_command`를 자동 재실행.
- 모든 중간 Capability 값을 거대한 일반 transcript로 저장.
- 새로운 durable store나 Task 수명주기를 중복 구축.

## Status / authority

현재 `command_runtime.py`, `execution_store.py`, `app.py`에는 spool, SQLite command evidence와 compact 실행 요약 구현이 존재한다. 제안에 등장한 모든 복구 기능, retention 보장 및 별도 public `run_command_evidence` 도구가 구현됐다고 가정하지 않는다. 실제 제공 범위는 [operations](../operations.md), 현재 schema/코드·테스트를 따른다. 당시 상세 spool/GC 설계와 미구현 public 복구 아이디어는 이전 버전의 Git 이력으로 확인한다.
