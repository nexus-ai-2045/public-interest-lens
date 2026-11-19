import { describe, expect, it } from 'vitest';
import {
  assignTiers, buildExposureRanking, DEFAULT_ROLE_RATIO, EXPOSURE_DISCLAIMER,
  type ExposureGroup, type ExposureRanking, type Involvement, type Range,
} from './exposure-ranking';

const yen = (median: number, spread = 0): Range => ({ low: median - spread, median, high: median + spread });
const group = (id: string, median: number, spread = 0): ExposureGroup => ({ id, industry: id, period: '2000-2005', shortfallYen: yen(median, spread) });
const inv = (actorId: string, lawId: string, role: Involvement['role'], weight = 1, groupId = 'g1', actorKind: Involvement['actorKind'] = 'person'): Involvement =>
  ({ actorKind, actorId, groupId, lawId, role, weight });
const P = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1 };
const close = (a: Range, b: Range) => { for (const k of ['low', 'median', 'high'] as const) expect(a[k]).toBeCloseTo(b[k], 6); };
const conserved = (out: ExposureRanking) => close(
  { low: out.totals.people.low + out.totals.parties.low + out.totals.unallocated.low,
    median: out.totals.people.median + out.totals.parties.median + out.totals.unallocated.median,
    high: out.totals.people.high + out.totals.parties.high + out.totals.unallocated.high },
  out.totals.expected);
const person = (out: ExposureRanking, id: string) => out.people.find(p => p.actorId === id)!;

