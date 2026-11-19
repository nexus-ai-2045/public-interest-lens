import { describe, expect, it } from 'vitest';
import {
  assignTiers, buildExposureRanking, DEFAULT_ROLE_RATIO, EXPOSURE_DISCLAIMER, toPublicExposureRanking,
  type ExposureGroup, type ExposureRanking, type Involvement, type Range,
} from './exposure-ranking';

const yen = (median: number, spread = 0): Range => ({ low: median - spread, median, high: median + spread });
const group = (id: string, median: number, spread = 0, lawCount = 1): ExposureGroup =>
  ({ kind: 'group-diff', id, group: id, window: '2000〜2005年', diff: yen(median, spread), benchmark: 'テスト用の比較', lawCount });
/** 賛成・反対は院が必須。既定は参議院。 */
const inv = (actorId: string, lawId: string, role: Involvement['role'], weight = 1, groupId = 'g1', actorKind: Involvement['actorKind'] = 'person', house?: Involvement['house']): Involvement =>
  ({ actorKind, actorId, groupId, lawId, role, weight, ...(role === 'yes' || role === 'no' ? { house: house ?? 'upper' } : {}) });
const lower = (actorId: string, lawId: string, role: 'yes' | 'no', groupId = 'g1'): Involvement => inv(actorId, lawId, role, 1, groupId, 'party', 'lower');
const P = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 1 };
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
      inv('賛成A', 'L1', 'yes'), inv('賛成B', 'L1', 'yes'), lower('会派Y', 'L1', 'yes'),
      inv('反対者', 'L1', 'no'), lower('会派Z', 'L1', 'no'),
      inv('閣僚A', 'L1', 'cabinet'), inv('閣僚B', 'L1', 'cabinet'), inv('閣僚C', 'L1', 'cabinet'), inv('閣僚D', 'L1', 'cabinet'),
    ], P);
    expect(person(out, '発議者').exposureYen.median).toBeCloseTo(400);
    // 賛成の枠200は院で半分ずつ：参議院の100を2人で、衆議院の100を会派Yへ。反対も同じ。
    expect(person(out, '賛成A').exposureYen.median).toBeCloseTo(50);
    expect(out.parties.find(x => x.actorId === '会派Y')!.exposureYen.median).toBeCloseTo(100);
    expect(person(out, '反対者').exposureYen.median).toBeCloseTo(-100);
    expect(out.parties.find(x => x.actorId === '会派Z')!.exposureYen.median).toBeCloseTo(-100);
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
    const out = buildExposureRanking([group('g1', 1000, 0, 2)], [
      inv('甲', 'L1', 'proposer'), inv('乙', 'L2', 'proposer'), inv('甲', 'L2', 'proposer'),
    ], P);
    // 甲：L1 の発議 200 ＋ L2 の発議の半分 100。乙：100。
    expect(person(out, '甲').exposureYen.median).toBeCloseTo(300);
    expect(person(out, '乙').exposureYen.median).toBeCloseTo(100);
    expect(person(out, '甲').laws).toBe(2);
    conserved(out);
  });

  it('関与の記録が無い役割の枠は未配分に積み、ほかの役割へ寄せない', () => {
    const out = buildExposureRanking([group('g1', 1000), group('g2', 500, 0, 3)], [inv('甲', 'L1', 'proposer')], P);
    expect(person(out, '甲').exposureYen.median).toBeCloseTo(400);
    const byRole: Record<string, number> = {};
    for (const u of out.unallocated.filter(x => x.groupId === 'g1')) byRole[u.role!] = (byRole[u.role!] ?? 0) + u.exposureYen.median;
    expect(byRole.yes).toBeCloseTo(200);
    expect(byRole.no).toBeCloseTo(-200);
    expect(byRole.cabinet).toBeCloseTo(200);
    const g2 = out.unallocated.find(u => u.groupId === 'g2')!;
    expect(g2.role).toBeNull();
    expect(g2.laws).toBe(3);
    expect(g2.reason).toBe('この群の法律のうち関与の記録が無い法律の枠');
    expect(g2.exposureYen.median).toBeCloseTo(300);
    conserved(out);
  });

  it('人と会派へ二重に配らない（合計は変わらない）', () => {
    const people = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'yes'), inv('乙', 'L1', 'yes')], P);
    const mixed = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'yes'), inv('会派X', 'L1', 'yes', 3, 'g1', 'party')], P);
    // 参議院の半分（100）を重み1:3で分ける。
    expect(person(mixed, '甲').exposureYen.median).toBeCloseTo(25);
    expect(mixed.parties[0].exposureYen.median).toBeCloseTo(75);
    expect(mixed.totals.people.median + mixed.totals.parties.median).toBeCloseTo(people.totals.people.median);
    conserved(mixed);
  });

  it('同じ ID の人と会派は別の行になる', () => {
    const out = buildExposureRanking([group('g1', 1000)], [inv('X', 'L1', 'yes'), inv('X', 'L1', 'yes', 1, 'g1', 'party')], P);
    expect(out.people).toHaveLength(1);
    expect(out.parties).toHaveLength(1);
  });

  it('出力に法律の ID も法律ごとの額も無い（群の差を法律へ配る経路が無い）', () => {
    const out = buildExposureRanking([group('g1', 1000, 0, 2)], [inv('甲', '法律-秘-001', 'proposer'), inv('甲', '法律-秘-002', 'yes')], P);
    const text = JSON.stringify(out);
    expect(text).not.toContain('法律-秘');
    expect(text).not.toContain('lawId');
  });

  it('幅は端どうしを足し、反対では端が入れ替わる', () => {
    const out = buildExposureRanking([group('g1', 1000, 500)], [inv('反対者', 'L1', 'no'), inv('発議者', 'L1', 'proposer')], P);
    expect(person(out, '反対者').exposureYen).toEqual({ low: -150, median: -100, high: -50 });
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
    const out = buildExposureRanking([group('g1', 1000, 0, 5)], invs, { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 5, topThreeShareCap: 1 });
    expect(person(out, '多い人').tier).toBe(1);
    const few = person(out, '少ない人');
    expect(few.tier).toBeNull();
    expect(few.unrankedReason).toContain('5本に満たない');
    expect(few.laws).toBe(1);
    expect(few.exposureYen.median).toBeCloseTo(20);
  });

  it('重みの大きさを変えても割合が同じなら結果は同じ', () => {
    const a = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'cabinet', 1), inv('乙', 'L1', 'cabinet', 3)], P);
    const b = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'cabinet', 0.25), inv('乙', 'L1', 'cabinet', 0.75)], P);
    expect(person(a, '甲').exposureYen.median).toBeCloseTo(person(b, '甲').exposureYen.median);
  });

  it('入力の順序を変えても結果は同じ', () => {
    const groups = [group('g1', 1000, 100), group('g2', 700, 50, 2)];
    const invs = [inv('甲', 'L1', 'proposer'), inv('乙', 'L1', 'yes'), inv('丙', 'L2', 'no', 1, 'g2'), inv('甲', 'L3', 'cabinet', 1, 'g2'), inv('乙', 'L3', 'cabinet', 1, 'g2')];
    const a = buildExposureRanking(groups, invs, P);
    const b = buildExposureRanking([...groups].reverse(), [...invs].reverse(), P);
    expect(b.people.map(p => [p.actorId, p.tier])).toEqual(a.people.map(p => [p.actorId, p.tier]));
    for (const p of a.people) close(person(b, p.actorId).exposureYen, p.exposureYen);
  });

  it('不正な入力は止める', () => {
    const g = [group('g1', 1000)];
    expect(() => buildExposureRanking(g, [], { roleRatio: { proposer: 0.5, yes: 0.2, no: 0.2, cabinet: 0.2 }, minLaws: 1, topThreeShareCap: 1 })).toThrow('合計');
    expect(() => buildExposureRanking(g, [], { roleRatio: { proposer: 1.2, yes: -0.2, no: 0, cabinet: 0 }, minLaws: 1, topThreeShareCap: 1 })).toThrow('比率');
    expect(() => buildExposureRanking(g, [], { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 0, topThreeShareCap: 1 })).toThrow('下限');
    expect(() => buildExposureRanking(g, [inv('甲', 'L1', 'yes', 0)], P)).toThrow('重み');
    expect(() => buildExposureRanking(g, [inv('甲', 'L1', 'yes', 1, '無い群')], P)).toThrow('群の一覧に無い');
    expect(() => buildExposureRanking(g, [{ ...inv('甲', 'L1', 'yes'), actorKind: 'grp' as never }], P)).toThrow('種類');
    expect(() => buildExposureRanking(g, [inv('甲', 'L1', 'yes', 1e308), inv('乙', 'L1', 'yes', 1e308)], P)).toThrow('有限');
    expect(() => buildExposureRanking([...g, ...g], [], P)).toThrow('重複');
    expect(() => buildExposureRanking([{ ...g[0], diff: { low: 2, median: 1, high: 3 } }], [], P)).toThrow('幅');
  });

  it('lawCount：記録の無い法律の枠は全役割ぶんが未配分に積まれ、検算が合う', () => {
    const out = buildExposureRanking([group('g1', 1000, 100, 4)], [inv('甲', 'L1', 'proposer'), inv('乙', 'L2', 'yes')], P);
    // 4本のうち記録があるのは2本。記録の無い2本ぶんは全役割（0.4＋0.2−0.2＋0.2＝0.6）の半分。
    const none = out.unallocated.find(u => u.role === null)!;
    expect(none.laws).toBe(2);
    expect(none.exposureYen.median).toBeCloseTo(1000 * 0.6 * 2 / 4);
    expect(person(out, '甲').exposureYen.median).toBeCloseTo(1000 * 0.4 / 4);
    close(out.totals.expected, { low: 500, median: 600, high: 700 }); // 反対は端が入れ替わる
    conserved(out);
  });

  it('lawCount が正の整数でない、または記録のある法律の本数より小さいと止める', () => {
    const invs = [inv('甲', 'L1', 'proposer'), inv('甲', 'L2', 'proposer')];
    expect(() => buildExposureRanking([group('g1', 1000, 0, 1)], invs, P)).toThrow('より小さい');
    expect(() => buildExposureRanking([group('g1', 1000, 0, 0)], [], P)).toThrow('正の整数');
    expect(() => buildExposureRanking([group('g1', 1000, 0, 1.5)], [], P)).toThrow('正の整数');
    expect(() => buildExposureRanking([group('g1', 1000, 0, 2)], invs, P)).not.toThrow();
  });

  it('上位3本の占有率が上限を超える人は階層に入れず、ちょうど上限は入る', () => {
    const cap = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 0.5 };
    // 法律6本・各1000、発議だけ。甲は6本を均等に（上位3本で 3/6 = 0.5 ちょうど）、乙は1本だけ大きく。
    const groups = [group('g1', 600, 0, 6), group('g2', 1000, 0, 1)];
    const invs = [1, 2, 3, 4, 5, 6].map(i => inv('甲', `L${i}`, 'proposer')).concat([inv('乙', 'L7', 'proposer', 1, 'g2')]);
    // L7 は単独の群なので乙の寄与はこの1本だけ（占有率 1）。
    const out = buildExposureRanking(groups, invs, cap);
    expect(person(out, '甲').topThreeShare).toBeCloseTo(0.5, 12);
    expect(person(out, '甲').tier).not.toBeNull();
    const b = person(out, '乙');
    expect(b.topThreeShare).toBe(1);
    expect(b.tier).toBeNull();
    expect(b.unrankedReason).toBe('上位3本の占有率が50.0%を超える（100.0%）');
    // 法律の ID も法律ごとの額も出さない。
    expect(JSON.stringify(out)).not.toContain('L7');
  });

  it('占有率が浮動小数点の丸めで上限をわずかに超えて見えても、ちょうど上限の人は階層に入る', () => {
    // 5本・各200（群の額1000×発議0.4÷5）の上位3本＝600÷1000＝0.6。割り算の丸めで 0.6 をわずかに超える値になる（許容誤差が無いと弾かれる）。
    const out = buildExposureRanking([group('g1', 1000, 0, 5)], [1, 2, 3, 4, 5].map(i => inv('甲', `L${i}`, 'proposer')), { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 3 / 5 });
    expect(person(out, '甲').topThreeShare).toBeGreaterThan(3 / 5);
    expect(person(out, '甲').topThreeShare).toBeCloseTo(3 / 5, 12);
    expect(person(out, '甲').tier).not.toBeNull();
    // 本当に超える人（1e-12 より大きく超える）は入らない。
    const over = buildExposureRanking([group('g1', 1000, 0, 5)], [1, 2, 3, 4, 5].map(i => inv('甲', `L${i}`, 'proposer')), { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 0.59 });
    expect(person(over, '甲').tier).toBeNull();
  });

  it('下限に満たない理由と占有率の理由が両方当たるときは、下限の理由を優先する', () => {
    const out = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'proposer')], { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 5, topThreeShareCap: 0.5 });
    expect(person(out, '甲').unrankedReason).toContain('5本に満たない');
  });

  it('占有率の上限が不正なら止める', () => {
    expect(() => buildExposureRanking([group('g1', 1000)], [], { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 0 })).toThrow('占有率');
    expect(() => buildExposureRanking([group('g1', 1000)], [], { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 1.5 })).toThrow('占有率');
  });

  it('賛成・反対は院で半分ずつ。片方の院の記録が無ければ半分を未配分に積み、もう片方へ寄せない', () => {
    const out = buildExposureRanking([group('g1', 1000)], [inv('参議員', 'L1', 'yes'), inv('参反対', 'L1', 'no'), lower('会派X', 'L1', 'no')], P);
    // 賛成の枠200：参議院の100は参議員。衆議院の記録は無いので100は未配分。
    expect(person(out, '参議員').exposureYen.median).toBeCloseTo(100);
    const un = (role: string, house: string) => out.unallocated.filter(u => u.role === role && u.house === house);
    expect(un('yes', 'lower')).toHaveLength(1);
    expect(un('yes', 'lower')[0].reason).toBe('衆議院の賛否の記録が無い法律の枠');
    expect(un('yes', 'lower')[0].exposureYen.median).toBeCloseTo(100);
    expect(un('yes', 'upper')).toHaveLength(0);
    // 反対は両院とも記録がある（逆向き）。
    expect(person(out, '参反対').exposureYen.median).toBeCloseTo(-100);
    expect(out.parties[0].exposureYen.median).toBeCloseTo(-100);
    expect(un('no', 'lower')).toHaveLength(0);
    // 参議院の記録が無い役割の理由。
    const onlyLower = buildExposureRanking([group('g1', 1000)], [lower('会派X', 'L1', 'yes')], P);
    expect(onlyLower.unallocated.find(u => u.role === 'yes' && u.house === 'upper')!.reason).toBe('参議院の賛否の記録が無い法律の枠');
    conserved(out);
    conserved(onlyLower);
  });

  it('賛成・反対の関与に院が無い、または院が不正なら止める', () => {
    const noHouse = { ...inv('甲', 'L1', 'yes'), house: undefined };
    expect(() => buildExposureRanking([group('g1', 1000)], [noHouse], P)).toThrow('院');
    expect(() => buildExposureRanking([group('g1', 1000)], [{ ...noHouse, house: 'both' as never }], P)).toThrow('院');
    // 発議・閣議決定は院を見ない。
    expect(() => buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'proposer'), inv('甲', 'L1', 'cabinet')], P)).not.toThrow();
  });

  it('配り先なしの関与は重みだけ枠に入れ、その分を未配分に積む（ほかの人へ寄せない）', () => {
    const none: Involvement = { actorKind: 'none', actorId: '', groupId: 'g1', lawId: 'L1', role: 'yes', weight: 1, house: 'upper' };
    const out = buildExposureRanking([group('g1', 1000)], [inv('甲', 'L1', 'yes'), none, { ...none }, { ...none }], P);
    // 参議院の半分（100）を4票で割る：甲は25、未特定の3票は75。
    expect(person(out, '甲').exposureYen.median).toBeCloseTo(25);
    const u = out.unallocated.find(x => x.reason === '同姓同名で人物台帳に結べない票')!;
    expect(u.exposureYen.median).toBeCloseTo(75);
    expect(u.house).toBe('upper');
    expect(out.people).toHaveLength(1);
    conserved(out);
  });

  it('同じ法律・役割・院の枠は人と会派の両方に配られない（合計が枠を超えない）', () => {
    const out = buildExposureRanking([group('g1', 1000)], [
      inv('甲', 'L1', 'yes'), inv('乙', 'L1', 'yes'), inv('甲', 'L1', 'no'), inv('甲', 'L1', 'proposer'), inv('甲', 'L1', 'cabinet'), inv('丙', 'L1', 'cabinet'),
      lower('会派X', 'L1', 'yes'), lower('会派Y', 'L1', 'yes'),
    ], P);
    // 1本・1つの群：全員（人＋会派＋未配分）の受ける割合は比率の符号つき合計（0.6）で、これを超えない。
    conserved(out);
    const all = out.totals.people.median + out.totals.parties.median + out.totals.unallocated.median;
    expect(all).toBeCloseTo(600);
    // 1人が1本の法律から受ける割合は、その人の役割の比率の和を超えない：甲は発議0.4＋閣議0.2/2＋賛成0.2×0.5/2＋反対0.2×0.5 の絶対値の上限。
    const kou = person(out, '甲');
    expect(kou.exposureYen.median).toBeLessThanOrEqual(1000 * (0.4 + 0.2 / 2 + 0.1 / 2 + 0.1) + 1e-9);
    // 配り先ごとの額を直接確かめる。賛成の枠200：参議院の100は甲・乙で、衆議院の100は会派X・Yで。反対の枠-200：参議院の-100は甲、衆議院は記録が無く未配分。
    const cell = (row: { cells: { role: string; exposureYen: Range }[] }, role: string) => row.cells.find(c => c.role === role)?.exposureYen.median;
    expect(cell(kou, 'yes')).toBeCloseTo(50);
    expect(cell(kou, 'no')).toBeCloseTo(-100);
    expect(cell(kou, 'proposer')).toBeCloseTo(400);
    expect(cell(kou, 'cabinet')).toBeCloseTo(100);
    expect(kou.exposureYen.median).toBeCloseTo(450);
    expect(cell(person(out, '乙'), 'yes')).toBeCloseTo(50);
    expect(person(out, '乙').exposureYen.median).toBeCloseTo(50);
    expect(person(out, '丙').exposureYen.median).toBeCloseTo(100);
    expect(out.parties.find(x => x.actorId === '会派X')!.exposureYen.median).toBeCloseTo(50);
    expect(out.parties.find(x => x.actorId === '会派Y')!.exposureYen.median).toBeCloseTo(50);
    expect(out.totals.people.median).toBeCloseTo(600);
    expect(out.totals.parties.median).toBeCloseTo(100);
    const noLower = out.unallocated.find(u => u.role === 'no' && u.house === 'lower')!;
    expect(noLower.exposureYen.median).toBeCloseTo(-100);
    // 賛成の枠（200）は人と会派で二重に使われない。
    const yesTotal = ['甲', '乙'].reduce((x, id) => x + (cell(person(out, id), 'yes') ?? 0), 0) + out.parties.reduce((x, p) => x + (cell(p, 'yes') ?? 0), 0);
    expect(yesTotal).toBeCloseTo(200);
  });

  it('同じ人が複数の役割を持てば足す（閣僚は閣議0.2＋発議0.4）', () => {
    const out = buildExposureRanking([group('g1', 1000)], [inv('閣僚', 'L1', 'cabinet'), inv('閣僚', 'L1', 'proposer')], P);
    expect(person(out, '閣僚').exposureYen.median).toBeCloseTo(600);
  });

  it('内訳の束ね方を呼ぶ側が決められる（産業×年の群を産業で束ねる）。本数は法律の重複なし、額は年の和、row の groups は群の数のまま', () => {
    const gs = [{ ...group('A|1998', 1000, 0, 2), group: 'A' }, { ...group('A|1999', 2000, 0, 2), group: 'A' }];
    const invs = [inv('甲', 'L1', 'proposer', 1, 'A|1998'), inv('甲', 'L1', 'proposer', 1, 'A|1999'), inv('甲', 'L2', 'proposer', 1, 'A|1999')];
    const plain = buildExposureRanking(gs, invs, P);
    const rolled = buildExposureRanking(gs, invs, P, { cellGroupOf: id => id.split('|')[0] });
    expect(person(plain, '甲').cells).toHaveLength(2);
    const cells = person(rolled, '甲').cells;
    expect(cells).toHaveLength(1);
    expect(cells[0]).toMatchObject({ groupId: 'A', role: 'proposer', laws: 2 });
    expect(cells[0].exposureYen.median).toBeCloseTo(person(plain, '甲').exposureYen.median);
    expect(person(rolled, '甲').groups).toBe(2);
    expect(person(rolled, '甲').exposureYen).toEqual(person(plain, '甲').exposureYen);
  });

  it('既定の比率は書き換えられない', () => {
    expect(Object.isFrozen(DEFAULT_ROLE_RATIO)).toBe(true);
    expect(DEFAULT_ROLE_RATIO).toEqual({ proposer: 0.4, yes: 0.2, no: 0.2, cabinet: 0.2 });
  });
});

