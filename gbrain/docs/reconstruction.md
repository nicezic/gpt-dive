# GBrain Reconstruction and Operations

This is the current maintenance SSOT for GPT Dive's GBrain integration. Historical upgrade narratives belong in `../plans/`, not here.

## 1. Ownership model

The runtime is intentionally split into three planes:

```text
~/ref/gbrain
    clean upstream reference
            |
            | overlay preflight
            v
official Bun global GBrain + GPT Dive overlay
            |
            v
~/.gbrain
    persistent config / database / local GPT Dive migration ledger
```

GPT Dive owns the overlay. GBrain owns the upstream distribution and official migration namespace.

### Paths

```text
Upstream ref          ~/ref/gbrain
GPT Dive integration  ~/gpt-dive/gbrain
Installed package     ~/.bun/install/global/node_modules/gbrain
CLI                    ~/.bun/bin/gbrain
Persistent brain      ~/.gbrain
Production target     ~/.cache/gbrain-stable-index-v1/.gbrain
Local migration log   ~/.gbrain/gpt-dive/migrations.jsonl
```

`~/.gbrain` is currently a symlink to the Stable Index production target.

## 2. Current accepted state

```text
GBrain                0.46.24.0
Upstream stable       v0.46.24.0 / 7e3ce95bbf4c2e4902c8a35ff6a1f79bdbd54081
Install method        Bun global GitHub package + GPT Dive overlay
self_upgrade.mode     notify
official schema       132 (latest 132)
embedding             voyage:voyage-code-3, 1024d
reranker              voyage:rerank-2.5
search mode           conservative
source group          pydantic
pages                  1568
chunks                 27087
embedded               27087
stale                  0
```

Sources:

```text
pydantic-ai           896 pages
pydantic-ai-harness   357 pages
pydantic-ai-monty     315 pages
```

Reference checkouts:

```text
~/ref/pydantic-ai          v2.32.1 / f46c127c445ed60471fe9c778f1b93a30ec26b5c
~/ref/pydantic-ai-harness  v0.24.0 / 9989c4e83a1d1609664c58c16ab9b3cc6412c878
~/ref/pydantic-ai-monty    v0.0.21 / 70fe3f5781381eb33579e45046f8cb3845953373
```

## 3. Local overlay

Apply order is `../patches/series`.

Current units:

1. Voyage document-embedding quota guard hook.
2. Backtick-title frontmatter fix.
3. Voyage free-usage accounting and monthly reauthentication fence.
4. Named source groups.
5. Eval schema-pack provenance.
6. Exact retrieved-chunk hashes plus fresh-schema baseline column.
7. Explicit source-scope preservation.
8. Source revision provenance.

The overlay deliberately does **not** register a local migration number in GBrain's official migration registry.

### Preflight

Before touching the live package:

```bash
~/gpt-dive/gbrain/scripts/preflight-overlay.sh ~/ref/gbrain
```

This requires a clean upstream ref, clones it into an isolated temporary workspace, applies every overlay in order, runs `git diff --check`, installs dev dependencies in that isolated clone, and runs TypeScript typechecking.

Focused behavior acceptance additionally covers frontmatter inference, source groups, eval capture/export, and Voyage usage behavior.

### Live apply

```bash
~/gpt-dive/gbrain/scripts/apply-overlay.sh ~/.bun/install/global/node_modules/gbrain
```

The script copies the installed package into a sibling staging directory, checks/applies all overlays there, verifies runtime invariants, then swaps the completed stage into the canonical package path. A clean-base backup path is printed and retained until acceptance is complete.

Do not hand-edit failed hunks in the installed package. If preflight or live staging conflicts, stop and discuss the change with the user.

## 4. GPT Dive schema extensions

Official GBrain `config.version` belongs only to GBrain.

GPT Dive schema extensions use:

```text
runner  ~/gpt-dive/gbrain/migrations/apply.ts
ledger  ~/.gbrain/gpt-dive/migrations.jsonl
```

Current extension:

```text
001-eval-candidate-chunk-hashes
```

It ensures:

```sql
ALTER TABLE eval_candidates
  ADD COLUMN IF NOT EXISTS retrieved_chunk_hashes TEXT[] NOT NULL DEFAULT '{}';
```

Fresh overlaid GBrain schemas already include the column in their baseline schema files. Existing official brains receive it through the GPT Dive migration runner. Neither path advances GBrain's official schema version.

### Historical v133 repair

Before this ownership split, the local extension occupied GBrain migration number 133. On 2026-08-20 production was verified to contain upstream v131/v132 plus the local column, then normalized once from official schema stamp `133` to `132`.

The one-time repair is guarded by:

- installed GBrain must be exactly `0.46.24.0`;
- `retrieved_chunk_hashes` must already exist;
- upstream v132 `checkpoint_manifest` must exist;
- the upstream v131-dropped `uniq_subagent_tools_use_id` constraint must be absent.

Current production ledger records the normalization as complete. Do not use the normalization flag on later GBrain versions.

Normal local migration command:

```bash
bun ~/gpt-dive/gbrain/migrations/apply.ts \
  --package-root ~/.bun/install/global/node_modules/gbrain
```

## 5. Voyage free-quota guard

Tracked sources:

```text
~/gpt-dive/gbrain/scripts/voyage-free-guard
~/gpt-dive/gbrain/scripts/voyage-dashboard-session-enroll
```

Runtime installs:

