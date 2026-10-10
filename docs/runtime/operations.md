# GPT Dive Runtime 운영 가이드

## 목적

Always-durable Runtime의 로컬 검증, state 확인, 안전한 service reload, failure 진단 절차를 다룬다. Architecture는 `architecture.md`, clock 의미는 `timeouts.md`가 소유한다.

## 로컬 검증

```text
source / schema 변경
        │
        ▼
format / lint / type / test
        │
        ▼
생성된 MCP schema 확인
        │
        ▼
service를 안전하게 reload
        │
        ▼
fresh ChatGPT session acceptance
```

Repository gate:

```bash
uv sync --python 3.14
uv run ruff check .
uv run pyright
uv run pytest -q
git diff --check
```

Service를 건드리기 전에 생성된 tool contract를 확인한다.

```bash
uv run python - <<'PY'
import asyncio
from gpt_dive.app import mcp

for tool in asyncio.run(mcp.list_tools()):
    print(tool.name, tool.input_schema)
PY
```

예상 top-level set은 `bootstrap`, `code_mode`, `task`, `wsl_exec`다. `code_mode`는 `label`과 `code`를 필수로 요구하고, `task`는 strict action union을 받으며, 모든 tool은 알 수 없는 인자를 거부해야 한다.

## MCP 운영 로그

MCP 서버 시작점(`gpt-dive` CLI / `python -m gpt_dive`)은 표준 라이브러리 `RotatingFileHandler`로 운영 이벤트를 기록한다.

- 위치: `~/gpt-dive/logs/gpt-dive.log`
- 최대 용량: 활성 5 MiB + 백업 파일 `gpt-dive.log.1`~`.3` (총 최대 약 20 MiB).
- 환경변수: `GPT_DIVE_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR|CRITICAL` (기본 `INFO`).
- 내용: 서버 시작/종료, MCP 요청, Code Mode 결과와 request/execution ID, Task 발행·취소·정리, 진단 오류.
- 일반 이벤트 로그에는 코드 본문이나 Payload를 의도적으로 기록하지 않는다. 단, 예외 메시지 자체가 입력 일부를 포함할 수 있으므로 운영 로그도 비공개로 취급한다. 개별 실행의 stdout/stderr는 Execution artifact에 별도 보관한다.
- 파일 로깅은 MCP **서버 프로세스 시작 시** 초기화하며 도구 호출/Worker별 중복 핸들러는 만들지 않는다.

확인: `tail -n 100 ~/gpt-dive/logs/gpt-dive.log` (서버 재시작 후 파일 생성).
별도 DB/의존성을 도입하지 않는다.

## Runtime state

```text
~/.local/state/gpt-dive/
├─ runtime.sqlite3          lifecycle + Task awareness + run_command evidence
├─ runtime.sqlite3-wal      active SQLite WAL
├─ runtime.sqlite3-shm
└─ executions/<id>/
   ├─ request.json             Worker가 읽으면 삭제
   ├─ stdout.log
   ├─ stderr.log
   ├─ outcome.json             recovery evidence
   └─ input.json               짧게 존재하는 Code Mode input

/tmp/gpt-dive-run-command/<execution_id>/<run_ordinal>/
├─ stdout                      private 0600, ≤ 8 MiB
└─ stderr                      private 0600, ≤ 8 MiB
```

Database가 lifecycle state를 소유한다. Artifact directory나 systemd unit만 보고 상태를 추론하지 않는다.

현재 row를 read-only Python으로 확인한다.

```bash
uv run python - <<'PY'
from gpt_dive.execution_store import ExecutionStore

store = ExecutionStore()
for row in store.list_executions():
    print(
        row['execution_id'],
        row['label'],
        row['state'],
        row['reason'],
        'published' if row['published_at'] else 'inline-only',
    )
PY
```

정상 transient unit 이름은 `gpt-dive-execution-<execution_id>.service`다.

## 안전한 MCP service reload

ChatGPT Web은 현재 conversation에 tool schema를 cache할 수 있다. Server restart만으로 기존 conversation이 새 schema를 읽는다고 가정하지 않는다. 최종 acceptance는 fresh ChatGPT Web session에서 한다.

`run_command` 내부에서 restart를 보낼 때는, 중단될 Execution의 descendant로 handoff가 남지 않도록 sibling user unit을 사용한다.

```bash
systemd-run --user --collect --unit=gd-mcp-restart \
  bash -lc 'sleep 3; sudo systemctl restart gpt-dive-tunnel.service'
```

독립 local terminal에서는 delayed command도 충분하다.

```bash
nohup bash -lc 'sleep 3; sudo systemctl restart gpt-dive-tunnel.service' \
  >/tmp/gpt-dive-mcp-restart.log 2>&1 &
```

Delay는 initiating response가 transport를 빠져나갈 시간을 준다. Restart를 보낸 뒤에는 사용자에게 control을 돌려주며, 교체 중인 server에 같은 응답에서 MCP call을 다시 보내지 않는다.

## Live acceptance

Fresh ChatGPT session에서 다음 순서로 확인한다.

