from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_monty import MontyRuntimeError, MontyTypingError

import gpt_dive.code_capabilities as capabilities_module
from gpt_dive.code_capabilities import build_code_registry, code_runtime
from gpt_dive.code_mode_protocol import CODE_MODE_WORKER_PROTOCOL
from gpt_dive.code_runtime import CallableRegistry
from gpt_dive.command_runtime import runtime_record
from gpt_dive.execution_store import ExecutionStore, generate_execution_id
from gpt_dive.mcp_models import CodeModeCompleted

EXPECTED_CAPABILITIES = {
    "read_file",
    "read_execution_result",
    "write_file",
    "edit_file",
    "list_directory",
    "search_files",
    "find_files",
    "create_directory",
    "file_info",
    "agy_worker",
    "subagent_call",
    "peer_review",
    "council_emit",
    "run_command",
    "gz64",
    "deadline_remaining",
}


def registry_for_test(
    root: Path, *, duration_seconds: float = 60.0
) -> CallableRegistry:
    store = ExecutionStore(root / "runtime.sqlite3")
    execution_id = generate_execution_id()
    store.create(
        execution_id=execution_id,
        kind="test",
        label="test execution",
        cwd=str(root),
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=duration_seconds,
        cleanup_timeout_seconds=10.0,
        request_path=root / "request.json",
        artifact_dir=root / "artifacts",
        stdout_path=root / "stdout.log",
        stderr_path=root / "stderr.log",
        outcome_path=root / "outcome.json",
    )
    record = runtime_record(store.get(execution_id), store=store)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    return build_code_registry(str(root), record=record)


def run_code(
    root: Path,
    code: str,
    *,
    payload: str | None = None,
    duration_seconds: float = 60.0,
) -> Any:
    return asyncio.run(
        code_runtime.run(
            code,
            registry_for_test(root, duration_seconds=duration_seconds),
            cwd=str(root),
            payload=payload,
        )
    )


def test_registry_has_the_renewed_fifteen_capabilities(tmp_path: Path) -> None:
    registry = registry_for_test(tmp_path)
    descriptions = registry.describe()
    stubs = registry.type_check_stubs(include_payload=True)

    assert set(descriptions) == EXPECTED_CAPABILITIES
    assert "PAYLOAD: str" in stubs
    assert "BACKGROUND" not in stubs
    for removed in ("task_list", "task_collect", "task_cancel", "task_ack"):
        assert removed not in descriptions
    for name in ("agy_worker", "subagent_call", "peer_review"):
        assert "timeout" not in descriptions[name]["signature"]
    assert "declaration" in descriptions["run_command"]


def test_read_execution_result_recovers_full_72k_without_rerunning(
    tmp_path: Path,
) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    execution_id = generate_execution_id()
    original = "한글✅" * 8192  # exactly 72 KiB of UTF-8
    retained_path = tmp_path / "retained.stdout"
    retained_path.write_text(
        json.dumps(
            {"v": CODE_MODE_WORKER_PROTOCOL, "ok": True, "result": original},
            ensure_ascii=False,
        )
    )
    store.create(
        execution_id=execution_id,
        kind="code_mode",
        label="retained test",
        cwd=None,
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=120,
        cleanup_timeout_seconds=10,
        request_path=tmp_path / "request2.json",
        artifact_dir=tmp_path / "artifacts2",
        stdout_path=retained_path,
        stderr_path=tmp_path / "stderr2.log",
        outcome_path=tmp_path / "outcome2.json",
    )
    assert store.claim(execution_id, worker_pid=1000000, worker_start_ticks=None)
    store.finish(execution_id, exit_code=0)
    offset = 0
    parts = []
    while True:
        chunk = asyncio.run(
            code_runtime.run(
                "part = await read_execution_result(execution_id=PAYLOAD, offset="
                + str(offset)
                + ")\npart",
                registry_for_test(tmp_path),
                payload=execution_id,
            )
        )
        assert chunk["total_bytes"] == len(original.encode("utf-8"))
        assert (
            CodeModeCompleted(execution_id="paging", result=chunk).output_truncated
            is None
        )
        parts.append(chunk["content"])
        if chunk["next_offset"] is None:
            break
        assert chunk["next_offset"] > offset
        offset = chunk["next_offset"]
    assert "".join(parts) == original
    assert len(parts) == 3
    # Byte boundaries reject a location inside the 3-byte Hangul character.
    import pytest

    with pytest.raises(MontyRuntimeError):
        run_code(
            tmp_path,
            "await read_execution_result(execution_id=PAYLOAD, offset=1)",
            payload=execution_id,
        )
    with pytest.raises(MontyRuntimeError):
        run_code(
            tmp_path,
            "await read_execution_result(execution_id=PAYLOAD, offset=0, limit=1)",
            payload=execution_id,
        )


