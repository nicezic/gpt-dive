# GPT Dive Context Map

## Context

- [Runtime](./docs/runtime/CONTEXT.md) — GPT Dive 전체의 `Execution`, `Worker`, `Task`, 비동기 작업 인지(awareness) 언어를 소유한다.
- [Conduit](./docs/conduit/CONTEXT.md) — `@c` 대화·제어 protocol과 Conduit 고유 대화 언어를 소유한다.

## 관계

- **Conduit → Runtime**: Conduit는 공용 Execution/Task 모델과 TrackedTasks projection(축약 투영)을 사용한다. 이 개념이나 Worker lifecycle을 별도로 소유하지 않는다.
- **Runtime → Conduit**: Runtime은 공용 비동기 작업 인지 정보를 제공하고, Conduit는 이를 별도 tunnel/control surface에 투영할 수 있다.