```text
~/.local/bin/voyage-free-guard
~/.local/bin/voyage-dashboard-session-enroll
```

Install/update them with:

```bash
install -m 0755 ~/gpt-dive/gbrain/scripts/voyage-free-guard ~/.local/bin/voyage-free-guard
install -m 0755 ~/gpt-dive/gbrain/scripts/voyage-dashboard-session-enroll ~/.local/bin/voyage-dashboard-session-enroll
```

Normal guard check:

```bash
creds run ai -- ~/.local/bin/voyage-free-guard --json
```

Policy:

- warning at 80% estimated free usage;
- new corpus embedding is blocked when the authoritative snapshot is past its 30-day reauthentication deadline;
- query embedding remains available;
- no new corpus embedding is permitted when the guard is not PASS;
- an old successful guard result is evidence only, never reusable authorization for a later embedding run.

Current accepted guard after the 0.46.24 ownership cutover: PASS, `reauthRequired=false`.

## 6. Stable Pydantic index

Filter policy:

```text
~/gpt-dive/gbrain/docs/index-filter.md
```

Refresh helper:

```text
~/gpt-dive/gbrain/scripts/stable-index-refresh
```

The stable corpus is exactly the three physical Pydantic sources listed above. They remain separate for release/sync tracking and are combined for ordinary trusted-local retrieval through the named `pydantic` source group.

Do not rebuild or re-embed merely because GBrain itself was upgraded. Re-embedding requires a real corpus/provider/dimension change and a fresh guard PASS.

## 7. Upgrade contract

Routine GBrain upgrades are owned by the local `/update-gbrain` workflow. The workflow must read both:

1. the installed upstream `skills/gbrain-upgrade/SKILL.md`;
2. this reconstruction policy.

If the two conflict or upstream appears to supersede a local overlay, stop and discuss it with the user. Do not silently choose a side or retire a local feature.

### Required sequence

```text
verify self_upgrade.mode != auto
→ resolve exact target stable
→ update/inspect clean ~/ref/gbrain
→ read upstream changelog + migration changes
→ check whether upstream absorbed any local overlay
→ run overlay preflight against the target
→ conflict? STOP + user discussion
→ run the official upgrade action
→ reapply GPT Dive overlay to the installed package
→ run official migrations explicitly
→ run GPT Dive migrations
→ reinstall/verify local helpers
→ guard + health + stale + retrieval acceptance
→ update current-state docs if the accepted base changed
→ commit only relevant GPT Dive/Wiki changes
```

`self_upgrade.mode=auto` is incompatible with an overlaid runtime because an unattended package swap would remove the overlay. Keep the install in `notify` mode.

Bun may block GBrain's package `postinstall`. Therefore the local workflow always runs official migrations explicitly after base replacement:

```bash
gbrain apply-migrations --yes
```

Do not treat a successful package-manager command as completed acceptance.

## 8. Reconstruction from a clean machine

1. Clone/update GPT Dive.
2. Clone official GBrain into `~/ref/gbrain` and checkout the exact accepted stable tag.
3. Install the exact official base from GitHub with Bun global install.
4. Run `preflight-overlay.sh` against the clean ref.
5. Apply the overlay to the installed package with `apply-overlay.sh`.
6. Restore or initialize the persistent `~/.gbrain` data/config plane.
7. Run official GBrain migrations explicitly.
8. Run GPT Dive migrations.
9. Install the two Voyage helper scripts from this integration directory.
10. Verify the Voyage guard before any corpus embedding.
11. Run the acceptance contract below.

Do not restore the old downstream GBrain Git branch as the normal runtime. Historical source-checkout state is rollback evidence only.

## 9. Acceptance contract

Minimum acceptance after an upgrade or reconstruction:

```bash
gbrain --version
readlink -f ~/.bun/bin/gbrain
git -C ~/ref/gbrain status --short
~/gpt-dive/gbrain/scripts/verify-overlay.sh ~/.bun/install/global/node_modules/gbrain
gbrain apply-migrations --yes
gbrain doctor --json
creds run ai -- ~/.local/bin/voyage-free-guard --json
creds run ai -- gbrain embed --stale --dry-run
```

Required outcomes:

- installed package version is the accepted target;
- CLI resolves into Bun global `node_modules/gbrain`, not a development checkout;
- upstream ref is clean;
- overlay invariants pass;
- official schema version equals official latest;
- GPT Dive migration ledger is complete;
- embeddings are 100% covered;
- stale dry-run is zero unless a separately approved corpus change intentionally created work;
- Voyage guard is PASS before corpus embedding;
- representative retrieval succeeds for Core, Harness, Monty, and a cross-source `pydantic` query.

Current accepted retrieval canaries:

- Core: `AbstractAgent.run` implementation/behavior.
- Harness: Code Mode registered-capability/Python execution.
- Monty: resource limits.
- Cross-source: Harness Code Mode + Monty execution/resource limits.

## 10. Recovery

`apply-overlay.sh` does not mutate the live package until all overlays have applied and invariants have passed in its staging copy. On successful swap it prints the clean-base backup path.

If acceptance fails after the swap, preserve the failing output and restore the printed clean-base package before attempting a different repair. Do not improvise a new patch or migration. If the failure exposes a real design decision, return to the user.

The production database is independent from package replacement. Never delete/reinitialize the brain as a package-upgrade recovery tactic unless the user explicitly chooses a data-plane rebuild.
