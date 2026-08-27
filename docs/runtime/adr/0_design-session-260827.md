---
title: Runtime Renewal Design Session
created: 2026-08-28
updated: 2026-08-28
type: record
status: archived
---

# Runtime 0 — 리뉴얼 설계 세션 기록 (2026-08-27)

> ADR 0004가 **무엇을 결정했는지**를 소유한다면, 이 문서는 **어떻게 그 결론에 도달했는지**를 보존한다.
> 규범적(normative) 문서가 아니다. 결정과 충돌하면 언제나 `0004-always-durable-code-mode-runtime.md`가 이긴다.
>
> 남기는 이유: compact/요약은 *왜(why)*를 가장 먼저 잃는다. 6개월 뒤 "이건 왜 이렇게 했지"를 다시 논쟁하지 않기 위한 기록이다.

## 참여와 방식

```text
USER    소유자·결정권자
opus5   질문 주도 (유저 지정: "여기서 키는 opus5 가 잡는다")
gpt-sol Web ChatGPT peer, 반론·검증 담당
```

진행 규칙 (유저 지정):

1. `/grill-me`로 **용어와 문제 정의부터** 검증한다. 용어가 확정되기 전에는 API도 구현안도 확정하지 않는다.
2. handoff에 이미 답이 있거나 소스에서 확인 가능한 사실은 **다시 묻지 않는다**. 사용자 판단이 필요한 설계 선택지만 질문한다.
3. 각 질문에는 추천안과 트레이드오프를 함께 제시한다.
4. 과거 호환 금지. 토큰 절약. 복잡도 대비 가치 낮은 TestCase·Fallback 금지.

총 3라운드, Q1–Q18 + capability inventory 분기(Q11–Q14)로 종결.

## 배경 정정

handoff 문서의 서술은 부정확했다. 유저가 제공한 실제 경위:

```text
근본 원인
  chatgpt.com 이 MCP 2.0 Tasks 를 미지원 → async 구현이 태생적으로 열악

진화
  (1) 구식 sync/async + code_mode background 도입
  (2) "리턴 시 항상 TrackedTasks 를 붙인다" 아이디어 도입
      → 단계별 runtime 이해 부족으로 버그 다발
  (3) 개선 아이디어 탐색
  (4) 유저 결정: "이럴 거면 새로 만들자" (리뉴얼)
```

즉 리뉴얼의 동기는 tunnel 버그 자체가 아니라, **전달 방식과 실행 수명이 얽힌 구조**였다.

## 결정 목록 (D1–D13)

| # | 질문 | 결정 |
|---|---|---|
| D1 | Q1 목적 우선순위 | containment > CLI ergonomics > 용어·문서 정합성. "tunnel 원인을 몰라도 안전해야 한다"는 목표가 아니라 framing |
| D2 | Q2 정책 | 과거 호환 없음. 토큰 절약. 저가치 test·fallback 금지 |
| D3 | Q3 도메인 모델 | Option A (Execution 중심). Execution / Worker / Task / TrackedTasks. **`Job` 미사용**. `Execution 1 : Task 0..1` |
| D4 | Q4 identity | 공개 ID는 `execution_id` 단일. 구 ADR 0001 invariant 3 폐기 |
| D5 | Q5 MCP surface | tool 3개: `bootstrap`, `code_mode`, `task` |
| D6 | Q6 label | 모든 호출에 **required**, Execution launch metadata로 저장. Task 생성은 (a) 명시적 task 모드 (b) inline wait 만료 두 경우뿐. 명칭은 **Task publication**, "전달 실패"가 아님 |
| D7 | Q7 절대 상한 | 유한한 상한 유지. caller·model이 선택 불가. 부분 출력 보존, 자동 재시도 없음. 주 근거는 tunnel이 아니라 **resource containment** |
| D8 | Q8 저장·복구 | SQLite = control-plane SSOT, filesystem = artifact. 순서: accepted commit → spawn → **worker 자신이 CAS** → 성공 후에만 사용자 코드 |
| D9 | Q9 deadline 소유권 | `BACKGROUND` 삭제. child capability의 model 지정 `timeout` 삭제. runtime이 `min(정책, 잔여)` 계산. `deadline_remaining()`은 읽기 전용으로 존치 |
| D10 | Q10 run_command | 단일 capability. `run_bounded_worker`의 TERM→KILL→reap 재사용 + bash `-lc` + guard-bin PATH + **bounded streaming spool** + strip 금지 |
| D11 | Q11–Q14 | Agent·Model 4종 Code Mode 내부 유지. top-level 이동·`delegate` 통합 안 함. **내부 중복 정리는 범위 밖** |
| D12 | Q15 | 상한 초과 작업은 `systemd-run --user --unit=… --collect` 형제 unit. `setsid`는 실측으로 폐기 |
| D13 | Q16 | 절대 상한 = **3600s**. 유저가 내 추천안 B(1800s) 대신 C를 선택 |
| — | Q17 | "완료·미수령" 별도 상태 없음. `completed`는 명시적 dismiss까지 유지. `timed_out`은 상태가 아니라 `failed + reason` |
| — | Q18 | tunnel 절단 시 계속 실행 + Task publish. 취소는 `task(action="cancel")`뿐 |

