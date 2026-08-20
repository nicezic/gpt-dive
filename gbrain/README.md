# GPT Dive GBrain Integration

GPT Dive owns the local GBrain customization layer. Upstream GBrain remains replaceable; local policy, overlays, helpers, tests, and GPT Dive-only schema extensions live here.

## Ownership

- **Runtime base:** official Bun global GBrain package.
- **Upstream reference:** `~/ref/gbrain` — clean checkout used only for inspection and overlay preflight.
- **Persistent brain:** `~/.gbrain` — configuration and database plane, independent from package replacement.
- **Local integration:** this directory.

## Layout

- `docs/reconstruction.md` — current reconstruction, upgrade, recovery, and acceptance SSOT.
- `docs/index-filter.md` — Stable Index inclusion/exclusion policy.
- `patches/` — ordered GBrain source overlays. `series` is the apply order.
- `scripts/preflight-overlay.sh` — apply/check overlays against an isolated clone of the clean upstream ref and typecheck it.
- `scripts/apply-overlay.sh` — stage the installed package, apply overlays there, verify invariants, then swap the completed stage into place.
- `scripts/verify-overlay.sh` — runtime overlay invariants.
- `scripts/stable-index-refresh` — Stable Index refresh helper.
- `scripts/voyage-free-guard` — fail-closed Voyage free-quota guard.
- `scripts/voyage-dashboard-session-enroll` — explicit Voyage dashboard-session enrollment/refresh helper.
- `migrations/apply.ts` — GPT Dive-only schema extension runner and ledger writer.
- `tests/` — local helper tests.
- `plans/` — historical and current GBrain decisions.

## Core rule

Never add GPT Dive migrations to GBrain's official migration-number registry. Official `config.version` belongs to GBrain. GPT Dive migrations are idempotent extensions tracked separately under `~/.gbrain/gpt-dive/migrations.jsonl`.

For upgrades or reconstruction, read `docs/reconstruction.md` before mutating the installed package or production brain.
