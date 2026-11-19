// @ts-nocheck
// @vitest-environment node
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { SPEC_VERSION } from './method-spec';
import { validGenerationMetadata } from './generation-metadata';
import { generationMetadata } from '../../scripts/generation_provenance.mjs';
import { parsePublicExposureRanking } from './public-distribution';

const good = () => ({ methodSpecVersion: SPEC_VERSION, codeHashes: {
  'app/src/method-spec.ts': 'a'.repeat(64), 'app/src/exposure-ranking.ts': 'b'.repeat(64),
} });

describe('生成方法とソースの来歴', () => {
  it('曝露ランキングは実際に解決した全依存ソースと一致する', async () => {
    const root = join(process.cwd(), '..');
    const { createServer } = await import('vite');
    const server = await createServer({ root: join(root, 'app'), logLevel: 'silent', server: { middlewareMode: true, hmr: false }, appType: 'custom' });
    try {
      const entries = ['app/src/exposure-inputs.ts', 'app/src/exposure-ranking.ts', 'app/src/scoring-constants.ts', 'app/src/exposure-labels.ts'];
      for (const entry of entries) await server.ssrLoadModule('/' + entry.replace('app/', ''));
      const expected = await generationMetadata(server, root, entries, ['scripts/build_exposure_ranking.mjs']);
      const actual = JSON.parse(readFileSync(join(root, 'data/derived/exposure-v1/exposure-ranking.json'), 'utf8'));
      expect(actual.generatedFrom).toEqual(expected);
    } finally { await server.close(); }
  }, 60_000);

  it('曝露ランキングでは旧形式・未記録・未知の方法・伏せ方の破れを受け入れない', () => {
    const metadata = good();
    for (const name of ['app/src/exposure-inputs.ts', 'app/src/scoring-constants.ts', 'app/src/exposure-labels.ts', 'scripts/build_exposure_ranking.mjs', 'scripts/generation_provenance.mjs', 'scripts/path_guard.mjs', 'app/package-lock.json']) metadata.codeHashes[name] = 'c'.repeat(64);
    const payload = { schema: 'exposure-ranking/v1', claim: 'descriptive', people: [{ actorId: '甲', tier: null, exposureYen: null }], parties: [], unallocated: [], generatedFrom: metadata,
      groups: [{ id: 'A|1998', group: 'A', window: '1998年' }], personReadings: { 甲: 'こう' } };
    expect(parsePublicExposureRanking(JSON.stringify(payload)).people).toHaveLength(1);
    for (const delta of [{ schema: 'public-members/v3' }, { claim: 'causal' }, { generatedFrom: undefined },
      { generatedFrom: { ...metadata, methodSpecVersion: 'method-spec-v999.0' } },
      { people: [{ actorId: '甲', tier: null, exposureYen: { low: 1, median: 1, high: 1 } }] }, { people: [{ actorId: '甲', tier: 1, exposureYen: null }] },
      // 群と読みが無い古い形、読みがひらがなでない・空白入り・台帳にいない人の読み
      { groups: undefined }, { personReadings: undefined }, { personReadings: { 甲: 'コウ' } }, { personReadings: { 甲: 'こ う' } }, { personReadings: { 乙: 'おつ' } }]) {
      expect(() => parsePublicExposureRanking(JSON.stringify({ ...payload, ...delta }))).toThrow();
    }
  });

  it('未記録・未知の方法版・壊れたhash・端末のパスを拒否する', () => {
    expect(validGenerationMetadata(good(), ['app/src/exposure-ranking.ts'])).toBe(true);
    for (const value of [null, {}, { ...good(), methodSpecVersion: 'method-spec-v999.0' },
      { ...good(), codeHashes: {} }, { ...good(), codeHashes: { 'app/src/method-spec.ts': ['a'.repeat(64)] } },
      { ...good(), codeHashes: { ...good().codeHashes, '../private.py': 'c'.repeat(64) } }]) {
      expect(validGenerationMetadata(value)).toBe(false);
    }
    expect(validGenerationMetadata(good(), ['scripts/missing.py'])).toBe(false);
  });

  it('実依存の変更を追跡し、READMEや別コミットには依存しない', async () => {
    const root = mkdtempSync(join(tmpdir(), 'generation-'));
    try {
      for (const [file, text] of Object.entries({ 'app/src/method-spec.ts': 'spec', 'app/src/entry.ts': 'entry',
        'app/src/child.ts': 'child', 'scripts/generation_provenance.mjs': 'helper', 'scripts/path_guard.mjs': 'guard', 'app/package-lock.json': '{}' })) {
        mkdirSync(join(root, file, '..'), { recursive: true }); writeFileSync(join(root, file), text);
      }
      const child = { file: join(root, 'app/src/child.ts'), importedModules: new Set() };
      const entry = { file: join(root, 'app/src/entry.ts'), importedModules: new Set([child]) };
      const spec = { file: join(root, 'app/src/method-spec.ts'), importedModules: new Set() };
      const nodes = new Map([[entry.file, entry], [spec.file, spec]]);
      const server = { ssrLoadModule: async () => ({ SPEC_VERSION }), environments: { ssr: { moduleGraph: { getModuleById: path => nodes.get(path) } } } };
      const before = await generationMetadata(server, root, ['app/src/entry.ts']);
      writeFileSync(join(root, 'README.md'), 'unrelated');
      expect(await generationMetadata(server, root, ['app/src/entry.ts'])).toEqual(before);
      writeFileSync(child.file, 'changed child');
      expect((await generationMetadata(server, root, ['app/src/entry.ts'])).codeHashes['app/src/child.ts']).not.toBe(before.codeHashes['app/src/child.ts']);
      await expect(generationMetadata(server, root, ['app/src/missing.ts'])).rejects.toThrow();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
});
