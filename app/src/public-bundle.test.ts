// Node の型定義を入れずに、ビルド成果物だけを検査するため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { build } from 'vite';
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
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
}, 60_000);
