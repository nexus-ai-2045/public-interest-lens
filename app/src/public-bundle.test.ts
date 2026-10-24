// Node の型定義を入れずに、ビルド成果物だけを検査するため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { build } from 'vite';
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, expect, it } from 'vitest';

const outDir = mkdtempSync(join(tmpdir(), 'pubbundle-'));
afterAll(() => rmSync(outDir, { recursive: true, force: true }));

it('公開版バンドルに端末専用APIとローカルファイル読込の処理が残らない', async () => {
  const previous = process.env.VITE_PUBLIC_SITE;
  process.env.VITE_PUBLIC_SITE = 'true';
  try {
    await build({ root: process.cwd(), logLevel: 'silent', build: { outDir, emptyOutDir: true } });
  } finally {
    if (previous === undefined) delete process.env.VITE_PUBLIC_SITE; else process.env.VITE_PUBLIC_SITE = previous;
  }
  const dir = join(outDir, 'assets');
  const code = readdirSync(dir).filter(name => name.endsWith('.js')).map(name => readFileSync(join(dir, name), 'utf8')).join('\n');
  expect(code.length).toBeGreaterThan(0);
  expect(code).not.toContain('__local__');
  expect(code).not.toContain('ローカル評価データJSONを開く');
  const files = (folder: string): string[] => readdirSync(folder).flatMap(name => statSync(join(folder, name)).isDirectory() ? files(join(folder, name)) : [join(folder, name)]);
  for (const file of files(outDir)) expect(readFileSync(file, 'latin1').includes('private-m2'), file).toBe(false);
  const ranking = JSON.parse(readFileSync(join(outDir, 'distribution', 'ranking.json'), 'utf8'));
  expect(Object.keys(ranking)).not.toContain('people');
  expect(ranking.approval.scope).toBe('all-laws');
  expect(ranking.approval.approvedAt).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(ranking.laws.length + ranking.others.length).toBe(ranking.counts.enacted);
  for (const item of ranking.others) expect(JSON.stringify(item)).not.toMatch(/Yen|中央値|四分位/);
}, 60_000);
