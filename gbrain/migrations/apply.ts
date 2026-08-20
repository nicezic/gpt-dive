#!/usr/bin/env bun

import { existsSync, mkdirSync, readFileSync, appendFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const valueAfter = (flag: string): string | null => {
  const i = args.indexOf(flag);
  return i >= 0 ? (args[i + 1] ?? null) : null;
};

const packageRoot = resolve(
  valueAfter('--package-root') ?? process.env.GBRAIN_PACKAGE_ROOT ?? '',
);
const normalizeLegacyV133 = args.includes('--normalize-legacy-v133');

if (!packageRoot || !existsSync(join(packageRoot, 'src', 'cli.ts'))) {
  console.error('usage: apply.ts --package-root <gbrain-package-root> [--normalize-legacy-v133]');
  process.exit(2);
}

const pkg = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8')) as { version?: string };
const packageVersion = String(pkg.version ?? 'unknown');

const configMod = await import(pathToFileURL(join(packageRoot, 'src', 'core', 'config.ts')).href);
const engineFactory = await import(pathToFileURL(join(packageRoot, 'src', 'core', 'engine-factory.ts')).href);

const config = configMod.loadConfig();
if (!config) {
  throw new Error('No GBrain config found. Initialize/configure GBrain before GPT Dive migrations.');
}

const engineConfig = configMod.toEngineConfig(config);
const engine = await engineFactory.createEngine(engineConfig);
await engine.connect(engineConfig);

const hasColumn = async (table: string, column: string): Promise<boolean> => {
  const rows = await engine.executeRaw<{ present: number }>(
    `SELECT 1 AS present FROM information_schema.columns WHERE table_name = $1 AND column_name = $2 LIMIT 1`,
    [table, column],
  );
  return rows.length > 0;
};

const hasConstraint = async (table: string, constraint: string): Promise<boolean> => {
  const rows = await engine.executeRaw<{ present: number }>(
    `SELECT 1 AS present FROM information_schema.table_constraints WHERE table_name = $1 AND constraint_name = $2 LIMIT 1`,
    [table, constraint],
  );
  return rows.length > 0;
};

let normalizedLegacyV133 = false;
let addedChunkHashes = false;

try {
  let officialVersion = String((await engine.getConfig('version')) ?? '');

  if (normalizeLegacyV133 && officialVersion === '133') {
    if (packageVersion !== '0.46.24.0') {
      throw new Error(
        `Refusing legacy v133 normalization on GBrain ${packageVersion}; this one-time repair is valid only for 0.46.24.0.`,
      );
    }

    const chunkHashesPresent = await hasColumn('eval_candidates', 'retrieved_chunk_hashes');
    const checkpointManifestPresent = await hasColumn('session_context_state', 'checkpoint_manifest');
    const staleV131ConstraintPresent = await hasConstraint(
      'subagent_tool_executions',
      'uniq_subagent_tools_use_id',
    );

    if (!chunkHashesPresent || !checkpointManifestPresent || staleV131ConstraintPresent) {
      throw new Error(
        'Refusing legacy v133 normalization: schema evidence does not prove upstream v131/v132 plus the old local v133 are all present.',
      );
    }

    await engine.executeRaw(`UPDATE config SET value = '132' WHERE key = 'version'`);
    officialVersion = String((await engine.getConfig('version')) ?? '');
    if (officialVersion !== '132') {
      throw new Error(`Legacy v133 normalization failed: expected official schema version 132, got ${officialVersion}.`);
    }
    normalizedLegacyV133 = true;
  }

  officialVersion = String((await engine.getConfig('version')) ?? '');
  const officialVersionNumber = Number.parseInt(officialVersion, 10);
  if (!Number.isFinite(officialVersionNumber) || officialVersionNumber < 132) {
    throw new Error(
      `Official GBrain schema is not ready for GPT Dive extensions: version=${officialVersion || '<missing>'}. Run official migrations first.`,
    );
  }

  if (!(await hasColumn('eval_candidates', 'retrieved_chunk_hashes'))) {
    await engine.executeRaw(
      `ALTER TABLE eval_candidates ADD COLUMN IF NOT EXISTS retrieved_chunk_hashes TEXT[] NOT NULL DEFAULT '{}'`,
    );
    addedChunkHashes = true;
  }

  if (!(await hasColumn('eval_candidates', 'retrieved_chunk_hashes'))) {
    throw new Error('GPT Dive migration 001 verification failed: retrieved_chunk_hashes is still missing.');
  }

  const ledgerDir = join(configMod.configDir(), 'gpt-dive');
  const ledgerPath = join(ledgerDir, 'migrations.jsonl');
  mkdirSync(ledgerDir, { recursive: true, mode: 0o700 });

  const migrationId = '001-eval-candidate-chunk-hashes';
  let alreadyRecorded = false;
  if (existsSync(ledgerPath)) {
    for (const line of readFileSync(ledgerPath, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      try {
        const row = JSON.parse(line) as { id?: string; status?: string };
        if (row.id === migrationId && row.status === 'complete') {
          alreadyRecorded = true;
          break;
        }
      } catch {
        // Preserve an operator-owned ledger even if an older unrelated line is malformed.
      }
    }
  }

  const finalOfficialVersion = String((await engine.getConfig('version')) ?? '');
  if (!alreadyRecorded) {
    appendFileSync(
      ledgerPath,
      JSON.stringify({
        id: migrationId,
        status: 'complete',
        at: new Date().toISOString(),
        gbrain_package_version: packageVersion,
        official_schema_version: finalOfficialVersion,
        changed: addedChunkHashes,
        normalized_legacy_v133: normalizedLegacyV133,
      }) + '\n',
      { encoding: 'utf8', mode: 0o600 },
    );
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        migration: migrationId,
        gbrain_package_version: packageVersion,
        official_schema_version: finalOfficialVersion,
        changed: addedChunkHashes,
        normalized_legacy_v133: normalizedLegacyV133,
        ledger: ledgerPath,
      },
      null,
      2,
    ),
  );
} finally {
  await engine.disconnect();
}
