# GPT Dive — 현재 Continuation

> 갱신: 2026-09-06
> 용도: AI 인수인계 및 새 세션 연결용 Single Source of Truth (SSOT).
> 설계 근거의 권위: [`docs/runtime/adr/0004-always-durable-code-mode-runtime.md`](file:///home/nicezic/gpt-dive/docs/runtime/adr/0004-always-durable-code-mode-runtime.md) 및 [`docs/runtime/adr/0011-read-file-raw-default-and-monty-alignment.md`](file:///home/nicezic/gpt-dive/docs/runtime/adr/0011-read-file-raw-default-and-monty-alignment.md).

---

## 1. 현재 목표 및 상태

Runtime v2의 Always-Durable execution, Codex-native typed tool contract(ADR 0010), 그리고 `read_file` raw default + Monty upstream wire protocol 정합(ADR 0011)이 완료되어 안정화된 상태다.

```text
[설계 및 검증 파이프라인]
ADR 0004 (Durable Runtime v2) ──→ ADR 0010 (Codex Contract) ──→ ADR 0011 (Raw read_file & Monty Fix)
              │                                │                                │
              ▼                                ▼                                ▼
    SQLite Control-Plane             Typed Stubs Catalog               Raw File Data Pipeline
              └────────────────────────────────┬────────────────────────────────┘
                                               ▼
                              로컬 검증: 169 Tests Passed (100% Green)
```

---

## 2. 핵심 계약 (Runtime Contract)

```text
Web MCP Tools
├─ bootstrap                                  ── 세션 오리엔테이션 및 위키 맵 로드
├─ code_mode(label, code, payload?, cwd?)    ── Pydantic Monty 격리 파이썬 코드 실행 (Durable)
└─ task({action: list|get|cancel|dismiss})    ── 백그라운드 Task 생명주기 관리 및 결과 수신

Execution & Storage
├─ 단일 식별자        : execution_id (6자리 URL-safe Base64)
├─ 상태 권위 (SSOT)   : SQLite (~/.local/state/gpt-dive/runtime-v2.sqlite3)
└─ 파일시스템         : OS 격리 및 artifact 보존 전용
```

### 불변 규칙
- **Always Durable**: 모든 `code_mode` 호출은 코드 실행 전 SQLite에 `accepted` 상태로 원자적 기록된다.
- **Strict Typed Contract**: Outer catalog stubs를 통해 첫 호출부터 positional/keyword signature를 준수하며, 알 수 없는 인자는 즉시 거부한다.
- **Raw File Transport**: `read_file`은 기본적으로 순수 텍스트(`line_numbers=False`)를 반환하여 `json.loads` 및 `edit_file` 파이프라인과 즉시 호환된다.

---

## 3. 최근 소스 변경 Delta (2026-09-06)

```text
변경 내역
├─ read_file 원문 기본화 (ADR 0011)
│  └─ line_numbers: bool = False, raw: bool | None = None 추가
│  └─ offset / limit 1-indexed 라인 슬라이싱 보존
│  └─ 파일: src/gpt_dive/code_capabilities.py
│
├─ 업스트림 라이브러리 최신화
│  └─ pydantic-monty >= 0.0.23: multiline exception의 column span 직렬화 버그(#631) 해결
│  └─ pydantic-ai-harness >= 0.29.0: 최신 툴체인 동기화
│  └─ mcp >= 2.1.1: UnexpectedToolError.__cause__ 예외 체이닝 지원
│  └─ 파일: pyproject.toml, uv.lock, src/gpt_dive/app.py
│
└─ 에러 아키텍처 SSOT 정립
   └─ 매 턴 수기 작성하던 ERROR_CASE.md 폐지
   └─ runtime-v2.sqlite3 DB 쿼리 기반 주기적 사후 감사 체제로 전환
```

---

## 4. 로컬 검증 현황 (Facts)

- **Pytest**: `169 passed in 13.99s` (100% 통과)
- **Ruff**: 통과 (`All checks passed!`)
- **Pyright**: 통과 (0 errors)
- **Git Diff**: `git diff --check` 클린 (0 warnings)
- **런타임 동작**:
  - `read_file` raw/formatted/sliced 계약 단위 테스트 통과 ([`tests/test_code_runtime.py`](file:///home/nicezic/gpt-dive/tests/test_code_runtime.py#L308-L325))
  - MCP 2.1.1 `UnexpectedToolError` 체이닝 표면 테스트 통과 ([`tests/test_surface.py`](file:///home/nicezic/gpt-dive/tests/test_surface.py#L42-L55))

---

## 5. 인수인계 문서 권위 (Pointers & Authority)

AI 에이전트가 후속 작업을 수행할 때 반드시 참조해야 하는 권위 문서 목록:

1. **런타임 라이프사이클 & 상태 모델**
   - [`docs/runtime/CONTEXT.md`](file:///home/nicezic/gpt-dive/docs/runtime/CONTEXT.md): Execution, Worker, Task, Publication, Lost의 정식 용어 정의.
   - [`docs/runtime/adr/0004-always-durable-code-mode-runtime.md`](file:///home/nicezic/gpt-dive/docs/runtime/adr/0004-always-durable-code-mode-runtime.md): Durable 런타임 설계 근거.
2. **Code Mode & Capability 규격**
   - [`docs/pydantic/code-mode.md`](file:///home/nicezic/gpt-dive/docs/pydantic/code-mode.md): 15개 등록 capability 및 파일시스템 경계.
   - [`docs/runtime/adr/0010-codex-native-tool-contract-alignment.md`](file:///home/nicezic/gpt-dive/docs/runtime/adr/0010-codex-native-tool-contract-alignment.md): 모델 제공용 typed stubs catalog 규격.
   - [`docs/runtime/adr/0011-read-file-raw-default-and-monty-alignment.md`](file:///home/nicezic/gpt-dive/docs/runtime/adr/0011-read-file-raw-default-and-monty-alignment.md): `read_file` raw text 전환 및 Monty #631 정합.
3. **런타임 아키텍처 & 운영**
   - [`docs/runtime/architecture.md`](file:///home/nicezic/gpt-dive/docs/runtime/architecture.md): 현재 시스템 아키텍처 및 command/filesystem 경계.
   - [`docs/runtime/operations.md`](file:///home/nicezic/gpt-dive/docs/runtime/operations.md): MCP tunnel 지연 재시작 및 배포 절차.