1. `bootstrap`을 호출한다.
2. live `code_mode`와 `task` schema를 확인한다.
3. 필수 label이 있는 짧은 `code_mode`를 실행해 `status=completed`를 확인한다.
4. `delivery=task`로 실행한 뒤 다른 일을 계속하고, `task(get)`을 두 번 호출해 비파괴 조회를 증명한다.
5. 무해한 116초 `delivery=auto` 시험에서 약 114초에 Task ID를 받는지, 기존 단일 Execution이 완료되고 `task(get)`으로 결과를 회수하는지 확인한다. 오류 시 동일 명령을 즉시 재호출하지 않고 기존 실행부터 확인한다.
6. Terminal Task를 dismiss하고 `task(list)`에서 사라졌는지 확인한다.
7. `run_command`를 실행해 stdout/stderr whitespace와 structured field를 확인한다.
8. Transport loss를 시험할 때는 inline waiter만 중단하고, Execution이 cancel되지 않고 Task로 나타나는지 확인한다.

첫 acceptance probe로 production repository를 변경하지 않는다.

## Failure 진단

```text
call 실패
├─ GPT Dive request-entry log 없음
│  └─ tunnel/session/stdio 경계; Runtime은 작업을 수락하지 못함
├─ Execution state = failed
│  ├─ launch_interrupted  → Worker가 실행 권한을 얻지 못함
│  ├─ deadline_exceeded   → 43190초 work cutoff (12h)
│  ├─ worker_error        → stderr artifact 확인
│  └─ exit_code_<n>       → stdout/stderr 확인
├─ Execution state = cancelled
│  └─ 명시적 lifecycle cancellation이 terminal race에서 이김
└─ Execution state = lost
   ├─ worker_disappeared
   ├─ outcome_marker_invalid
   ├─ retained_result_missing
   ├─ cleanup_unconfirmed
   └─ retention_expired
```

`lost`를 replay로 수리하지 않는다. 사용자가 manual rerun이 안전한지 판단할 때까지 row와 증거를 보존한다.

## Error 통계

새 `runtime.sqlite3`의 `error_events`는 Execution당 최초 오류 1행(`execution_id UNIQUE`)을 기록한다. 실행 전 거절은 ID가 없으므로 별도 행이다. 원문 메시지·파일 경로 대신 분류 코드만 영속 저장하며, 수명 만료로 Execution artifact가 삭제돼도 집계는 유지된다. 반복 `task(get)`은 중복 삽입하지 않는다. Worker 또는 Runtime 상태 확정 지점에서 기록하므로 `task(get)` 호출이 없어도 오류를 집계할 수 있다. 통계 저장에 실패하면 `ERROR_EVENT persistence failed` 로그를 남기고 원래 실행 결과를 유지하므로, 이 경우 통계 누락은 가능하다. **Capability의 `ok=false`나 셸 종료 코드는 자동으로 Execution 오류로 분류하지 않는다.**

```sql
SELECT json_extract(error_json, '$.category') category,
       json_extract(error_json, '$.code') code, COUNT(*) executions
FROM error_events GROUP BY 1, 2 ORDER BY 3 DESC;

SELECT json_extract(d.value, '$.code') diagnostic, COUNT(*) occurrences
FROM error_events e, json_each(e.error_json, '$.diagnostics') d
GROUP BY 1 ORDER BY 2 DESC;
```

## Runtime 밖의 명시적 작업

긴 download처럼 독립 supervisor에 맡길 command:

```bash
systemd-run --user --unit=gd-detached-download --collect \
  bash -lc 'wget -O ~/large.iso <URL>'
```

Systemd로 관찰하고 취소한다.

```bash
systemctl --user status gd-detached-download.service
journalctl --user-unit gd-detached-download.service
systemctl --user stop gd-detached-download.service
```

이 sibling unit은 GPT Dive 밖에 있으므로 Execution row, Task, 자동 결과 보존, Runtime deadline이 없다. `setsid nohup ... &`은 동등한 대체가 아니다. Systemd service cgroup 안에는 남지만 Popen process group에서는 벗어날 수 있어 backend마다 결과가 달라진다.

## Retention

Execution terminal artifact와 SQLite `run_command` evidence는 5일 보존한다. `/tmp` working evidence는 Execution `accepted_at`으로부터 48시간 후 cleanup 대상이 된다. Dismissal은 awareness만 없애며 retained result는 즉시 삭제하지 않는다. Durable artifact가 만료된 undismissed Task는 `lost(reason=retention_expired)`로 바뀌어 명시적 dismiss 전까지 정직하게 남는다.

## Council 참고

Conduit Room(옛 Council)은 Playwright Extension을 통해 SOL input을 보내고 기존 `code_mode → council_emit` 계약으로 SOL output을 받는다. Browser/session 운영은 `docs/conduit/room/`이 소유하며 Runtime Execution/Task 의미를 바꾸지 않는다.

## 참고 문서

- `docs/runtime/architecture.md`
  - 여기서 관찰하는 state의 ownership과 source map.
- `docs/runtime/timeouts.md`
  - Response, work, cleanup, retention clock의 의미.
- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Replay, `setsid` escape, caller timeout, two-store authority를 거부한 이유.