describe('曝露ランキングの集計器', () => {
  it('1本の法律を役割の比率で配る（反対は逆向き、閣議決定は閣僚に均等）', () => {
    const out = buildExposureRanking([group('g1', 1000)], [
      inv('発議者', 'L1', 'proposer'),
      inv('賛成A', 'L1', 'yes'), inv('賛成B', 'L1', 'yes'),
      inv('反対者', 'L1', 'no'),
      inv('閣僚A', 'L1', 'cabinet'), inv('閣僚B', 'L1', 'cabinet'), inv('閣僚C', 'L1', 'cabinet'), inv('閣僚D', 'L1', 'cabinet'),
    ], P);
    expect(person(out, '発議者').exposureYen.median).toBeCloseTo(400);
    expect(person(out, '賛成A').exposureYen.median).toBeCloseTo(100);
    expect(person(out, '反対者').exposureYen.median).toBeCloseTo(-200);
    expect(person(out, '閣僚A').exposureYen.median).toBeCloseTo(50);
    expect(out.unallocated).toEqual([]);
    close(out.totals.expected, yen(600));
    conserved(out);
  });

  it('因果でなく記述だと明記する', () => {
    const out = buildExposureRanking([], [], P);
    expect(out.claim).toBe('descriptive');
    expect(out.disclaimer).toBe(EXPOSURE_DISCLAIMER);
    expect(out.disclaimer).toContain('因果の推定ではありません');
  });

  it('群の額は法律の本数で等分した枠に分ける', () => {
    const out = buildExposureRanking([group('g1', 1000)], [
      inv('甲', 'L1', 'proposer'), inv('乙', 'L2', 'proposer'), inv('甲', 'L2', 'proposer'),
    ], P);
    // 甲：L1 の発議 200 ＋ L2 の発議の半分 100。乙：100。
    expect(person(out, '甲').exposureYen.median).toBeCloseTo(300);
    expect(person(out, '乙').exposureYen.median).toBeCloseTo(100);
    expect(person(out, '甲').laws).toBe(2);
    conserved(out);
  });

  it('関与の記録が無い役割の枠は未配分に積み、ほかの役割へ寄せない', () => {
    const out = buildExposureRanking([group('g1', 1000), group('g2', 500)], [inv('甲', 'L1', 'proposer')], P);
    expect(person(out, '甲').exposureYen.median).toBeCloseTo(400);
    const byRole = Object.fromEntries(out.unallocated.filter(u => u.groupId === 'g1').map(u => [u.role, u.exposureYen.median]));
    expect(byRole.yes).toBeCloseTo(200);
    expect(byRole.no).toBeCloseTo(-200);
    expect(byRole.cabinet).toBeCloseTo(200);
    const g2 = out.unallocated.find(u => u.groupId === 'g2')!;
    expect(g2.role).toBeNull();
    expect(g2.exposureYen.median).toBeCloseTo(300);
    conserved(out);
  });

  it('人と会派へ二重に配らない（合計は変わらない）', () => {
    const people = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'yes'), inv('乙', 'L1', 'yes')], P);
    const mixed = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'yes'), inv('会派X', 'L1', 'yes', 3, 'g1', 'party')], P);
    expect(person(mixed, '甲').exposureYen.median).toBeCloseTo(50);
    expect(mixed.parties[0].exposureYen.median).toBeCloseTo(150);
    expect(mixed.totals.people.median + mixed.totals.parties.median).toBeCloseTo(people.totals.people.median);
    conserved(mixed);
  });

  it('同じ ID の人と会派は別の行になる', () => {
    const out = buildExposureRanking([group('g1', 1000)], [inv('X', 'L1', 'yes'), inv('X', 'L1', 'yes', 1, 'g1', 'party')], P);
    expect(out.people).toHaveLength(1);
    expect(out.parties).toHaveLength(1);
  });

  it('出力に法律の ID も法律ごとの額も無い（群の差を法律へ配る経路が無い）', () => {
    const out = buildExposureRanking([group('g1', 1000)], [inv('甲', '法律-秘-001', 'proposer'), inv('甲', '法律-秘-002', 'yes')], P);
    const text = JSON.stringify(out);
    expect(text).not.toContain('法律-秘');
    expect(text).not.toContain('lawId');
  });

  it('幅は端どうしを足し、反対では端が入れ替わる', () => {
    const out = buildExposureRanking([group('g1', 1000, 500)], [inv('反対者', 'L1', 'no'), inv('発議者', 'L1', 'proposer')], P);
    expect(person(out, '反対者').exposureYen).toEqual({ low: -300, median: -200, high: -100 });
    expect(person(out, '発議者').exposureYen).toEqual({ low: 200, median: 400, high: 600 });
    for (const p of out.people) { expect(p.exposureYen.low).toBeLessThanOrEqual(p.exposureYen.median); expect(p.exposureYen.median).toBeLessThanOrEqual(p.exposureYen.high); }
    conserved(out);
  });

  it('伸び損ねが負の群（中央値より伸びた）でも幅の順序と検算が保たれる', () => {
    const out = buildExposureRanking([group('g1', -1000, 300), group('g2', 400, 100)], [
      inv('甲', 'L1', 'proposer'), inv('甲', 'L2', 'no', 1, 'g2'), inv('乙', 'L1', 'no'),
    ], P);
    for (const p of out.people) { expect(p.exposureYen.low).toBeLessThanOrEqual(p.exposureYen.median); expect(p.exposureYen.median).toBeLessThanOrEqual(p.exposureYen.high); }
    conserved(out);
  });

  it('階層：幅が先頭と重なる間は同じ階層', () => {
    const rows = assignTiers([
      { actorId: 'a', exposureYen: { low: 90, median: 100, high: 110 } },
      { actorId: 'b', exposureYen: { low: 80, median: 95, high: 105 } },
      { actorId: 'c', exposureYen: { low: 50, median: 60, high: 85 } },
      { actorId: 'd', exposureYen: { low: 40, median: 55, high: 70 } },
      { actorId: 'e', exposureYen: { low: 0, median: 10, high: 20 } },
    ]);
    expect(rows.map(r => [r.actorId, r.tier])).toEqual([['a', 1], ['b', 1], ['c', 2], ['d', 2], ['e', 3]]);
  });

  it('法律の本数が下限に満たない人は階層に入れず、額と本数は出す', () => {
    const invs = [1, 2, 3, 4, 5].map(i => inv('多い人', `L${i}`, 'proposer')).concat([inv('少ない人', 'L1', 'yes')]);
    const out = buildExposureRanking([group('g1', 1000)], invs, { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 5 });
    expect(person(out, '多い人').tier).toBe(1);
    const few = person(out, '少ない人');
    expect(few.tier).toBeNull();
    expect(few.unrankedReason).toContain('5本に満たない');
    expect(few.laws).toBe(1);
    expect(few.exposureYen.median).toBeCloseTo(40);
  });

  it('重みの大きさを変えても割合が同じなら結果は同じ', () => {
    const a = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'cabinet', 1), inv('乙', 'L1', 'cabinet', 3)], P);
    const b = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'cabinet', 0.25), inv('乙', 'L1', 'cabinet', 0.75)], P);
    expect(person(a, '甲').exposureYen.median).toBeCloseTo(person(b, '甲').exposureYen.median);
  });

  it('入力の順序を変えても結果は同じ', () => {
    const groups = [group('g1', 1000, 100), group('g2', 700, 50)];
    const invs = [inv('甲', 'L1', 'proposer'), inv('乙', 'L1', 'yes'), inv('丙', 'L2', 'no', 1, 'g2'), inv('甲', 'L3', 'cabinet', 1, 'g2'), inv('乙', 'L3', 'cabinet', 1, 'g2')];
    const a = buildExposureRanking(groups, invs, P);
    const b = buildExposureRanking([...groups].reverse(), [...invs].reverse(), P);
    expect(b.people.map(p => [p.actorId, p.tier])).toEqual(a.people.map(p => [p.actorId, p.tier]));
    for (const p of a.people) close(person(b, p.actorId).exposureYen, p.exposureYen);
  });

  it('不正な入力は止める', () => {
    const g = [group('g1', 1000)];
    expect(() => buildExposureRanking(g, [], { roleRatio: { proposer: 0.5, yes: 0.2, no: 0.2, cabinet: 0.2 }, minLaws: 1 })).toThrow('合計');
    expect(() => buildExposureRanking(g, [], { roleRatio: { proposer: 1.2, yes: -0.2, no: 0, cabinet: 0 }, minLaws: 1 })).toThrow('比率');
    expect(() => buildExposureRanking(g, [], { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 0 })).toThrow('下限');
    expect(() => buildExposureRanking(g, [inv('甲', 'L1', 'yes', 0)], P)).toThrow('重み');
    expect(() => buildExposureRanking(g, [inv('甲', 'L1', 'yes', 1, '無い群')], P)).toThrow('群の一覧に無い');
    expect(() => buildExposureRanking(g, [{ ...inv('甲', 'L1', 'yes'), actorKind: 'grp' as never }], P)).toThrow('種類');
    expect(() => buildExposureRanking(g, [inv('甲', 'L1', 'yes', 1e308), inv('乙', 'L1', 'yes', 1e308)], P)).toThrow('有限');
    expect(() => buildExposureRanking([...g, ...g], [], P)).toThrow('重複');
    expect(() => buildExposureRanking([{ ...g[0], shortfallYen: { low: 2, median: 1, high: 3 } }], [], P)).toThrow('幅');
  });

  it('既定の比率は書き換えられない', () => {
    expect(Object.isFrozen(DEFAULT_ROLE_RATIO)).toBe(true);
    expect(DEFAULT_ROLE_RATIO).toEqual({ proposer: 0.4, yes: 0.2, no: 0.2, cabinet: 0.2 });
  });
});