## gpt-sol이 잡아낸 내 오류 3건

기록해 두는 이유: 셋 다 **그럴듯했지만 틀렸고**, 그대로 갔으면 설계에 박혔을 것들이다.

### ① `deadline × 0.8` 계약이라는 서술

내가 `tests/test_code_runtime.py`가 일반적인 0.8 비율 계약을 인코딩한다고 주장했다.

SOL 반론: 실제 정책은 piecewise다.

```text
cleanup_budget  = min(10, deadline * 0.2)
execution_cutoff = deadline - cleanup_budget

prod:  110 - 10   = 100      (비율 0.909)
test:  0.05 - 0.01 = 0.04    (비율 0.8)
```

0.8이 보인 것은 **테스트가 deadline을 0.05로 줄였기 때문**이다. 수용.

### ② "auto-detachment는 ADR 0003을 뒤집는다"는 framing

SOL 반론: 새 설계는 실행을 background로 **이동시키지 않는다**. Execution은 t=0부터 durable하고, 바뀌는 것은 inline wait과 awareness뿐이다.

결과: ADR 0003이 자동 detachment를 거부한 두 근거 중 "side effect 중복"은 **소멸**하고, "return semantics 변경"만 남았다 — 이건 discriminated output으로 해소. 수용.

### ③ 단일 ID가 crash gap을 없앤다는 주장

SOL 반론: `ExecutionManager.start()` **자체가** `meta.json`을 쓰기 전에 spawn한다. 단일 ID는 Task 매핑 gap만 없앨 뿐, launch journal은 별개 문제다.

이 지적이 Q8을 열었고, D8(journal + CAS)로 이어졌다. 수용.

## 내 제안 중 실측으로 폐기된 것: `setsid nohup`

절대 상한 초과 작업의 escape hatch로 `setsid nohup`을 제안했다. "코드 추가 0, 복잡도 0"이라고 주장했다. SOL이 "systemd cgroup을 못 벗어난다"고 반론했고, 나는 확신이 없어 **직접 실험**했다.

```bash
systemd-run --user --quiet --collect --unit=gd-escape-test /bin/bash -lc \
  'setsid nohup bash -c "for i in $(seq 1 60); do echo alive $i >> /tmp/escape_setsid.log; sleep 1; done" \
   </dev/null >/dev/null 2>&1 & sleep 2; echo parent_done'

systemctl --user status gd-escape-test --no-pager | tail -8
systemctl --user stop gd-escape-test
# +3s, +6s 시점 로그 줄 수 비교
```

결과:

