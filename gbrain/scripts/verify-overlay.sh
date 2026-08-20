#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="${1:-}"
[[ -n "$PACKAGE_ROOT" ]] || { echo "usage: $0 <gbrain-package-root>" >&2; exit 2; }

checks=(
  "src/commands/embed.ts:assertVoyageFreeQuotaGuard"
  "src/core/voyage-free-usage.ts:getVoyageUsageStatus"
  "src/core/source-groups.ts:setSourceGroup"
  "src/core/eval-capture.ts:retrieved_chunk_hashes"
  "src/core/types.ts:schema_pack_per_source"
)

for item in "${checks[@]}"; do
  file="${item%%:*}"
  needle="${item#*:}"
  grep -q "$needle" "$PACKAGE_ROOT/$file" || {
    echo "missing overlay invariant: $file :: $needle" >&2
    exit 1
  }
done

if grep -q "eval_candidate_chunk_text_hashes" "$PACKAGE_ROOT/src/core/migrate.ts"; then
  echo "local migration leaked into official GBrain migration registry" >&2
  exit 1
fi

echo "overlay invariants PASS"
