/**
 * 曝露ランキング集計の性質テスト（境界・乱数・反例）。
 * 依存に fast-check は無いので、固定種の LCG で網羅する。
 * 反例 C1 は直さず it.fails で残す（docs/reports/評価エンジン_不変条件と性質テスト_2026-11-20.md）。
 * C1 の根本直しは別 PR。その PR が it.fails を通常の試験に変える。
 */
import { beforeAll, describe, expect, it } from 'vitest';
import {
  DEFAULT_ROLE_RATIO,
  assignTiers,
  buildExposureRanking,
  type ExposureGroup,
  type ExposureRanking,
  type Involvement,
  type Range,
} from './exposure-ranking';

const yen = (median: number, spread = 0): Range => ({ low: median - spread, median, high: median + spread });
const group = (id: string, median: number, spread = 0, lawCount = 1): ExposureGroup =>
  ({ kind: 'group-diff', id, group: id, window: '2000〜2005年', diff: yen(median, spread), benchmark: '性質テスト', lawCount });
const inv = (
  actorId: string,
  lawId: string,
  role: Involvement['role'],
  weight = 1,
  groupId = 'g1',
  actorKind: Involvement['actorKind'] = 'person',
  house?: Involvement['house'],
): Involvement =>
  ({
    actorKind,
    actorId,
    groupId,
    lawId,
    role,
    weight,
    ...(role === 'yes' || role === 'no' ? { house: house ?? 'upper' } : {}),
  });

const P = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 1 };
const close = (a: Range, b: Range) => {
  for (const k of ['low', 'median', 'high'] as const) expect(a[k]).toBeCloseTo(b[k], 6);
};
const conserved = (out: ExposureRanking) => close(
  {
    low: out.totals.people.low + out.totals.parties.low + out.totals.unallocated.low,
    median: out.totals.people.median + out.totals.parties.median + out.totals.unallocated.median,
    high: out.totals.people.high + out.totals.parties.high + out.totals.unallocated.high,
  },
  out.totals.expected,
);
const actorKey = (o: ExposureRanking) =>
  o.people.concat(o.parties)
    .map(p => [p.actorKind, p.actorId, p.tier, p.laws, p.exposureYen.median.toFixed(9)].join(':'))
    .sort()
    .join('|');
const amountKey = (o: ExposureRanking) =>
  o.people.concat(o.parties)
    .map(p => [p.actorKind, p.actorId, p.exposureYen.median.toFixed(6)].join(':'))
    .sort()
    .join('|');

function lcg(seed: number) {
  let s = (Math.imul(seed, 1103515245) + 12345) >>> 0;
  return () => {
    s = (Math.imul(s, 1103515245) + 12345) >>> 0;
    return s / 0x100000000;
  };
}

/** 有効入力だけを返す。lawCount を記録本数未満にしない。例外を握りつぶすための逃げ道は持たない。 */
function randomCase(seed: number): { groups: ExposureGroup[]; invs: Involvement[] } {
  const rnd = lcg(seed);
  const roles: Involvement['role'][] = ['proposer', 'yes', 'no', 'cabinet'];
  const kinds: Involvement['actorKind'][] = ['person', 'party'];
  const nGroups = 1 + Math.floor(rnd() * 3);
  const groups: ExposureGroup[] = [];
  for (let i = 0; i < nGroups; i++) {
    groups.push(group(`g${i}`, Math.floor((rnd() - 0.5) * 2000), Math.floor(rnd() * 200), 1 + Math.floor(rnd() * 5)));
  }
  const invs: Involvement[] = [];
  const nInvs = Math.floor(rnd() * 12);
  for (let i = 0; i < nInvs; i++) {
    const g = groups[Math.floor(rnd() * groups.length)];
    const role = roles[Math.floor(rnd() * roles.length)];
    const kind = rnd() < 0.1 ? 'none' : kinds[Math.floor(rnd() * kinds.length)];
    const lawId = `L${g.id}-${Math.floor(rnd() * g.lawCount)}`;
    const actorId = kind === 'none' ? '' : `A${Math.floor(rnd() * 4)}`;
    invs.push(inv(actorId, lawId, role, 0.1 + rnd() * 5, g.id, kind, rnd() < 0.5 ? 'lower' : 'upper'));
  }
  const byG = new Map<string, Set<string>>();
  for (const x of invs) {
    if (!byG.has(x.groupId)) byG.set(x.groupId, new Set());
    byG.get(x.groupId)!.add(x.lawId);
  }
  const fixed = groups.map(g => {
    const need = byG.get(g.id)?.size ?? 0;
    return need > g.lawCount ? { ...g, lawCount: need } : g;
  });
  return { groups: fixed, invs };
}

/** 失敗時に種を報告する。例外は握りつぶさず再送出する。 */
function withSeed<T>(seed: number, run: () => T): T {
  try {
    return run();
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    throw new Error(`種 ${seed} で失敗: ${detail}`, { cause: e });
  }
}