def test_registry_renders_typed_run_command_contract_without_breaking_positional_calls(
    tmp_path: Path,
) -> None:
    registry = registry_for_test(tmp_path)
    catalog = registry.model_catalog()
    stubs = registry.type_check_stubs()
    declaration = registry.describe()["run_command"]["declaration"]

    for rendered in (catalog, stubs, declaration):
        assert "class RunCommandResult(TypedDict)" in rendered
        assert "exit_code: int" in rendered
        assert "stdout: str" in rendered
        assert "stderr: str" in rendered
        assert "duration_ms: int" in rendered
        assert "truncated: bool" in rendered
    assert "async def run_command(*, command: str) -> RunCommandResult:" in catalog
    assert "async def run_command(command:" in stubs
    assert "-> RunCommandResult" in stubs


def test_registry_dispatches_pydantic_normalized_arguments() -> None:
    seen: list[int] = []

    def capture(value: int) -> int:
        seen.append(value)
        return value

    registry = CallableRegistry()
    registry.register("capture", capture)
    result = registry.as_external_lookup()["capture"]("7")

    assert result == 7
    assert seen == [7]


def test_runtime_returns_expression_and_payload_results(tmp_path: Path) -> None:
    assert run_code(tmp_path, "1 + 2") == 3
    assert run_code(
        tmp_path,
        "PAYLOAD.splitlines()",
        payload="first\nsecond",
    ) == ["first", "second"]


def test_capabilities_are_discoverable_inside_monty(tmp_path: Path) -> None:
    result = run_code(tmp_path, "CAPABILITIES")

    assert set(result) == EXPECTED_CAPABILITIES
    assert (
        "read-only Execution work budget" in result["deadline_remaining"]["description"]
    )


def test_run_command_is_awaited_bounded_and_preserves_output(tmp_path: Path) -> None:
    result = run_code(
        tmp_path,
        "await run_command(\"printf '  CLI_OK  \\n'; printf ' ERR ' >&2\")",
    )

    assert result == {
        "exit_code": 0,
        "stdout": "  CLI_OK  \n",
        "stderr": " ERR ",
        "duration_ms": result["duration_ms"],
        "truncated": False,
    }
    assert result["duration_ms"] >= 0


def test_run_command_rejects_invalid_host_result_before_monty_consumes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def invalid_result(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"exit_code": 0, "stdout": "OK"}

    monkeypatch.setattr(capabilities_module, "run_runtime_command", invalid_result)

    with pytest.raises(MontyRuntimeError):
        run_code(tmp_path, 'await run_command("true")')


def test_run_command_resolves_tool_from_mise_shims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    shim_dir = fake_home / ".local" / "share" / "mise" / "shims"
    shim_dir.mkdir(parents=True)
    tool = shim_dir / "mise-probe"
    tool.write_text("#!/bin/sh\nprintf 'MISE_SHIM_OK\\n'\n")
    tool.chmod(0o755)
    monkeypatch.setenv("HOME", str(fake_home))

    result = run_code(tmp_path, 'await run_command("mise-probe")')

    assert result["exit_code"] == 0
    assert result["stdout"] == "MISE_SHIM_OK\n"


def test_deadline_remaining_is_read_only_and_dynamic(tmp_path: Path) -> None:
    result = run_code(
        tmp_path,
        "first = deadline_remaining()\nsecond = deadline_remaining()\n"
        "{'first': first, 'second': second}",
    )

    assert 0 < result["second"] <= result["first"] <= 60


def test_runtime_supplies_child_budget_without_model_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_subagent(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"ok": True, "model": kwargs["alias"], "output": "OK"}

    monkeypatch.setattr(capabilities_module, "invoke_subagent", fake_subagent)

    result = run_code(
        tmp_path,
        "await subagent_call(alias='terra5', task='review', output_tokens_limit=321)",
    )

    assert result == {"ok": True, "model": "terra5", "output": "OK"}
    timeout = calls[0]["timeout"]
    assert isinstance(timeout, int | float)
    assert 0 < timeout <= 60
    assert calls[0]["workspace_dir"] == str(tmp_path)
    with pytest.raises((MontyTypingError, MontyRuntimeError)):
        run_code(
            tmp_path,
            "await subagent_call(alias='terra5', task='review', timeout=30)",
        )


