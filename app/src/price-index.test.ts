// Node の型定義を入れずに公開ファイルを読むため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parsePriceIndex, toLatestYen, windowBaseYear } from './price-index';

const committed = parsePriceIndex(JSON.parse(readFileSync(new URL('../public/distribution/price-index.json', import.meta.url), 'utf8')));

describe('物価の換算（price-v1）', () => {
  it('窓の開始前の年を額の円の年にする', () => {
    expect(windowBaseYear('2005〜2014年')).toBe(2004);
    expect(windowBaseYear(undefined)).toBeNull();
  });
  it('b 年の円に P_T / P_b を掛ける', () => {
    const index = parsePriceIndex({ schema: 'price-index/v1', latestYear: 2024, sourceUrl: 'u', deflator: { '2004': 100, '2024': 110 } });
    expect(toLatestYen(1_000, 2004, index)).toBe(1_100);
    expect(toLatestYen(1_000, 1980, index)).toBeNull();
  });
  it('公開の表は2020年＝100で、最新年がある', () => {
    expect(committed.deflator['2020']).toBe(100);
    expect(committed.deflator[String(committed.latestYear)]).toBeGreaterThan(0);
  });
  it('形の違う表は読まない', () => {
    expect(() => parsePriceIndex({ schema: 'x' })).toThrow();
  });
});
