import { describe, expect, it } from 'vitest';
import { allocateLaw, DEFAULT_KNOBS, gameShares, knobShares, quota, readKnobs, vetoShare, writeKnobs } from './causal-allocation';

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

/** 二項係数。検定用で、実装の積の形とは別の式。 */
function binom(n: number, r: number): bigint {
  if (r < 0 || r > n) return 0n;
  r = Math.min(r, n - r);
  let c = 1n;
  for (let i = 1; i <= r; i++) c = c * BigInt(n - r + i) / BigInt(i);
  return c;
}

function gcd(a: bigint, b: bigint): bigint {
  while (b !== 0n) { const t = a % b; a = b; b = t; }
  return a;
}

/** φ = (1/n) Σ C(Y, j) / C(n−1, j+k−1) を約分した整数比にする。 */
function binomialRatio(k: number, Y: number, q: number): { num: bigint; den: bigint } {
  const n = k + Y;
  let num = 0n;
  let den = 1n;
  for (let j = Math.max(q, 0); j <= Y; j++) {
    const a = binom(Y, j);
    const b = binom(n - 1, j + k - 1) * BigInt(n);
    const g = gcd(b, den);
    const b2 = b / g;
    const d2 = den / g;
    num = num * b2 + a * d2;
    den *= b2;
    const g2 = gcd(num, den);
    num /= g2;
    den /= g2;
  }
  return { num, den };
}

function floatRatio(value: number): { num: bigint; den: bigint } {
  const buf = new ArrayBuffer(8);
  const view = new DataView(buf);
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  const biased = Number((bits >> 52n) & 0x7ffn);
  const frac = bits & ((1n << 52n) - 1n);
  if (biased === 0) return { num: frac, den: 1n << 1074n };
  const mant = frac | (1n << 52n);
  const exp = biased - 1075;
  return exp >= 0 ? { num: mant << BigInt(exp), den: 1n } : { num: mant, den: 1n << BigInt(-exp) };
}

/** value が target 以上に近いか。距離は整数比のまま比べる。 */
function atLeastAsClose(value: number, other: number, target: { num: bigint; den: bigint }): boolean {
  const gap = (x: number) => {
    const f = floatRatio(x);
    const left = f.num * target.den;
    const right = target.num * f.den;
    return { diff: left > right ? left - right : right - left, den: f.den };
  };
  const a = gap(value);
  const b = gap(other);
  return a.diff * b.den <= b.diff * a.den;
}

function isNearestFloat(value: number, target: { num: bigint; den: bigint }): boolean {
  const buf = new ArrayBuffer(8);
  const view = new DataView(buf);
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  view.setBigUint64(0, bits - 1n);
  const prev = view.getFloat64(0);
  view.setBigUint64(0, bits + 1n);
  const next = view.getFloat64(0);
  return atLeastAsClose(value, prev, target) && atLeastAsClose(value, next, target);
}

describe('成立への寄与（Shapley 値）', () => {
  it('小さいゲームで総当たりと一致する', () => {
    for (const [k, Y, q] of [[1, 3, 2], [2, 3, 2], [2, 4, 3], [3, 3, 1]]) expect(vetoShare(k, Y, q)).toBe(bruteVeto(k, Y, q));
  });

  it('実際の票数での値', () => {
    expect(vetoShare(2, 214, quota(214, 16))).toBeCloseTo(0.3539, 3);
    expect(vetoShare(2, 155, quota(155, 73))).toBeCloseTo(0.2277, 3);
    expect(vetoShare(3, 214, quota(214, 16))).toBeCloseTo(0.2804, 3);
  });

  it('割合は二項係数の整数比に最も近い float で、同じ呼び出しは同じビットになる', () => {
    // 閣法-193-59（賛成212・反対22・可決118）と、票数・拒否権者数が隣のもの。CI ではここの最終ビットだけが OS で割れた。
    const cases = [[2, 212, 118], [2, 211, 118], [2, 213, 118], [2, 212, 117], [2, 212, 119], [3, 212, 118], [4, 212, 118], [4, 199, 117], [2, 214, quota(214, 16)], [2, 155, quota(155, 73)], [3, 214, quota(214, 16)]];
    for (const [k, Y, q] of cases) {
      const share = vetoShare(k, Y, q);
      expect(share).toBe(vetoShare(k, Y, q));
      expect(isNearestFloat(share, binomialRatio(k, Y, q))).toBe(true);
    }
    const reproduced = vetoShare(2, 212, quota(212, 22));
    // darwin の再計算と ubuntu の再計算は 1 ULP 違いだった。公開値はそのどちらでもなく、整数比の最近傍。
    expect(reproduced).not.toBe(0.34596990039928005);
    expect(reproduced).not.toBe(0.3459699003992801);
    expect(JSON.stringify(reproduced)).toBe('0.34596990039928044');
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

describe('見え方のつまみ', () => {
  const game = { proposers: ['甲', '乙'], voters: ['乙', '丙', '丁'], chairs: ['戊'], yes: 5, no: 3 };
  const sum = (r: ReturnType<typeof knobShares>) => [...r.persons.values()].flatMap(x => Object.values(x)).reduce((a, b) => a + (b ?? 0), 0) + r.party + r.unidentified + r.unattributed;
  it('初期値は基準の Shapley 値と同じ', () => {
    const base = gameShares(game, 'base');
    const k = knobShares(game, DEFAULT_KNOBS);
    expect(k.persons.get('甲')!.proposer).toBeCloseTo(base.persons.get('甲')!.proposer!, 12);
    expect(k.party).toBeCloseTo(base.party, 12);
  });
  it('どの値でも合計は1（額を超えない）', () => {
    for (const proposer of [0, 0.3, 1]) for (const party of ['party', 'voters'] as const) for (const chairVeto of [false, true]) for (const rate of [0.1, 0.5, 1]) {
      expect(sum(knobShares(game, { proposer, party, chairVeto, rate, office: false }))).toBeCloseTo(1, 12);
    }
  });
  it('提出者の重みを下げると提出者は減り、賛成票は増える', () => {
    const k = knobShares(game, { ...DEFAULT_KNOBS, proposer: 0.5 });
    expect(k.persons.get('甲')!.proposer).toBeCloseTo(gameShares(game, 'base').persons.get('甲')!.proposer! / 2, 12);
    expect(k.persons.get('丙')!.vote!).toBeGreaterThan(gameShares(game, 'base').vote);
  });
  it('URL に入れて読み戻せる', () => {
    const k = { proposer: 0.4, party: 'voters' as const, chairVeto: true, rate: 0.5, office: true };
    expect(readKnobs(writeKnobs(new URLSearchParams('name=x'), k))).toEqual(k);
    expect(writeKnobs(new URLSearchParams('name=x'), DEFAULT_KNOBS).toString()).toBe('name=x');
  });
});
