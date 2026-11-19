import { describe, expect, it } from 'vitest';
import { SCORING_CONSTANTS, meetsCertaintyFloor } from './scoring-constants';
import { makeLawEffect, type GroupDiff, type LawEffect } from './scoring-types';

const raw = import.meta.glob('./scoring-*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const source = (name: string) => raw[`./${name}`].replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');

/** 点数設計 v2.1 §2（固定つまみ）と §6（性質テスト）。 */
describe('v2.1 の固定定数', () => {
  it('値は設計確定 v2.1 §2 のとおり', () => {
    expect(SCORING_CONSTANTS).toEqual({ hitRateFloor: 0.8, minContributingLaws: 5, topThreeShareCap: 0.5, certaintyFloor: '中' });
  });
  it('確かさは中以上だけ通る（低・参考は通らない）', () => {
    expect(['高', '中', '低', '参考', ''].map(meetsCertaintyFloor)).toEqual([true, true, false, false, false]);
  });
  it('設定から変更できない：凍結されていて、書き換えは失敗する', () => {
    expect(Object.isFrozen(SCORING_CONSTANTS)).toBe(true);
    expect(() => { (SCORING_CONSTANTS as { hitRateFloor: number }).hitRateFloor = 0.95; }).toThrow();
    expect(SCORING_CONSTANTS.hitRateFloor).toBe(0.8);
  });
  it('設定・環境変数・URL・保存領域を読まない（定数ファイルは自己完結）', () => {
    const src = source('scoring-constants.ts');
    expect(src).not.toMatch(/process\.env|import\.meta\.env|localStorage|sessionStorage|location\.|fetch\(|require\(|\bimport\s/);
  });
  it('定数ファイルは1つだけ：ほかのソースに同じ固定値を直書きしない', () => {
    // 的中率の合格線を 0.8 / 0.95 と直書きした定数を新しく作らない（TARGET は scripts 側で別スレッド）。
    const src = source('scoring-types.ts');
    expect(src).not.toMatch(/\b0\.8\b|\b0\.5\b|minContributingLaws\s*[:=]\s*\d/);
  });
});

describe('v2.1 の型：群の差は法律へ配れない', () => {
  const group: GroupDiff = { kind: 'group-diff', group: '産業X', window: '2000〜2009年', diff: { low: -3, median: -2, high: -1 }, benchmark: 'OECD同産業・同時期の中央値' };
  const evidence = { rung: 'other-country-measured' as const, source: '出典' };
  it('LawEffect は外部証拠が無いと作れない（null）', () => {
    expect(makeLawEffect({ lawId: '閣法-1-1', amountYen: { low: 1, median: 2, high: 3 }, certainty: '高', evidence: undefined })).toBeNull();
    expect(makeLawEffect({ lawId: '閣法-1-1', amountYen: { low: 1, median: 2, high: 3 }, certainty: '高', evidence: { rung: 'other-country-measured', source: '' } })).toBeNull();
  });
  it('確かさが低・参考の法律も LawEffect にならない', () => {
    expect(makeLawEffect({ lawId: 'x', amountYen: { low: 1, median: 2, high: 3 }, certainty: '低', evidence })).toBeNull();
    expect(makeLawEffect({ lawId: 'x', amountYen: { low: 1, median: 2, high: 3 }, certainty: '参考', evidence })).toBeNull();
  });
  it('証拠と確かさ中以上がそろえば作れる', () => {
    const e = makeLawEffect({ lawId: 'x', amountYen: { low: 1, median: 2, high: 3 }, certainty: '中', evidence });
    expect(e?.kind).toBe('law-effect');
  });
  it('GroupDiff には法律の額の欄が無く、LawEffect としては受け取られない（型と実行時の両方）', () => {
    // @ts-expect-error GroupDiff は LawEffect に代入できない
    const asLaw: LawEffect = group;
    expect((group as unknown as Record<string, unknown>).amountYen).toBeUndefined();
    expect((group as unknown as Record<string, unknown>).lawId).toBeUndefined();
    expect(asLaw).toBe(group);
  });
  it('型の手書きでも LawEffect は作れない（ブランド）', () => {
    // @ts-expect-error ブランドが無いオブジェクトは LawEffect ではない
    const forged: LawEffect = { kind: 'law-effect', lawId: 'x', amountYen: { low: 1, median: 2, high: 3 }, certainty: '高', evidence };
    expect(forged.kind).toBe('law-effect');
  });
  it('群の差を法律へ配る関数が公開されていない', async () => {
    const mod = await import('./scoring-types');
    expect(Object.keys(mod).sort()).toEqual(['makeLawEffect']);
  });
});
