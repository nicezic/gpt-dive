#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF_ROOT="${1:-${GBRAIN_REF_ROOT:-$HOME/ref/gbrain}}"
SERIES="$ROOT_DIR/patches/series"

[[ -d "$REF_ROOT/.git" ]] || { echo "missing clean GBrain ref: $REF_ROOT" >&2; exit 2; }
[[ -f "$SERIES" ]] || { echo "missing overlay series: $SERIES" >&2; exit 2; }
[[ -z "$(git -C "$REF_ROOT" status --porcelain)" ]] || { echo "GBrain ref is dirty: $REF_ROOT" >&2; exit 2; }

stage="$(mktemp -d "${TMPDIR:-/tmp}/gbrain-overlay-preflight.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

git clone --shared "$REF_ROOT" "$stage/repo" >/dev/null
git -C "$stage/repo" checkout --detach "$(git -C "$REF_ROOT" rev-parse HEAD)" >/dev/null

while IFS= read -r patch_name; do
  [[ -n "$patch_name" ]] || continue
  patch_path="$ROOT_DIR/patches/$patch_name"
  echo "[overlay] check $patch_name"
  git -C "$stage/repo" apply --check "$patch_path"
  git -C "$stage/repo" apply "$patch_path"
done < "$SERIES"

git -C "$stage/repo" diff --check
(
  cd "$stage/repo"
  bun install >/dev/null
  bunx tsc --noEmit
)

echo "overlay preflight PASS: $(git -C "$REF_ROOT" describe --tags --always)"
