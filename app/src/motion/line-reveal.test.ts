import { describe, expect, it } from 'vitest';
import { indexSeries, pickLabels, spreadLabels } from './LineReveal';

describe('終端ラベルと基準年', () => {
  it('近いラベルを最小の間隔で離し、元の順を保つ', () => {
    const placed = spreadLabels([100, 102, 300], 16, 0, 400);
    expect(placed[1] - placed[0]).toBeGreaterThanOrEqual(16);
    expect(placed[2]).toBe(300);
  });
  it('下にはみ出すときは上へ詰める', () => {
    const placed = spreadLabels([395, 396, 397], 16, 0, 400);
    expect(Math.max(...placed)).toBeLessThanOrEqual(400);
    expect(placed[1] - placed[0]).toBeGreaterThanOrEqual(16);
  });
  it('必ず出す名前を残し、ほかは重ならないものだけ値の大きい順に出す', () => {
    // y が小さいほど上（値が大きい）。2 番目は日本（必ず出す）、3・4 番目は日本と近すぎる。
    const chosen = pickLabels([{ y: 10 }, { y: 200, force: true }, { y: 205 }, { y: 195 }, { y: 240 }], 16);
    expect(chosen).toEqual([true, true, false, false, true]);
  });
  it('基準年を100にし、基準年の値が無い系列は0で埋めずに外す', () => {
    const result = indexSeries([
      { id: 'jp', label: '日本', points: [{ year: 2000, value: 50 }, { year: 2001, value: 75 }, { year: 2002, value: null }] },
      { id: 'xx', label: '欠け', points: [{ year: 2000, value: null }, { year: 2001, value: 10 }] },
    ], 2000);
    expect(result).toHaveLength(1);
    expect(result[0].points.map(point => point.value)).toEqual([100, 150, null]);
  });
});
