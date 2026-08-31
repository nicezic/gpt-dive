---
title: ADR - Raw Execution Evidence Recovery
created: 2026-08-30
updated: 2026-08-31
type: decision
status: proposed
---

# ADR 0008 — Raw Execution Evidence Recovery

> ADR 0005의 normal path는 compact `output`이다. 이 ADR은 결과가 이상할 때 **retained Execution evidence를 `execution_id`로 다시 찾아 선택적으로 검사하는 경로**만 결정한다. Naming은 ADR 0009가 소유한다.

## 결정 요약

```text
suspicious compact output
        ↓ execution_id
compact evidence discovery
        ↓
selected retained artifact read
        ↓ local grep / parse / compare
small final output
```

> **Retain locally, inspect selectively, return compactly.**

새 로그 저장소를 만들지 않는다. SQLite는 lifecycle truth를, 기존 Execution artifact directory는 retained evidence bytes를 소유한다.

## 현재 retained evidence

```text
~/.local/state/gpt-dive/
├─ runtime-v2.sqlite3              lifecycle authority
└─ executions-v2/<execution_id>/   artifact authority
   ├─ stdout.log
   ├─ stderr.log
   ├─ outcome.json
   └─ capability-output/
      └─ run-command-*.log
```

| Artifact | 의미 |
|---|---|
| `outcome.json` | process-level exit/reason marker |
| `stdout.log` | Code Mode worker protocol의 retained final output |
| `stderr.log` | worker/runtime failure evidence |
| `run-command-*.log` | truncated `run_command` stdout/stderr spill |

`stdout.log`는 Monty `print()` transcript가 아니다. 현재 `run_command`는 stdout/stderr를 stream당 최대 8 MiB spool하고 model-facing preview를 8,000 chars로 제한하며, preview가 truncated됐을 때 combined spill을 남긴다.

## 결정

### 1. 기존 authority와 retention을 재사용한다

```text
SQLite     → state / reason / publication / retention truth
filesystem → retained evidence bytes
```

- 별도 SQLite BLOB/evidence store를 만들지 않는다.
- terminal artifact는 기존 5-day retention을 따른다.
- Task dismissal은 artifact deletion이 아니다.
- expired/missing/unretained evidence를 자동 replay로 만들어내지 않는다.

### 2. Recovery는 `execution_id → compact manifest` discovery다

Top-level raw-dump MCP tool이나 `task(get, raw=...)`를 추가하지 않는다. Inline-only Execution도 recovery할 수 있어야 하므로 Task publication과 결합하지 않는다.

개념적 manifest:

```json
{
  "execution_id": "abc123",
  "state": "completed",
  "reason": null,
  "artifact_dir": "/home/.../executions-v2/abc123",
  "artifacts": [
    {"path": "stdout.log", "bytes": 42},
    {"path": "stderr.log", "bytes": 0},
    {"path": "capability-output/run-command-....log", "bytes": 37695}
  ]
}
```

Discovery capability는 raw content를 기본 반환하지 않고, `execution_id`를 current retained artifact set으로 안전하게 resolve한다. Capability 이름은 ADR 0009에서 확정한다.

### 3. Raw 내용 읽기와 reduction은 기존 capability를 재사용한다

```python
manifest = await execution_evidence("abc123")  # working name
raw = await read_file(manifest["artifact_dir"] + "/stderr.log")
{"errors": [line for line in raw.splitlines() if "Error" in line][:20]}
```

새 recovery surface를 arbitrary filesystem browser로 만들지 않는다. 큰 raw artifact도 Monty 안에서 선택적으로 읽고 줄인 뒤 작은 final `output`만 model context로 보낸다.

### 4. Complete transcript를 만들지 않는다

모든 intermediate capability result를 자동 persistence하지 않는다. Final output로 선택되지 않았고 별도 retained artifact도 없으면 after-the-fact recovery를 보장하지 않는다.

```text
read_file / repo_search intermediate result
model/reviewer response
non-truncated run_command rich object
other Monty local intermediate data
```

모든 값을 기록하면 disk/privacy/cleanup 비용이 커지고 ADR 0005의 local-reduction boundary가 transcript recorder로 변한다.

## 폐기한 대안

| 대안 | 폐기 이유 |
|---|---|
| every capability output persistence | transcript system화 + disk/privacy/cleanup 비용 |
| SQLite BLOB | lifecycle authority와 raw-byte authority 혼합 |
| top-level raw evidence tool | model context에 raw dump 유도 |
| `task(get, raw=...)` | Task가 아닌 Execution recovery 불가 + lifecycle 의미 혼합 |
| artifact path 암기 | private layout이 public API가 됨 |
| 별도 evidence TTL | 기존 retention과 이중 clock |
| missing evidence replay | side-effect safety를 추측해야 함 |

## 구현 불변조건

- lifecycle authority는 SQLite, retained raw bytes authority는 existing artifact directory다.
- recovery는 Task publication 여부와 무관하게 retained Execution `execution_id`를 처리한다.
- discovery result는 compact manifest이며 raw bytes를 기본 model-facing result로 dump하지 않는다.
- selected artifact inspection은 existing filesystem capability와 local reduction을 재사용한다.
- existing 5-day retention을 재사용하고 missing evidence를 replay하지 않는다.
- 모든 intermediate capability result를 자동 persistence하지 않는다.

## Non-goal

- complete execution transcript / every capability recording
- automatic replay/retry or permanent audit archive
- Task awareness — ADR 0006
- model guidance — ADR 0007
- final vocabulary — ADR 0009

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
- `docs/runtime/adr/0005-code-mode-output-contract.md`
- `docs/runtime/adr/0009-runtime-terminology-and-naming.md`
- `docs/runtime/operations.md`
- `docs/runtime/timeouts.md`
- `src/gpt_dive/execution_store.py`, `src/gpt_dive/execution_manager.py`
- `src/gpt_dive/execution_worker.py`
- `src/gpt_dive/command_runtime.py`