describe('公開用への変換（法律1本ぶんの額を出さない）', () => {
  const pub = (invs: Involvement[], groups = [group('g1', 1000, 100, 5)], minLaws = 3) => {
    const out = buildExposureRanking(groups, invs, { roleRatio: DEFAULT_ROLE_RATIO, minLaws, topThreeShareCap: 1 });
    return { out, pub: toPublicExposureRanking(out, minLaws) };
  };
  const row = (r: { people: { actorId: string }[] }, id: string) => r.people.find(p => p.actorId === id)! as ReturnType<typeof toPublicExposureRanking>['people'][number];
  const five = (id: string, role: Involvement['role'] = 'proposer') => [1, 2, 3, 4, 5].map(i => inv(id, `L${i}`, role));

  it('関与した法律が1本の人は、額も内訳の額も出さない。額＝その1本の額が読めない', () => {
    const { out, pub: p } = pub([...five('多い人'), inv('一本の人', 'L1', 'proposer')]);
    const one = row(p, '一本の人');
    expect(one.tier).toBeNull();
    expect(one.exposureYen).toBeNull();
    expect(one.cells.every(c => c.exposureYen === null)).toBe(true);
    // 本数・群の数・役割・理由は残す。
    expect(one).toMatchObject({ laws: 1, groups: 1, unrankedReason: '関与した法律が3本に満たない（1本）' });
    expect(one.cells).toMatchObject([{ groupId: 'g1', role: 'proposer', laws: 1 }]);
    // 1本ぶんの額（発議の枠80を多い人と半分ずつ＝40）の数値が、その人の行のどこにも出ない。
    const oneAmount = person(out, '一本の人').exposureYen.median;
    expect(oneAmount).toBeCloseTo(40);
    expect(JSON.stringify(one)).not.toContain(String(oneAmount));
    expect(row(p, '多い人').tier).toBe(1);
    expect(row(p, '多い人').exposureYen).toEqual(person(out, '多い人').exposureYen);
  });

  it('階層に入った人でも、内訳に本数が下限未満のものがあれば内訳の額を全部出さない（本数と役割は残す）', () => {
    const invs = [...five('甲'), ...[1, 2, 3, 4, 5].map(i => inv('甲', `L${i}`, 'cabinet')).slice(0, 1)];
    const p = pub(invs).pub;
    const kou = row(p, '甲');
    expect(kou.tier).not.toBeNull();
    expect(kou.exposureYen).not.toBeNull();
    const roles = kou.cells.map(c => `${c.role}:${c.laws}`).sort();
    expect(roles).toEqual(['cabinet:1', 'proposer:5']);
    for (const c of kou.cells.filter(x => x.laws < 3)) expect(c.exposureYen).toBeNull();
    expect(kou.cells.every(c => c.exposureYen === null)).toBe(true);
    // 全部の内訳が下限以上なら額を出す。
    const ok = row(pub(five('乙')).pub, '乙');
    expect(ok.cells[0].exposureYen).not.toBeNull();
    expect(ok.cells[0].laws).toBe(5);
  });

  it('額を出さない人・会派の合計を件数つきで出す。出せるのは2つ以上のとき', () => {
    const invs = [...five('多い人'), inv('少甲', 'L1', 'proposer'), inv('少乙', 'L2', 'proposer'), inv('少丙', 'L1', 'cabinet', 1, 'g1', 'person'), lower('会派少', 'L1', 'yes')];
    const { out, pub: p } = pub(invs);
    expect(p.hidden.people.count).toBe(3);
    expect(p.hidden.parties.count).toBe(1);
    // 会派が1つだけ・人が3つ：合わせて4つなので合計は出る。
    const hiddenPeople = out.people.filter(x => x.tier === null).reduce((s, x) => s + x.exposureYen.median, 0);
    expect(p.hidden.people.exposureYen!.median).toBeCloseTo(hiddenPeople);
    expect(p.hidden.parties.exposureYen!.median).toBeCloseTo(out.parties[0].exposureYen.median);
    expect(p.totals.people).toEqual(out.totals.people);
    expect(p.totals.parties).toEqual(out.totals.parties);
    // 検算は公開用でも合う：人＋会派＋未配分＝期待値。
    for (const k of ['low', 'median', 'high'] as const) expect(p.totals.people![k] + p.totals.parties![k] + p.totals.unallocated[k]).toBeCloseTo(p.totals.expected[k], 6);
    // 階層に入った人の額の和と、額を出さない人の合計の和が、全員の合計になる。
    const ranked = p.people.filter(x => x.tier !== null).reduce((s, x) => s + x.exposureYen!.median, 0);
    expect(ranked + p.hidden.people.exposureYen!.median).toBeCloseTo(p.totals.people!.median);
  });

  it('額を出さない人が1人だけのときは、その合計も totals の people・parties も伏せる（引き算で1人の額が読めるため）', () => {
    const { out, pub: p } = pub([...five('多い人'), inv('一本の人', 'L1', 'proposer')]);
    expect(p.hidden.people).toEqual({ count: 1, exposureYen: null });
    expect(p.hidden.parties).toEqual({ count: 0, exposureYen: null });
    expect(p.totals.people).toBeNull();
    expect(p.totals.parties).toBeNull();
    // 検算に要る expected と unallocated は残る。
    expect(p.totals.expected).toEqual(out.totals.expected);
    expect(p.totals.unallocated).toEqual(out.totals.unallocated);
    // 引き算で復元できない：公開用の JSON のどこにも、その人の額も、全員の合計から残りを引いた値も無い。
    const text = JSON.stringify(p);
    expect(text).not.toContain(String(person(out, '一本の人').exposureYen.median));
    // 人が0・会派が1のときも同じ（人と会派を合わせて1つ）。
    const partyOnly = pub([...five('多い人'), lower('会派少', 'L1', 'yes')]).pub;
    expect(partyOnly.hidden.people.count + partyOnly.hidden.parties.count).toBe(1);
    expect(partyOnly.totals.people).toBeNull();
    expect(partyOnly.hidden.parties.exposureYen).toBeNull();
    // 額を出さない行が無ければ、合計は出て、hidden は件数0の0円。
    const none = pub(five('多い人')).pub;
    expect(none.totals.people).not.toBeNull();
    expect(none.hidden.people).toEqual({ count: 0, exposureYen: { low: 0, median: 0, high: 0 } });
  });

  it('入力を変えない。階層に入った行の額と順位は変わらない。法律の ID は出ない', () => {
    const { out } = pub([...five('多い人'), inv('一本の人', 'L1', 'proposer')]);
    const before = JSON.stringify(out);
    const p = toPublicExposureRanking(out, 3);
    expect(JSON.stringify(out)).toBe(before);
    expect(p.people.map(x => [x.actorId, x.tier])).toEqual(out.people.map(x => [x.actorId, x.tier]));
    expect(JSON.stringify(p)).not.toMatch(/L[0-9]/);
    for (const x of p.people) if (x.tier === null) { expect(x.exposureYen).toBeNull(); for (const c of x.cells) expect(c.exposureYen).toBeNull(); }
  });
});
