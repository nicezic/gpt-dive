---
title: ADR 0011 — Lossless Raw File Read for Monty
created: 2026-09-06
updated: 2026-10-20
type: decision
status: accepted
---

# ADR 0011 — Lossless Raw File Read for Monty

## Decision

`read_file(path)` 기본 모드는 **줄번호·헤더·잘림 안내가 섞이지 않은 원문 텍스트**를 Monty 내부에 전달한다. `json.loads`, 파싱, `edit_file(old_text=...)`의 입력으로 직접 사용하기 때문이다. AI-facing MCP 출력 제한을 이 내부 문자열에 적용하지 않는다([ADR 0005](0005-code-mode-output-contract.md)).

- `offset=0`이 시작 위치다. `offset`과 `limit`은 **0-based 줄 오프셋 / 줄 수** 기준이며, raw 결과도 동일하다.
- `line_numbers=True` 또는 `raw=False`는 Harness의 번호·메타데이터가 추가된 **표시용 뷰**다. 편집 앵커·전체 파일 원문으로 사용하지 않는다.
- raw 읽기는 원문 바이트를 UTF-8로 엄격히 해석한다. NUL 바이트나 유효하지 않은 UTF-8을 안내 문자열·대체 문자로 조용히 변형하지 않고 오류로 거부한다.
- 큰 파일은 메모리 보호를 위해 읽기 **전에** 크기 검사를 한다. 정확한 제한값은 `code_capabilities.py`/현재 architecture 문서가 소유한다.
- `write_file`과 `edit_file` 및 `expected_hash` 충돌 검사는 기존 Pydantic Harness를 재사용한다.

## Why

Harness의 기본 파일 뷰어는 사람/LLM에게 줄번호와 hash를 보여 주므로 raw 파서나 `edit_file`의 정확한 텍스트와 다르다. 2026-10 사고에서는 raw 읽기가 파일 전체를 메모리에 읽은 뒤 256KiB를 잘라 안내 문구와 함께 반환했고, 잘린 문자열이 완전한 파일로 오인되어 쓰기 손상이 발생했다. 이 조기 절단을 제거했다.

잘못된 UTF-8을 U+FFFD로 대체하거나 바이너리 파일에 설명 문장을 정상 반환하면 동일한 데이터 오인 위험이 있다. 엄격한 실패가 안전하다.

## Rejected

- Harness의 줄번호 뷰를 raw 기본값으로 사용: 파싱과 문자열 앵커가 실패한다.
- 내부 raw 값에 출력용 cap/preview 문자열 삽입: 데이터 무결성 훼손.
- 별도 바이너리 형식 감지 라이브러리: NUL+UTF-8 검사가 현재 범위에 충분하다.
- 잘못된 인코딩을 추측해 자동 수정: 원본 의미가 바뀔 수 있다.

## Compatibility / evidence

원래 ADR 0011이 다룬 Monty 멀티라인 예외 전파 문제는 [upstream issue 631](https://github.com/pydantic/monty/issues/631)와 Git 이력에 남는다. 이 결정은 현재 파일 읽기 무결성으로 범위를 명확히 했다. [architecture](../architecture.md)에 실제 제한과 표시용 경로가 기록된다. 테스트는 `tests/test_code_runtime.py`가 소유한다.
