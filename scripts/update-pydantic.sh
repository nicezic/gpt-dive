#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: scripts/update-pydantic.sh <pydantic-ai-core-version> <harness-version>" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
CORE_VERSION="$1"
HARNESS_VERSION="$2"

for version in "$CORE_VERSION" "$HARNESS_VERSION"; do
  if [[ ! "$version" =~ ^[0-9][0-9A-Za-z.+!-]*$ ]]; then
    echo "update-pydantic: invalid exact version: $version" >&2
    exit 2
  fi
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -f pyproject.toml ]] || { echo "update-pydantic: pyproject.toml not found" >&2; exit 2; }
[[ -f README.patch.openai.provider.md ]] || { echo "update-pydantic: Codex compatibility SSOT not found" >&2; exit 2; }

harness_lines="$(grep -Ec '^[[:space:]]*"pydantic-ai-harness==[^\"]+",?[[:space:]]*$' pyproject.toml || true)"
[[ "$harness_lines" == "1" ]] || {
  echo "update-pydantic: expected exactly one pinned pydantic-ai-harness dependency, found $harness_lines" >&2
  exit 2
}

echo "==> target: pydantic-ai-slim=$CORE_VERSION pydantic-ai-harness=$HARNESS_VERSION"
echo "==> updating Harness direct pin"
sed -i -E "s/(\"pydantic-ai-harness==)[^\"]+/\\1${HARNESS_VERSION}/" pyproject.toml

echo "==> resolving exact Pydantic targets"
uv lock \
  -P "pydantic-ai-slim==${CORE_VERSION}" \
  -P "pydantic-ai-harness==${HARNESS_VERSION}"

echo "==> syncing Python 3.14 environment"
uv sync --python 3.14

echo "==> verifying resolved package versions and lazy Codex isolation"
EXPECTED_CORE="$CORE_VERSION" EXPECTED_HARNESS="$HARNESS_VERSION" \
uv run --python 3.14 python - <<'PY'
import importlib.metadata
import os
import sys

core = importlib.metadata.version("pydantic-ai-slim")
harness = importlib.metadata.version("pydantic-ai-harness")
assert core == os.environ["EXPECTED_CORE"], (core, os.environ["EXPECTED_CORE"])
assert harness == os.environ["EXPECTED_HARNESS"], (harness, os.environ["EXPECTED_HARNESS"])

import pydantic_ai  # noqa: F401
import gpt_dive  # noqa: F401

assert "gpt_dive.openai_codex" not in sys.modules
print(f"resolved: pydantic-ai-slim={core} pydantic-ai-harness={harness}")
PY

echo "==> running focused Pydantic/Harness compatibility tests"
uv run --python 3.14 pytest -q \
  tests/test_openai_codex_compat.py \
  tests/test_code_runtime.py \
  tests/test_subagent_runtime.py \
  tests/test_bare.py \
  tests/test_bootstrap.py

echo "==> running Ruff"
uv run --python 3.14 ruff check src tests

echo "==> running Pyright"
uv run --python 3.14 pyright

echo "PASS: Pydantic stack updated and basic validation passed"