describe('曝露ランキングの性質（I1・I4・I5・境界）', () => {
  it('乱数800種：合計の保存・決定論・幅の順序・期待値の式', () => {
    for (let seed = 0; seed < 800; seed++) {
      withSeed(seed, () => {
        const { groups, invs } = randomCase(seed);
        const out = buildExposureRanking(groups, invs, P);
        conserved(out);
        const again = buildExposureRanking(groups, invs, P);
        expect(JSON.stringify(again)).toBe(JSON.stringify(out));
        for (const row of out.people.concat(out.parties)) {
          expect(row.exposureYen.low).toBeLessThanOrEqual(row.exposureYen.median + 1e-9);
          expect(row.exposureYen.median).toBeLessThanOrEqual(row.exposureYen.high + 1e-9);
        }
        const signed = 0.4 + 0.2 - 0.2 + 0.2;
        const want = groups.reduce((s, g) => s + g.diff.median * signed, 0);
        expect(out.totals.expected.median).toBeCloseTo(want, 6);
      });
    }
  });

  it('乱数800種：額（中央値を丸めた鍵）は入力順に依らない', () => {
    for (let seed = 0; seed < 800; seed++) {
      withSeed(seed, () => {
        const { groups, invs } = randomCase(seed);
        const a = buildExposureRanking(groups, invs, P);
        const b = buildExposureRanking([...groups].reverse(), [...invs].reverse(), P);
        expect(amountKey(b)).toBe(amountKey(a));
        conserved(b);
      });
    }
  });

  it('境界：法律1本・重み1・片院のみでも合計が保存される', () => {
    const out = buildExposureRanking(
      [group('g1', 1000, 50, 1)],
      [inv('甲', 'L1', 'proposer'), inv('乙', 'L1', 'yes', 1, 'g1', 'person', 'upper')],
      P,
    );
    conserved(out);
    expect(out.unallocated.some(u => u.role === 'yes' && u.house === 'lower')).toBe(true);
  });

  it('境界：lawCount が記録より多く、全役割が未配分に残る分でも合計が合う', () => {
    const out = buildExposureRanking(
      [group('g1', -500, 20, 5)],
      [inv('甲', 'L1', 'cabinet')],
      P,
    );
    conserved(out);
    expect(out.unallocated.some(u => u.role === null && u.laws === 4)).toBe(true);
  });
});

describe('見つかった反例 C1（階層の入力順依存・未修正）', () => {
  /**
   * なぜ壊れるか：関与の加算順が入力順に依存し、浮動小数点の非結合性で中央値が 1e-14 ずれ、
   * 同点付近の先頭が入れ替わると階層の leaderLow が変わり、後続の tier が変わる。
   */
  const groups = [group('g0', -782, 78, 4)];
  const invs: Involvement[] = [
    inv('A1', 'Lg0-1', 'proposer', 1.5648735523223878, 'g0', 'party'),
    inv('A0', 'Lg0-1', 'cabinet', 1.8701256275177003, 'g0', 'party'),
    inv('A0', 'Lg0-0', 'no', 1.6123414993286134, 'g0', 'party', 'upper'),
    inv('A1', 'Lg0-2', 'no', 1.6470302104949952, 'g0', 'person', 'upper'),
    inv('A0', 'Lg0-1', 'yes', 2.1779597759246827, 'g0', 'party', 'lower'),
    inv('A0', 'Lg0-3', 'cabinet', 1.4447260856628419, 'g0', 'party'),
    inv('A1', 'Lg0-1', 'yes', 3.3798075675964356, 'g0', 'person', 'upper'),
    inv('A1', 'Lg0-0', 'no', 4.669137096405029, 'g0', 'person', 'lower'),
    inv('A2', 'Lg0-3', 'proposer', 2.0938242435455323, 'g0', 'party'),
    inv('A1', 'Lg0-3', 'yes', 0.12505898475646973, 'g0', 'party', 'lower'),
  ];

  let forward: ExposureRanking;
  let reversed: ExposureRanking;

  // 集計の例外は it.fails の「期待失敗」に数えない。ここで投げれば通常の失敗になる。
  beforeAll(() => {
    forward = buildExposureRanking(groups, invs, P);
    reversed = buildExposureRanking([...groups].reverse(), [...invs].reverse(), P);
  });

  it('額の合計は順でも逆でも保存される（I1は維持）', () => {
    conserved(forward);
    conserved(reversed);
    expect(amountKey(forward)).toBe(amountKey(reversed));
  });

  it('原因：中央値が 1e-14 ずれて先頭が変わると、leaderLow の差で後続の tier が入れ替わる', () => {
    // C1 で観測した幅そのもの。assignTiers に渡すと tier が変わる（症状ではなく階層規則への入力差）
    const ledByA2 = assignTiers([
      { actorId: 'A2', exposureYen: { low: -86, median: -78.2, high: -70.4 } },
      { actorId: 'A0', exposureYen: { low: -89.9, median: -78.20000000000002, high: -66.5 } },
      { actorId: 'A1', exposureYen: { low: -107.5, median: -97.75, high: -88 } },
    ]);
    const ledByA0 = assignTiers([
      { actorId: 'A0', exposureYen: { low: -89.9, median: -78.2, high: -66.5 } },
      { actorId: 'A2', exposureYen: { low: -86, median: -78.2, high: -70.4 } },
      { actorId: 'A1', exposureYen: { low: -107.5, median: -97.75, high: -88 } },
    ]);
    expect(ledByA2.find(r => r.actorId === 'A1')!.tier).toBe(2);
    expect(ledByA0.find(r => r.actorId === 'A1')!.tier).toBe(1);
  });

  // 意図する不変条件 I5：パイプライン全体で tier を含む鍵も一致すべき。現状は一致しない。
  // it.fails の中では階層鍵の不一致だけを見る（計算例外は beforeAll 側で通常失敗にする）。
  it.fails('階層（tier）も入力順に依らない（C1：直すまで fails のまま残す）', () => {
    expect(actorKey(reversed)).toBe(actorKey(forward));
  });
});
