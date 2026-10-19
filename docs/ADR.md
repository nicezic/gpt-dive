# Architecture Decisions — GPT Dive

**ADR은 장기적으로 유지할 `Decision + Why + Rejected alternative`만 소유한다.** 현재 값·공개 schema·구현 상태는 소스·테스트와 각 도메인의 `architecture.md`, `CONTEXT.md`, `operations.md`가 우선한다. Web AI의 실행 습관은 `~/wiki/workflow/`가 소유한다. 실험, 미구현 계획, 오래된 acceptance 기록은 `plans/` 또는 Git 이력이다.

## Current decisions

| 경계 / 단일 책임 | ADR | 상태 |
|---|---|---|
| 수락부터 durable한 Execution, Task 수명·동일 ID | [Runtime 0004](runtime/adr/0004-always-durable-code-mode-runtime.md) | Accepted |
| 온전한 Monty 중간 데이터, MCP 최종 출력 경계 | [Runtime 0005](runtime/adr/0005-code-mode-output-contract.md) | Accepted |
| Runtime-owned passive TrackedTasks 노출 | [Runtime 0006](runtime/adr/0006-tracked-tasks-connector-projection.md) | Accepted |
| 첫 호출 전 generated capability 계약과 최소 AI 안내 | [Runtime 0007](runtime/adr/0007-capability-contract-and-model-guidance.md) | Accepted |
| 원본 `run_command` 증거 보존·조회 확대안 | [Runtime 0008](runtime/adr/0008-raw-execution-evidence-recovery.md) | Proposed |
| 원문 무결성, UTF-8와 바이너리·읽기 역할 구분 | [Runtime 0011](runtime/adr/0011-read-file-raw-default-and-monty-alignment.md) | Accepted |
| 대화 중심 Task 발견과 OEP (Conduit 관점) | [Conduit 0001](conduit/adr/0001-conversation-driven-task-pull.md) | Accepted |
| 호스트 파일시스템 접근·secret 경계 | [Pydantic 0004](pydantic/adr/0004-code-mode-host-filesystem-policy.md) | Accepted |

번호는 **역사적 ID**라 연속되도록 재번호를 매기지 않는다. 이름이 같은 0004는 도메인 디렉터리로 구분한다.

## Consolidated / moved records (2026-10-20)

- Runtime 0009 명칭 원칙 → Runtime 0004 (delivery·Task) 및 0005 (status·result).
- Runtime 0010 typed/Codex 계약 → Runtime 0007 (최소 안내와 통합).
- Conduit 0002 cross-surface awareness/OEP → Conduit 0001. 실제 Runtime projection은 Runtime 0006.
- Pydantic 0002 upstream clone 위치 → [Pydantic README](pydantic/README.md). 운영 디렉터리 규칙이라 ADR에서 제외.
- 미구현 `TODO-durable-agy-worker` → [plan](../plans/runtime/2026-08-30-top-level-durable-agy-worker.md). Accepted ADR로 표시하지 않는다.

통합 전 원문과 설계 실험은 Git 이력으로 복원할 수 있다. 과거 번호·링크를 현행 코드 계약으로 사용하지 않는다.

## Admission rule

1. 장기적인 권위·보안·데이터 무결성·lifecycle 경계이며, 미래에 다시 도입할 만한 현실적 대안이 있을 때 ADR 작성.
2. 값 변경, 구현 세부사항, 테스트 결과, 단발성 사고는 현재 구현 문서나 `plans/`로 기록.
3. 새 ADR은 **하나의 논리 책임**만 갖는다. 기존 결정을 바꾸면 해당 ADR의 현재 원칙을 정리하고 출처를 기록한다. 새로운 번호가 꼭 필요한 별도 결정만 신설한다.
