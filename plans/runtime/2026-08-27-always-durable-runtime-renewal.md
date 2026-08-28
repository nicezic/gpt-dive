# Always-Durable Runtime Renewal

> 브랜치: `renewal/260827-always-durable-runtime` (base `274b68c`).
> 결정 권위: `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`.
> 설계 과정: `docs/runtime/adr/0_design-session-260827.md`.
> 이 파일은 구현 순서와 수용 체크리스트만 기록한다.

## 배경

ChatGPT Web은 GPT Dive 워크플로가 필요로 하는 MCP Tasks contract를 negotiate하지 않는다. 그 공백을 메우려고 쌓인 구조가 한계에 도달했다.

```text
(1) 구식 sync/async + code_mode background 도입
(2) "리턴 시 항상 TrackedTasks 를 붙인다" 아이디어 추가
    → 단계별 runtime 이해 부족으로 버그 다발
(3) 개선 아이디어 탐색
(4) 유저 결정: "이럴 거면 새로 만들자"
```

핵심 결함은 tunnel 버그가 아니라 **실행 수명이 전달 방식에 묶인 것**이었다. inline 경로는 async가 되기 전까지 durable하지 않았고, 상태는 두 identity(`task_id`/`execution_id`)와 두 authority(filesystem/SQLite)로 흩어져 있었다. 그 위에서 `ExecutionManager.start()`는 durable 레코드를 쓰기 **전에** 프로세스를 spawn했다.

리뉴얼은 전제를 바꾼다. durability는 acceptance에서 시작하고, inline 반환이냐 Task awareness냐는 전달 결정일 뿐이다.

## 설계 세션

2026-08-27, USER / opus5 / gpt-sol 3자 리뷰. 용어부터 검증하고 API·구현은 용어 확정 후로 미루는 순서로 Q1–Q18을 종결했다. 결정 D1–D13과 폐기된 대안의 경위는 `0_design-session-260827.md`에 있다.

세션에서 코드 변경은 0건이었다. 구현은 이 계획으로 분리했다.

## 구현 순서

ADR의 delivery order를 따른다. 순서에 의미가 있다 — D9(deadline 소유권)는 D10(`run_command` budget)의 선행 조건이고, D8(launch journal + CAS)이 나머지 전부의 토대다.

```text
1. glossary + ADR                 docs/runtime/CONTEXT.md, adr/0004
2. SQLite journal + claim CAS     execution_store.py
3. always-durable launch          execution_worker.py, app.py
   inline wait / deadline / publication
4. run_command + child budget     command_runtime.py, execution_context.py
5. 엄격한 MCP·task contract       app.py, code_capabilities.py
   + bounded TrackedTasks
6. stale 문서 정리와 검증          docs/**, CONTINUATION.md
```

## 변경 범위

신규:

```text
src/gpt_dive/execution_store.py       control-plane SSOT, 상태 전이, claim CAS
src/gpt_dive/execution_worker.py      worker 진입점, accepted→running CAS
src/gpt_dive/command_runtime.py       run_command (bounded spool, TERM→KILL→reap)
src/gpt_dive/execution_context.py     잔여 budget, min(정책, 잔여) 계산
tests/test_execution_store.py
tests/test_always_durable_code_mode.py
```

삭제:

```text
src/gpt_dive/task_store.py               두 번째 authority 제거
tests/test_task_store.py
tests/test_task_object_detachment.py     detach 개념 자체가 소멸
docs/runtime/adr/0001,0002,0003          전부 proposed 였으므로 supersede 아닌 삭제
```

대규모 수정:

```text
src/gpt_dive/app.py                   tool 3개 surface, discriminated output
src/gpt_dive/execution_manager.py     launch 순서, artifact 전용화
src/gpt_dive/task_runtime.py          task_id 제거, projection 축소
src/gpt_dive/code_capabilities.py     18 → 16, BACKGROUND·timeout 인자 삭제
src/gpt_dive/conduit/runtime.py       execution_id 단일 handle 반영
tests/test_code_runtime.py            구 계약 assertion 대거 제거
```

정확한 변경 파일과 line 통계는 `git diff --stat main...HEAD`를 권위로 삼는다. 이 문서는 변경 목적과 수용 근거만 유지한다.

## 수용 체크리스트

구현이 ADR을 실제로 지키는지 확인할 항목. 2026-08-28 로컬 검증 완료. Live acceptance는 아래 남은 작업으로 분리한다.

