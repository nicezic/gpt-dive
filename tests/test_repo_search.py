from __future__ import annotations

from pathlib import Path

from gpt_dive.repo_search import _compact_probe_result


def test_compact_probe_result_keeps_only_useful_context(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("def hello(): pass\n")
    data = {
        "results": [
            {
                "file": str(source),
                "lines": [1, 1],
                "code": "def hello(): pass",
                "score": 0.91,
                "owner_qualified_symbol": "hello",
                "language": "python",
                "matches": [{"text": "hello"}],
            }
        ],
        "summary": {"total_tokens": 7},
        "skipped_files": [{"file": "noise.py"}],
    }

    assert _compact_probe_result(data, tmp_path) == {
        "count": 1,
        "total_tokens": 7,
        "results": [
            {
                "file": "src/app.py",
                "lines": [1, 1],
                "code": "def hello(): pass",
                "score": 0.91,
                "symbol": "hello",
                "language": "python",
            }
        ],
    }
