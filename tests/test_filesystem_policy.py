from pathlib import Path

from gpt_dive.filesystem_policy import GLOBAL_SECRET_PATTERNS, harness_denied_patterns


def test_harness_denied_patterns_prefixes_home_secrets_from_ancestor_root() -> None:
    patterns = harness_denied_patterns(root=Path("/home"), home=Path("/home/alice"))

    assert "**/.env" in patterns
    assert "alice/.ssh" in patterns
    assert "alice/.ssh/**" in patterns
    assert "alice/.local/share/keyrings/**" in patterns


def test_harness_denied_patterns_for_repo_root_keep_global_secret_guards() -> None:
    patterns = harness_denied_patterns(
        root=Path("/home/alice/project"),
        home=Path("/home/alice"),
    )

    assert patterns == GLOBAL_SECRET_PATTERNS