- [x] `accepted` commit이 worker spawn보다 **먼저** 일어난다 — `ExecutionManager.start()`의 `store.create()` → `_spawn_worker()` 순서
- [x] worker가 `accepted → running` CAS에 성공한 뒤에만 사용자 코드를 실행한다 — `execution_worker.run_execution()`의 `store.claim()` 경계
- [x] CAS 실패 시 사용자 코드 없이 종료한다 — `test_rejected_worker_claim_cannot_run_user_code`
- [x] stale `accepted` → `failed(reason=launch_interrupted)`, 자동 재실행 없음 — `test_stale_unclaimed_systemd_execution_fails_even_while_unit_is_active`
- [x] backing truth 소실 → `lost`, 추측·복원 없음 — `ExecutionManager._refresh()` / `ExecutionStore.mark_lost()`
- [x] `task_id`가 코드·스키마·응답 어디에도 없다 — `rg -n task_id src/gpt_dive` 결과 없음
- [x] filesystem이 lifecycle 판단 근거로 쓰이지 않는다 (artifact 전용) — SQLite가 SSOT, `meta.json`은 읽기 전용
- [x] MCP tool이 정확히 `bootstrap` / `code_mode` / `task` 3개 — `app.py`의 세 `@mcp.tool` 등록
- [x] `code_mode` 출력이 `kind` discriminated union이고 envelope가 unknown property를 거부한다 — `CodeModeOutcome` / `_ClosedModel`
- [x] `label`이 required이며 Execution 메타데이터로 저장된다 — `_mcp_code_mode()` / `ExecutionStore.create()`
- [x] inline 완료 시 Task가 생성되지 않는다 — `test_inline_completion_keeps_execution_unpublished`
- [x] inline wait 만료 시 Execution이 **계속 실행**되고 Task가 publish된다 — `test_inline_wait_expiry_publishes_same_continuing_execution`
- [x] stalled launch도 100초 inline cutoff에 accepted Execution을 Task로 공개하고, 110초 response deadline 뒤에도 구조화된 결과와 후속 publication을 보장한다 — inline cutoff / post-acceptance response-timeout 회귀 테스트
- [x] transport 절단과 ambient Worker signal이 명시적 취소로 기록되지 않는다 — transport·signal 회귀 테스트
- [x] 모델이 지정하는 timeout 인자가 어떤 capability에도 없다 — `code_capabilities.py` 전수 조사, timeout 인자 0건
- [x] child budget이 `min(capability 정책, 잔여 work budget)`으로 계산된다 — `ExecutionContext.child_budget()`
- [x] `deadline_remaining()`이 읽기 전용이다 — `build_code_registry()`가 `ExecutionContext.remaining_seconds()`만 노출
- [x] capability 15개, `BACKGROUND` 없음, `task_*` 4개는 top-level로 이관됨 — registry/schema 테스트
- [x] `run_command`가 실행 중 출력을 bounded spool한다 (전량 메모리 적재 없음) — `_drain_stream()`의 64KiB 청크와 stream별 byte 상한
- [x] `run_command`가 `.strip()`을 적용하지 않는다 — whitespace 보존 회귀 테스트
- [x] `run_command`가 process group을 TERM → KILL → reap으로 종료한다 — cancellation/deadline 회귀 테스트
- [x] TrackedTasks가 결정적 limit/order와 byte 상한을 지키고 변화 시에만 emit된다 — middleware/projection 회귀 테스트
- [x] `completed` Task가 명시적 dismiss 전까지 남는다 — task lifecycle 회귀 테스트
- [x] 43,200s (12시간: work 43,190s + cleanup 10s) 경계가 부분 출력 보존·무재시도·단일 bounded cleanup을 지킨다 — work cutoff 및 cleanup reserve 회귀 테스트
- [x] execution_id를 6자리 URL-safe Base64로 경량화 — `secrets.token_urlsafe(4)` 및 CLI 플래그 안전성 보장

전체 스위트: **143 passed in ~8.5s** (2026-08-29, 미사용 replay 및 m3_evidence 테스트 정리 완료). Ruff, Pyright, `git diff --check main`도 통과했다. CAS는 `ExecutionStore.claim()`의 조건부 `UPDATE ... WHERE state='accepted' AND cancel_requested=0`이 소유한다.

## 범위 밖

D11에 따라 이번에 손대지 않는다. 근거와 상세는 설계 세션 기록에 있다.

- agent/model capability 4종의 내부 transport 통합
- `_usage_summary` 바이트 동일 중복 (`model_call.py` / `subagent_worker.py`)
- `creds run ai` 커맨드 벡터와 `PROJECT_ROOT`/`CREDS`/`UV` 상수 이중화
- **`agy_worker`의 workspace 검증이 `is_dir()` 뿐** — `subagent_call`·`peer_review`와 달리 secret-path 정책이 없다. 별도 보안 작업으로 분리
- Council 확장 (`council_emit` 유지만)

## 남은 작업

- [x] 구현이 수용 체크리스트와 repository gate를 만족하는지 검증
- [ ] 서비스 재시작 후 **새 ChatGPT Web 세션**에서 스키마 수용 확인 (스키마 변경은 기존 세션에 반영되지 않는다)
- [ ] live acceptance 증거 기록
