#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: scripts/update-pydantic.sh <pydantic-ai-core-version> <harness-version> <monty-version>" >&2
  exit 2
}

[[ $# -eq 3 ]] || usage
CORE_VERSION="$1"
HARNESS_VERSION="$2"
MONTY_VERSION="$3"

for version in "$CORE_VERSION" "$HARNESS_VERSION" "$MONTY_VERSION"; do
  if [[ ! "$version" =~ ^[0-9][0-9A-Za-z.+!-]*$ ]]; then
    echo "update-pydantic: invalid exact version: $version" >&2
    exit 2
  fi
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -f pyproject.toml ]] || { echo "update-pydantic: pyproject.toml not found" >&2; exit 2; }

harness_lines="$(grep -Ec '^[[:space:]]*"pydantic-ai-harness(==|>=)[^\"]+",?[[:space:]]*$' pyproject.toml || true)"
[[ "$harness_lines" == "1" ]] || {
  echo "update-pydantic: expected exactly one pydantic-ai-harness dependency, found $harness_lines" >&2
  exit 2
}

echo "==> target: pydantic-ai-slim=$CORE_VERSION pydantic-ai-harness=$HARNESS_VERSION pydantic-monty=$MONTY_VERSION"
echo "==> updating Harness dependency requirement"
sed -i -E "s/(\"pydantic-ai-harness(==|>=))[^\"]+/\\1${HARNESS_VERSION}/" pyproject.toml

echo "==> updating Monty dependency requirement"
sed -i -E "s/(\"pydantic-monty>=)[^\"]+/\\1${MONTY_VERSION}/" pyproject.toml

echo "==> resolving exact Pydantic targets"
uv lock \
  -P "pydantic-ai-slim==${CORE_VERSION}" \
  -P "pydantic-ai-harness==${HARNESS_VERSION}" \
  -P "pydantic-monty==${MONTY_VERSION}"

echo "==> syncing Python 3.14 environment"
uv sync --python 3.14

echo "==> verifying resolved package versions"
EXPECTED_CORE="$CORE_VERSION" EXPECTED_HARNESS="$HARNESS_VERSION" EXPECTED_MONTY="$MONTY_VERSION" \
uv run --python 3.14 python - <<'PY'
import importlib.metadata
import os

core = importlib.metadata.version("pydantic-ai-slim")
harness = importlib.metadata.version("pydantic-ai-harness")
monty = importlib.metadata.version("pydantic-monty")
assert core == os.environ["EXPECTED_CORE"], (core, os.environ["EXPECTED_CORE"])
assert harness == os.environ["EXPECTED_HARNESS"], (harness, os.environ["EXPECTED_HARNESS"])
assert monty == os.environ["EXPECTED_MONTY"], (monty, os.environ["EXPECTED_MONTY"])

import pydantic_ai  # noqa: F401
import gpt_dive  # noqa: F401

print(f"resolved: pydantic-ai-slim={core} pydantic-ai-harness={harness} pydantic-monty={monty}")
PY

echo "==> running complete test suite"
uv run --python 3.14 pytest -q

echo "==> running Ruff"
uv run --python 3.14 ruff check .
uv run --python 3.14 ruff format --check .

echo "==> running Pyright (CI source scope)"
uv run --python 3.14 pyright src

echo "PASS: Pydantic stack updated and basic validation passed"
