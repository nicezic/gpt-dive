#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_ROOT="${1:-}"
SERIES="$ROOT_DIR/patches/series"

[[ -n "$PACKAGE_ROOT" ]] || { echo "usage: $0 <gbrain-package-root>" >&2; exit 2; }
[[ -f "$PACKAGE_ROOT/package.json" && -f "$PACKAGE_ROOT/src/cli.ts" ]] || {
  echo "not a GBrain source package: $PACKAGE_ROOT" >&2
  exit 2
}
[[ -f "$SERIES" ]] || { echo "missing overlay series: $SERIES" >&2; exit 2; }

parent="$(dirname "$PACKAGE_ROOT")"
stage="$(mktemp -d "$parent/.gbrain-overlay-stage.XXXXXX")"
backup="$PACKAGE_ROOT.gpt-dive-base-$(date +%Y%m%d%H%M%S)"
trap '[[ -d "$stage" ]] && rm -rf "$stage"' EXIT

cp -a "$PACKAGE_ROOT/." "$stage/"

while IFS= read -r patch_name; do
  [[ -n "$patch_name" ]] || continue
  patch_path="$ROOT_DIR/patches/$patch_name"
  echo "[overlay] check $patch_name"
  git -C "$stage" apply --check "$patch_path"
  git -C "$stage" apply "$patch_path"
done < "$SERIES"

"$ROOT_DIR/scripts/verify-overlay.sh" "$stage"

mv "$PACKAGE_ROOT" "$backup"
if ! mv "$stage" "$PACKAGE_ROOT"; then
  mv "$backup" "$PACKAGE_ROOT"
  echo "overlay swap failed; restored original package" >&2
  exit 1
fi
trap - EXIT

echo "overlay applied"
echo "package=$PACKAGE_ROOT"
echo "backup=$backup"