```text
CGroup: /user.slice/.../gd-escape-test.service
        └─889606 bash -c "for i in $(seq 1 60); do echo alive ..."

stop 후 +3s: 2줄 / +6s: 2줄   → 증가 없음 = 함께 죽음
```

`setsid`한 자식이 **unit cgroup 안에 그대로 남아 있었다.** systemd는 process group이 아니라 **cgroup 단위로 kill**하기 때문이다. 반면 Popen fallback은 `killpg`만 쓰므로 같은 코드가 그 환경에서는 **탈출한다**.

즉 이 안은 "동작한다/안 한다"가 아니라 **백엔드마다 다르게 동작한다** — 가능한 결과 중 최악이다. 철회하고 `systemd-run --user` 형제 unit으로 교체했다.

### 왜 형제 unit인가

```text
systemd-run --user --unit=gd-detached-<name> --collect bash -lc '...'

cgroup 분리        Execution 의 child 가 아니라 sibling
취소 가능          systemctl --user stop
결과 관측 가능      journal
명시적 선언        unit 이름이 있으므로 우발적 daemon 과 구분됨
런타임 코드 추가     0
```

containment invariant는 유지된다. 작업이 감시를 벗어나는 것이 아니라, **다른 supervisor에게 명시적으로 위임**되기 때문이다.

## 그 밖에 폐기된 내 제안 2건

### 부모가 CAS를 수행

SOL 반론: 부모가 spawn 직후 죽으면 worker는 **이미 사용자 코드를 미추적 상태로 실행 중**이다. SOL의 순서(worker 자신이 CAS)를 채택.

### `deadline_remaining()` → child `timeout` 인자로 전달

SOL 반론: 확률적 caller에게 산술을 시키지 마라. 결국 **`timeout` 인자를 통째로 제거**해서 오용을 구조적으로 불가능하게 만들되, 읽기 전용 budget 가시성은 남기는 것으로 해소.

## 얻은 교훈

1. **OS 수준 주장은 "복잡도 0"이라고 말하기 전에 실측한다.** setsid 건은 실험 한 번이 설계 결함 하나를 막았다.
2. **인자를 제거하는 것이 계산법을 문서화하는 것보다 강하다.** 문서는 확률적 caller에게 강제력이 없다.
3. **이름이 중요하다.** "inline 전달 실패"는 정상 경로를 오류로 규정한다. SOL의 **"Task publication"**이 옳다.

## 범위 밖으로 기록만 한 발견

D11에 따라 이번 리뉴얼에서 손대지 않지만, 사라지면 안 되는 사실들:

- **보안**: `agy_worker`의 workspace 검증은 `is_dir()` 뿐이다. `subagent_call`과 `peer_review`는 둘 다 secret-path / denied-pattern 정책을 강제한다. **3사 불일치.**
- `_usage_summary`가 `model_call.py`와 `subagent_worker.py`에 **바이트 단위로 동일**하게 중복.
- `creds run ai -- uv run --project … python -m <module>` 커맨드 벡터와 `PROJECT_ROOT`/`CREDS`/`UV` 상수가 `subagent_runtime.py`와 `model_call.py`에 이중 존재.
- JSON 파싱 → `JSONDecodeError` → `worker_stderr` 꼬리 첨부 패턴이 3곳에 복제.
- `model_call._run_worker`의 non-peer 갈래는 **유일한 소비자가 `m3_evidence`**다.
- `council/sol.py`가 Web SOL 프롬프트에 `council_emit`이라는 문자열을 직접 박아넣는다. 이 capability를 제거하면 왕복이 깨진다 → 유지 결정의 근거.

## 이번 세션에서 하지 않은 것

코드 변경 0건, 커밋 0건. 전 과정이 설계 층이었다. 구현은 별도 작업으로 분리했다.

## References

- `0004-always-durable-code-mode-runtime.md`
  - 이 세션이 산출한 결정. 충돌 시 그쪽이 권위.
- `../CONTEXT.md`
  - 세션에서 확정한 용어가 반영된 glossary.