def test_all_model_capabilities_receive_runtime_owned_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, dict[str, object]] = {}

    async def fake_agy(**kwargs: object) -> dict[str, object]:
        calls["agy"] = kwargs
        return {"ok": True}

    async def fake_peer(**kwargs: object) -> dict[str, object]:
        calls["peer"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(capabilities_module, "invoke_agy_worker", fake_agy)
    monkeypatch.setattr(capabilities_module, "invoke_model_call", fake_peer)

    run_code(
        tmp_path,
        "await asyncio.gather("
        "agy_worker(task='research'), "
        "peer_review(alias='micu', prompt='review'))",
    )

    assert set(calls) == {"agy", "peer"}
    for call in calls.values():
        timeout = call["timeout"]
        assert isinstance(timeout, int | float)
        assert 0 < timeout <= 60


def test_filesystem_capabilities_keep_conflict_and_secret_policy(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("original")
    stale_hash = hashlib.sha256(b"stale").hexdigest()[:12]

    assert "original" in run_code(tmp_path, "await read_file('target.txt')")
    with pytest.raises(Exception, match="Conflict: file"):
        run_code(
            tmp_path,
            f"await write_file('target.txt', 'changed', expected_hash={stale_hash!r})",
        )

    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret")
    with pytest.raises(Exception, match="denied by pattern"):
        run_code(tmp_path, "await read_file('.env')")


def test_read_file_raw_by_default_and_line_numbers(tmp_path: Path) -> None:
    sample = tmp_path / "sample.json"
    sample.write_text('{\n  "key": "value"\n}\n')

    # Default is exact raw content (no line numbers, no header)
    raw = run_code(tmp_path, "await read_file('sample.json')")
    assert raw == '{\n  "key": "value"\n}\n'

    # line_numbers=True includes header and line numbers
    formatted = run_code(tmp_path, "await read_file('sample.json', line_numbers=True)")
    assert "sample.json | 3 lines" in formatted
    assert "1\t{" in formatted

    # raw=False also produces formatted output
    formatted_via_raw = run_code(tmp_path, "await read_file('sample.json', raw=False)")
    assert "sample.json | 3 lines" in formatted_via_raw

    # offset & limit with raw
    sliced = run_code(tmp_path, "await read_file('sample.json', offset=1, limit=1)")
    assert sliced == '  "key": "value"\n'


def test_raw_read_round_trips_to_exact_edit_file_with_crlf(tmp_path: Path) -> None:
    target = tmp_path / "settings.txt"
    before = b'first\r\n  setting = "old"\r\nlast\r\n'
    after = before.replace(b'"old"', b'"new"')
    target.write_bytes(before)

    result = run_code(
        tmp_path,
        """
original = await read_file("settings.txt")
updated = original.replace('"old"', '"new"')
await edit_file("settings.txt", old_text=original, new_text=updated)
await read_file("settings.txt")
""",
    )

    assert result == after.decode()
    assert target.read_bytes() == after


def test_numbered_read_is_not_an_edit_anchor(tmp_path: Path) -> None:
    target = tmp_path / "settings.txt"
    target.write_text('first\nsetting = "old"\n')

    with pytest.raises(MontyRuntimeError, match="old_text not found"):
        run_code(
            tmp_path,
            """
numbered = await read_file("settings.txt", line_numbers=True)
await edit_file("settings.txt", old_text=numbered, new_text="wrong")
""",
        )

    assert target.read_text() == 'first\nsetting = "old"\n'


def test_raw_read_over_256k_is_complete_in_monty(tmp_path: Path) -> None:
    content = ("x" * 80 + "\n") * 4000
    (tmp_path / "large.txt").write_text(content)
    assert run_code(tmp_path, "await read_file('large.txt')") == content
    assert run_code(tmp_path, "await read_file('large.txt', offset=3234)") == (
        "".join(content.splitlines(keepends=True)[3234:])
    )


def test_read_file_rejects_1gb_before_loading(tmp_path: Path) -> None:
    target = tmp_path / "huge.txt"
    with target.open("wb") as f:
        f.truncate(1_000_000_000)
    for mode in ("", ", line_numbers=True"):
        with pytest.raises(MontyRuntimeError, match="1 GB"):
            run_code(tmp_path, f"await read_file('huge.txt'{mode})")


def test_raw_read_rejects_nontext_and_blocks_secret_symlinks(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"a\x00b")
    with pytest.raises(MontyRuntimeError, match="Binary file"):
        run_code(tmp_path, "await read_file('binary.bin')")

    (tmp_path / "late-nul.bin").write_bytes(b"x" * 9000 + b"\x00")
    with pytest.raises(MontyRuntimeError, match="Binary file"):
        run_code(tmp_path, "await read_file('late-nul.bin')")

    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"hello\xffworld")
    with pytest.raises(MontyRuntimeError, match="not valid UTF-8"):
        run_code(tmp_path, "await read_file('invalid.txt')")
    assert invalid.read_bytes() == b"hello\xffworld"

    (tmp_path / ".env").write_text("TOKEN=secret")
    (tmp_path / "env-link").symlink_to(".env")
    with pytest.raises(MontyRuntimeError, match="denied by pattern"):
        run_code(tmp_path, "await read_file('env-link')")


def test_broad_recursive_search_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        MontyRuntimeError,
        match="search_files refuses broad recursive search rooted at /",
    ):
        run_code(tmp_path, "await search_files('needle', path='/')")


def test_council_emit_uses_explicit_capability_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_emit(
        council_dir: str, message: str, expected_head: str | None
    ) -> dict[str, object]:
        return {
            "council_dir": council_dir,
            "message": message,
            "expected_head": expected_head,
        }

    monkeypatch.setattr(capabilities_module, "emit_sol_response", fake_emit)

    council = run_code(
        tmp_path,
        "await council_emit(council_dir='.', message='round')",
    )

    assert council["message"] == "round"


def test_gz64_rejects_unapproved_permission(tmp_path: Path) -> None:
    registry = registry_for_test(tmp_path)
    assert "user_permission" in registry.describe()["gz64"]["signature"]
    with pytest.raises(MontyRuntimeError, match="exact user_permission"):
        asyncio.run(
            code_runtime.run(
                "await gz64(payload='!', user_permission='unapproved')",
                registry,
            )
        )
