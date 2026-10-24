// Node の型定義を入れずに、正本と清書の一致を確かめるため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { execFileSync } from 'node:child_process';
import katex from 'katex';
import { describe, expect, it } from 'vitest';
import { SPEC_SECTIONS, SPEC_VERSION, STANDARD_METHODS } from './method-spec';

describe('計算方法の仕様（method-spec）', () => {
  it('すべての式と記号が KaTeX でエラーなく描ける', () => {
    for (const s of SPEC_SECTIONS) {
      for (const f of s.formulas) expect(() => katex.renderToString(f.tex, { throwOnError: true, strict: 'error', displayMode: true }), `${s.id}: ${f.tex}`).not.toThrow();
      for (const [sym] of s.symbols) expect(() => katex.renderToString(sym, { throwOnError: true, strict: 'error' }), `${s.id}: ${sym}`).not.toThrow();
    }
  });
  it('部品の id は重ならず、採用の部品には実装のファイルがある', () => {
    expect(new Set(SPEC_SECTIONS.map(s => s.id)).size).toBe(SPEC_SECTIONS.length);
    for (const s of SPEC_SECTIONS.filter(s => s.status === '採用')) expect(s.code.length).toBeGreaterThan(0);
    expect(SPEC_VERSION).toMatch(/^method-spec-v\d+\.\d+$/);
  });
  it('公開データの rules に出ている版は、仕様に採用として載っている', async () => {
    const { readFileSync } = await import('node:fs');
    const read = (name: string) => JSON.parse(readFileSync(new URL(`../public/distribution/${name}`, import.meta.url), 'utf8'));
    const adopted = new Set(SPEC_SECTIONS.filter(s => s.status === '採用').flatMap(s => [s.version, ...(s.alsoVersions ?? [])]));
    const rules = [...read('members.json').rules, ...read('members-reference.json').rules, ...read('ranking.json').generatedFrom.rules] as string[];
    for (const rule of rules) expect(adopted.has(rule), rule).toBe(true);
  });
  it('定番の手法は数を絞り、出典があり、仕様の節を指す', () => {
    expect(STANDARD_METHODS.length).toBeLessThanOrEqual(6);
    const ids = new Set(SPEC_SECTIONS.map(s => s.id));
    for (const m of STANDARD_METHODS) {
      expect(m.refs.length, m.name).toBeGreaterThan(0);
      for (const id of m.sections) expect(ids.has(id), `${m.name}: ${id}`).toBe(true);
    }
  });
  it('docs/計算式.md は正本から作り直されている', () => {
    expect(() => execFileSync('node', ['scripts/build_formula_doc.mjs', '--check'], { cwd: new URL('..', import.meta.url).pathname, stdio: 'pipe' })).not.toThrow();
  });
});
