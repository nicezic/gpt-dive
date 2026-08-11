from __future__ import annotations

from pathlib import Path

from pydantic_ai_harness import FileSystem, Shell
from pydantic_ai_harness.repo_context import RepoContext
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

from gpt_dive.subagent_worker import _build_worker_capabilities


def test_worker_capability_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-shell")
    monkeypatch.setenv("MINIMAX_API_KEY", "must-not-reach-shell")
    monkeypatch.setenv("AIAPIFLOW_CLAUDE_KEY", "must-not-reach-shell")

    capabilities = _build_worker_capabilities(str(tmp_path))
    assert [type(cap) for cap in capabilities] == [
        FileSystem,
        Shell,
        RepoContext,
        ToolOutputLimits,
    ]

    filesystem = capabilities[0]
    assert Path(filesystem.root_dir).resolve() == tmp_path.resolve()
    assert set(filesystem.get_toolset().tools) == {
        "read_file",
        "write_file",
        "edit_file",
        "list_directory",
        "search_files",
        "find_files",
        "create_directory",
        "file_info",
    }

    shell = capabilities[1]
    assert Path(shell.cwd).resolve() == tmp_path.resolve()
    assert set(shell.get_toolset().tools) == {
        "run_command",
        "start_command",
        "check_command",
        "stop_command",
    }
    assert "OPENAI_*" in shell.denied_env_patterns
    assert "MINIMAX_*" in shell.denied_env_patterns
    assert "AIAPIFLOW_*" in shell.denied_env_patterns
    assert shell.env["PATH"].split(":", 1)[0].endswith("gpt_dive/guard-bin")


def test_worker_filesystem_keeps_sensitive_defaults_protected(tmp_path: Path) -> None:
    filesystem = _build_worker_capabilities(str(tmp_path))[0]
    protected = set(filesystem.protected_patterns)
    assert ".git/*" in protected
    assert ".env" in protected
    assert "*.key" in protected
