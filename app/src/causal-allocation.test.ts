import { describe, expect, it } from 'vitest';
import { allocateLaw, gameShares, quota, vetoShare } from './causal-allocation';

/** 並び順をすべて試す Shapley 値（小さいゲームの検算用）。 */
function bruteVeto(k: number, Y: number, q: number): number {
  const players = [...Array(k + Y).keys()];
  const wins = (set: Set<number>) => [...Array(k).keys()].every(i => set.has(i)) && [...set].filter(p => p >= k).length >= q;
  let pivots = 0, orders = 0;
  const perm = (rest: number[], done: number[]) => {
    if (rest.length === 0) {
      orders++;
      const pos = done.indexOf(0);
      const before = new Set(done.slice(0, pos));
      if (!wins(before) && wins(new Set([...before, 0]))) pivots++;
      return;
    }
    rest.forEach((p, i) => perm([...rest.slice(0, i), ...rest.slice(i + 1)], [...done, p]));
  };
  perm(players, []);
  return pivots / orders;
}

describe('成立への寄与（Shapley 値）', () => {
  it('小さいゲームで総当たりと一致する', () => {
    for (const [k, Y, q] of [[1, 3, 2], [2, 3, 2], [2, 4, 3], [3, 3, 1]]) expect(vetoShare(k, Y, q)).toBeCloseTo(bruteVeto(k, Y, q), 10);
  });

  it('実際の票数での値', () => {
    expect(vetoShare(2, 214, quota(214, 16))).toBeCloseTo(0.3539, 3);
    expect(vetoShare(2, 155, quota(155, 73))).toBeCloseTo(0.2277, 3);
    expect(vetoShare(3, 214, quota(214, 16))).toBeCloseTo(0.2804, 3);
  });

  it('割合の合計は1で、額は人・党・名前不明でぴったり分ける', () => {
    const game = { proposers: ['甲', '乙'], voters: ['乙', '丙'], chairs: ['丁'], yes: 3, no: 1 };
    const s = gameShares(game, 'base');
    const total = [...s.persons.values()].flatMap(r => Object.values(r)).reduce((a, b) => a + (b ?? 0), 0) + s.party + s.unidentified;
    expect(total).toBeCloseTo(1, 12);
    expect(s.persons.get('丁')).toBeUndefined();
    const out = allocateLaw({ low: 999, median: 1000, high: 1001 }, game, 'chair_veto');
    expect(out.rows.reduce((a, r) => a + r.share.median, 0) + out.party.median + out.unidentified.median).toBe(1000);
    expect(out.rows.find(r => r.personId === '乙')!.roles).toHaveProperty('vote');
  });
});
