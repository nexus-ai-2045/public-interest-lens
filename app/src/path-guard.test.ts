import { describe, expect, it as test } from 'vitest';

const it = (name: string, run: () => Promise<void>) => test(name, run, 30_000);
const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path';
const { mkdtemp, mkdir, readdir, readFile, realpath, rm, symlink } = await import(/* @vite-ignore */ fsModule);
const { tmpdir } = await import(/* @vite-ignore */ osModule);
const { join } = await import(/* @vite-ignore */ pathModule);

const guard = await import(/* @vite-ignore */ new URL('../../scripts/path_guard.mjs', import.meta.url).href);
const pipeline = await import(/* @vite-ignore */ new URL('../../scripts/evidence_pipeline.mjs', import.meta.url).href);
const scriptsDir = new URL('../../scripts/', import.meta.url);

const input = () => ({ materialRefs: [], evidenceEvaluation: { schemaVersion: 'evidence-evaluation/v1', mode: 'test-only',
  options: { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-10-01', weights: { economy: 70, technology: 30 } },
  people: [], materials: [], actions: [], assessments: [] } });
const evaluated = { mode: 'test-only', rows: [], held: [], coverage: { inputActions: 0, assessedActions: 0, readableMaterials: 0 }, publicationStatus: 'requires_human_review' };

async function aliasedRoot() {
  const real = await mkdtemp(join(tmpdir(), 'path-guard-real-'));
  const holder = await mkdtemp(join(tmpdir(), 'path-guard-alias-'));
  const alias = join(holder, 'repo');
  await symlink(real, alias, 'junction');
  return { real, alias, cleanup: async () => { await rm(holder, { recursive: true, force: true }); await rm(real, { recursive: true, force: true }); } };
}

describe('OSごとのパス表記の差を吸収する', () => {
  it('別名経由の未作成パスも実体パスへそろえます', async () => {
    const { real, alias, cleanup } = await aliasedRoot();
    try {
      expect(await guard.canonicalPath(join(alias, '.local', 'new', 'dir'))).toBe(join(await realpath(real), '.local', 'new', 'dir'));
      expect(await guard.isInsideCanonical(real, join(alias, '.local', 'x'))).toBe(true);
      expect(await guard.isInsideCanonical(alias, join(real, '.local', 'x'))).toBe(true);
      expect(await guard.isInsideCanonical(alias, join(real, '..', 'other'))).toBe(false);
    } finally { await cleanup(); }
  });

  for (const [label, pick] of [
    ['repoRootが別名で出力先が実体', (r: { real: string; alias: string }) => ({ repoRoot: r.alias, outputBase: r.real })],
    ['repoRootが実体で出力先が別名', (r: { real: string; alias: string }) => ({ repoRoot: r.real, outputBase: r.alias })],
  ] as const) {
    it(`${label}でも.local配下への保存を受け付けます（macOSの/var→/private/varと同じ状況）`, async () => {
      const roots = await aliasedRoot();
      try {
        const { repoRoot, outputBase } = pick(roots);
        const release = await pipeline.runEvidencePipeline(input(), { repoRoot, outputDir: join(outputBase, '.local', 'release'), engineHash: 'a'.repeat(64), evaluate: async () => evaluated });
        expect(release.releaseId).toMatch(/^[a-f0-9]{64}$/);
      } finally { await roots.cleanup(); }
    });
  }

  it('別名をそろえても.local内のリンク経由の保存は拒否します', async () => {
    const { real, alias, cleanup } = await aliasedRoot();
    try {
      await mkdir(join(real, '.local', 'target'), { recursive: true });
      await symlink(join(real, '.local', 'target'), join(real, '.local', 'link'), 'junction');
      await expect(pipeline.runEvidencePipeline(input(), { repoRoot: alias, outputDir: join(alias, '.local', 'link', 'release'), engineHash: 'a'.repeat(64), evaluate: async () => evaluated })).rejects.toThrow('リンク経由の保存は禁止です');
    } finally { await cleanup(); }
  });

  it('パスの包含判定はscripts/path_guard.mjsだけに置きます', async () => {
    const offenders: string[] = [];
    for (const name of await readdir(scriptsDir)) {
      if (!/\.(mjs|js|ts)$/.test(name) || name === 'path_guard.mjs') continue;
      const text = await readFile(new URL(name, scriptsDir), 'utf8');
      if (/rel\s*!==?\s*['"]\.\.['"]|startsWith\(\s*`\.\.\$\{|startsWith\(\s*['"]\.\.[\\/]/.test(text) || /\bisAbsolute\b/.test(text)) offenders.push(name);
    }
    expect(offenders).toEqual([]);
  });
});
