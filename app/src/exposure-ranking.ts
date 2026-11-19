/**
 * 曝露ランキング（案B）の集計器。純関数で、ファイルも通信も読まない。
 *
 * 何を出すか：議員や会派が関与した法律の属する「産業×期間の群」の伸び損ね額（OECD 同産業・同時期の中央値との差）を、
 * 役割ごとの固定比率で配った額。これは「関与していた群がどれだけ伸び損ねたか」の記述であって、
 * その人や法律が伸び損ねを起こしたという因果の推定ではない（設計確定 v2.1 の L1・L3）。
 *
 * 決まり：
 * 1. 群の額は、群に属する法律の本数 n（lawCount。関与の記録が無い法律も数える）で等分した「1本ぶんの枠」に分け、枠の中を役割の比率で分ける。
 *    枠は配るための数え方で、法律単位の額としては出さない（出力の型に法律の ID も法律ごとの額も無い）。
 * 2. 役割の比率は取り決め（つまみ①）。反対は逆向き（符号を反転）で配る。
 * 3. 1本・1役割の中は、渡された重みの割合で配る（閣議決定は閣僚に均等、のような重みは呼ぶ側が決める）。
 *    重みの合計で割るので、1本・1役割の枠は必ず配り切る。
 * 4. 配り先は人か会派のどちらか一方。個人の記録が無い賛否は会派に置き、同じ枠を人と会派へ二重に配らない。
 * 5. ある法律で関与の記録が無い役割の枠は「未配分」に理由つきで積む（黙って消さない、ほかの役割へ寄せない）。
 *    関与の記録が1つも無い法律のぶん（lawCount − 記録のある法律数）は、全役割ぶんの枠を role: null で未配分に積む。
 * 6. 幅（low・median・high）は端どうしを足す。群どうしの相関を仮定しない広めの幅になる。反対は端が入れ替わるので、
 *    検算の合計（totals.expected）も役割ごとに幅を作ってから足す。
 * 7. 階層は、額の中央値の大きい順に並べ、幅が階層の先頭の人と重なる間は同じ階層とする。
 *    群の額の幅をそのまま使った記述の階層で、統計的な同時信頼集合ではない。
 * 8. 関与した法律が下限（minLaws）に満たない人・会派は階層に入れず、額と本数だけを出す。
 * 9. 上位3本の占有率（topThreeShare＝寄与の大きい上位3本の |寄与| の和 ÷ 全法律の |寄与| の和）が上限（topThreeShareCap）を超える人・会派も
 *    階層に入れない（1本で決まる人）。法律ごとの寄与は集計の中だけで持ち、出力には比率だけを出す。minLaws の理由と両方当たるときは minLaws を優先する。
 * 10. 賛成・反対の枠は、院で半分ずつ（HOUSE_SPLIT。取り決め）に分け、それぞれの半分をその院の関与の重みの割合で配る。
 *     片方の院の記録が無い法律・役割は、その半分を未配分に積む（もう片方の院へ寄せない）。発議・閣議決定は院を見ない。
 * 11. 役割は別々の行動なので、同じ人が同じ法律で複数の役割を持てば足す（閣僚は閣議0.2＋発議0.4、賛成票があれば＋賛成の枠）。
 *     「二重に配らない」は、同じ（法律・役割・院）の枠を人と会派の両方へ配らないこと。
 * 12. 配り先の無い関与（actorKind: 'none'。同姓同名で人物台帳に結べない票）は、重みだけ枠に入れ、その分を未配分に積む（ほかの人へ寄せない）。
 * 13. 公開用（toPublicExposureRanking）：階層に入らない行は額（exposureYen と cells の額）を出さず、本数・群の数・理由だけを残す。
 *     階層に入った行も、内訳に本数が下限（minLaws）に満たない群×役割が1つでもあれば内訳の額を全部伏せる（1つだけ伏せても合計との引き算で読めるため）。
 *     額を出さない人・会派の分の合計は出す（複数の合算で、個人の額ではない。丸めはしない）。ただし額を出さない人・会派が合わせて1つだけのときは、
 *     その合計も totals の全部（expected・unallocated を含む）も未配分の内訳の額も伏せる（null。expected − unallocated − 出ている額 でその1つの額が読めるため）。
 *     未配分は群×役割の合計に束ね、「N本ぶんの枠」の本数は出さない。本数が下限に満たない群×役割は役割ごとの1行にまとめる（summarizeUnallocated）。
 */

import type { GroupDiff, Range } from './scoring-types';
export type { Range };
export type ExposureRole = 'proposer' | 'yes' | 'no' | 'cabinet';
export const EXPOSURE_ROLES: readonly ExposureRole[] = ['proposer', 'yes', 'no', 'cabinet'];
export type RoleRatio = Readonly<Record<ExposureRole, number>>;
/** つまみ①の初期値（設計確定 v2.1 §2）：発議0.4・賛成0.2・反対0.2（逆向き）・閣議決定0.2。 */
export const DEFAULT_ROLE_RATIO: RoleRatio = Object.freeze({ proposer: 0.4, yes: 0.2, no: 0.2, cabinet: 0.2 });
/** 反対だけ逆向き。 */
const SIGN: Readonly<Record<ExposureRole, 1 | -1>> = { proposer: 1, yes: 1, no: -1, cabinet: 1 };

/** 産業×期間の群の差（diff は正が伸び損ね、負は比較より伸びた）と、群に属する法律の本数（関与の記録が無い法律も含む）。 */
export type ExposureGroup = GroupDiff & { id: string; lawCount: number };
/** none は配り先の無い関与（重みだけを枠に入れ、その分は未配分に積む）。 */
export type ActorKind = 'person' | 'party' | 'none';
export type House = 'lower' | 'upper';
/** 賛成・反対の枠を院で分ける割合（取り決め）。衆議院にこの割合、参議院に残りを置く。 */
export const HOUSE_SPLIT = 0.5;
/**
 * 1つの関与：誰が、どの群のどの法律に、どの役割で関わったか。weight は同じ法律・同じ役割（賛成・反対は同じ院）の中での重み（正の数）。
 * house は賛成・反対（yes・no）では必須。発議・閣議決定では見ない。
 */
export type Involvement = { actorKind: ActorKind; actorId: string; groupId: string; lawId: string; role: ExposureRole; weight: number; house?: House;
  /** actorKind: 'none' のとき、未配分に積む理由（無ければ「同姓同名で人物台帳に結べない票」）。 */ noneReason?: string };
export type ExposureParams = {
  roleRatio: RoleRatio;
  /** 階層に入れるのに要る、関与した法律の本数の下限。 */ minLaws: number;
  /** 上位3本の占有率の上限（超えると階層に入れない。ちょうど上限は入る）。 */ topThreeShareCap: number;
};

export type ExposureCell = { groupId: string; role: ExposureRole; laws: number; exposureYen: Range };
export type ExposureRow = {
  actorKind: ActorKind;
  actorId: string;
  exposureYen: Range;
  /** 関与した法律の本数（重複なし）と群の数。 */
  laws: number;
  groups: number;
  /** 上位3本の占有率（0〜1。比率だけで、法律の ID も額も出さない）。 */
  topThreeShare: number;
  /** 群×役割ごとの内訳。法律ごとの額は持たない。 */
  cells: ExposureCell[];
  /** 階層（1が最も曝露が大きい）。下限に満たないときは null で、unrankedReason に理由。 */
  tier: number | null;
  unrankedReason: string;
};
export type Unallocated = { groupId: string; role: ExposureRole | null; /** 賛成・反対の院ごとの枠のとき。 */ house?: House; laws: number; exposureYen: Range; reason: string };
export type ExposureRanking = {
  schema: 'exposure-ranking/v1';
  /** 因果の推定ではなく記述。 */
  claim: 'descriptive';
  disclaimer: string;
  params: ExposureParams;
  people: ExposureRow[];
  parties: ExposureRow[];
  unallocated: Unallocated[];
  /** 検算：人＋会派＋未配分＝群の額×（比率の符号つき合計）。 */
  totals: { people: Range; parties: Range; unallocated: Range; expected: Range };
};

export const EXPOSURE_DISCLAIMER =
  'この額は、関与した法律が属する産業群の伸び損ね額を、役割ごとの固定比率（取り決め）で配った記述です。その人や法律が伸び損ねの原因だという因果の推定ではありません。';

/** 小数1桁の百分率（四捨五入で「50%を超える（50%）」のように見えないため）。 */
const pct = (x: number): string => `${(x * 100).toFixed(1)}%`;
const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });
/** 負の数を掛けると端が入れ替わる。 */
const scale = (r: Range, x: number): Range => (x >= 0
  ? { low: r.low * x, median: r.median * x, high: r.high * x }
  : { low: r.high * x, median: r.median * x, high: r.low * x });

const EPS = 1e-9;
/** 占有率の比較の許容誤差。ちょうど上限の人が浮動小数点の丸めで弾かれないようにする。 */
const SHARE_EPS = 1e-12;

function checkParams(p: ExposureParams): void {
  let sum = 0;
  for (const r of EXPOSURE_ROLES) {
    const v = p.roleRatio[r];
    if (!Number.isFinite(v) || v < 0) throw new Error(`役割の比率が不正：${r}=${v}`);
    sum += v;
  }
  if (Math.abs(sum - 1) > EPS) throw new Error(`役割の比率の合計が1でない：${sum}`);
  if (!Number.isInteger(p.minLaws) || p.minLaws < 1) throw new Error(`法律の本数の下限が不正：${p.minLaws}`);
  if (!Number.isFinite(p.topThreeShareCap) || p.topThreeShareCap <= 0 || p.topThreeShareCap > 1) throw new Error(`上位3本の占有率の上限が不正：${p.topThreeShareCap}`);
}

/**
 * 階層を付ける。中央値の大きい順（同じなら ID 順）に並べ、幅が階層の先頭と重なる（high ≥ 先頭の low）間は同じ階層。
 * 返すのは並べ替えた新しい配列。
 */
export function assignTiers<T extends { actorId: string; exposureYen: Range }>(rows: readonly T[]): (T & { tier: number })[] {
  const sorted = [...rows].sort((a, b) => b.exposureYen.median - a.exposureYen.median || a.actorId.localeCompare(b.actorId));
  let tier = 0;
  let leaderLow = Infinity;
  return sorted.map(r => {
    if (tier === 0 || r.exposureYen.high < leaderLow) { tier++; leaderLow = r.exposureYen.low; }
    return { ...r, tier };
  });
}

/**
 * options.cellGroupOf：内訳（cells）の束ね方。群の ID を内訳の行の ID に写す（既定は群の ID のまま）。
 * 例：産業×年の群を産業で束ねると、内訳は産業×役割になる（本数は法律の重複なし、額は年を足したもの）。row の groups は束ねる前の群の数のまま。
 */
export type ExposureOptions = { cellGroupOf?: (groupId: string) => string };

export function buildExposureRanking(groups: readonly ExposureGroup[], involvements: readonly Involvement[], params: ExposureParams, options: ExposureOptions = {}): ExposureRanking {
  const cellGroupOf = options.cellGroupOf ?? ((id: string) => id);
  checkParams(params);
  const groupById = new Map<string, ExposureGroup>();
  for (const g of groups) {
    if (groupById.has(g.id)) throw new Error(`群の ID が重複：${g.id}`);
    const s = g.diff;
    if (!Number.isInteger(g.lawCount) || g.lawCount < 1) throw new Error(`群の法律の本数が正の整数でない：${g.id} ${g.lawCount}`);
    if (![s.low, s.median, s.high].every(Number.isFinite) || s.low > s.median || s.median > s.high) throw new Error(`群の額の幅が不正：${g.id}`);
    groupById.set(g.id, g);
  }
  // 群 → 法律 → 枠（役割。賛成・反対は院つき）→ 関与。
  const slotKey = (role: ExposureRole, house?: House) => (role === 'yes' || role === 'no' ? `${role}:${house}` : role);
  const slotsOf = (role: ExposureRole): { house?: House; share: number }[] =>
    role === 'yes' || role === 'no' ? [{ house: 'lower', share: HOUSE_SPLIT }, { house: 'upper', share: 1 - HOUSE_SPLIT }] : [{ share: 1 }];
  const tree = new Map<string, Map<string, Map<string, Involvement[]>>>();
  for (const inv of involvements) {
    if (!groupById.has(inv.groupId)) throw new Error(`関与の群が群の一覧に無い：${inv.groupId}`);
    if (!EXPOSURE_ROLES.includes(inv.role)) throw new Error(`役割が不正：${inv.role}`);
    if (inv.actorKind !== 'person' && inv.actorKind !== 'party' && inv.actorKind !== 'none') throw new Error(`配り先の種類が不正：${inv.actorKind}`);
    if (!Number.isFinite(inv.weight) || inv.weight <= 0) throw new Error(`重みが不正：${inv.actorId} ${inv.lawId} ${inv.weight}`);
    if (!inv.lawId || (inv.actorKind !== 'none' && !inv.actorId)) throw new Error('関与に配り先か法律の ID が無い');
    if ((inv.role === 'yes' || inv.role === 'no') && inv.house !== 'lower' && inv.house !== 'upper') throw new Error(`賛成・反対の関与に院が無い：${inv.actorId} ${inv.lawId}`);
    const laws = tree.get(inv.groupId) ?? new Map<string, Map<string, Involvement[]>>();
    const slots = laws.get(inv.lawId) ?? new Map<string, Involvement[]>();
    const key = slotKey(inv.role, inv.house);
    const list = slots.get(key) ?? [];
    list.push(inv);
    slots.set(key, list);
    laws.set(inv.lawId, slots);
    tree.set(inv.groupId, laws);
  }

  type Acc = { kind: ActorKind; id: string; total: Range; laws: Set<string>; groupIds: Set<string>; byLaw: Map<string, number>; cells: Map<string, { groupId: string; role: ExposureRole; laws: Set<string>; exposure: Range }> };
  const actors = new Map<string, Acc>();
  const give = (inv: Involvement, amount: Range) => {
    const key = `${inv.actorKind}\u0000${inv.actorId}`;
    const a = actors.get(key) ?? { kind: inv.actorKind, id: inv.actorId, total: zero(), laws: new Set<string>(), groupIds: new Set<string>(), byLaw: new Map<string, number>(), cells: new Map() };
    a.total = add(a.total, amount);
    a.laws.add(inv.lawId);
    a.groupIds.add(inv.groupId);
    // 法律ごとの寄与（全群・全役割の median の和）。上位3本の占有率を出すためだけに持ち、出力しない。
    a.byLaw.set(inv.lawId, (a.byLaw.get(inv.lawId) ?? 0) + amount.median);
    const cellGroup = cellGroupOf(inv.groupId);
    const cellKey = `${cellGroup}\u0000${inv.role}`;
    const c = a.cells.get(cellKey) ?? { groupId: cellGroup, role: inv.role, laws: new Set<string>(), exposure: zero() };
    c.laws.add(inv.lawId);
    c.exposure = add(c.exposure, amount);
    a.cells.set(cellKey, c);
    actors.set(key, a);
  };

  const unallocated: Unallocated[] = [];
  // 役割・院ごとの未配分（同じ群・役割・院・理由は1行にまとめる。laws は重ならない本数）。
  const pending = new Map<string, { groupId: string; role: ExposureRole; house?: House; reason: string; laws: Set<string>; exposureYen: Range }>();
  const pend = (groupId: string, role: ExposureRole, house: House | undefined, reason: string, lawId: string, amount: Range) => {
    const key = `${groupId}\u0000${role}\u0000${house ?? ''}\u0000${reason}`;
    const e = pending.get(key) ?? { groupId, role, house, reason, laws: new Set<string>(), exposureYen: zero() };
    e.laws.add(lawId);
    e.exposureYen = add(e.exposureYen, amount);
    pending.set(key, e);
  };
  const MISSING_REASON = { lower: '衆議院の賛否の記録が無い法律の枠', upper: '参議院の賛否の記録が無い法律の枠' } as const;
  // 群の額を全役割へ配り切ったときの合計。反対は端が入れ替わるので、役割ごとに幅を作ってから足す（先に比率を足し引きすると幅が合わない）。
  const allRoles = (s: Range): Range => EXPOSURE_ROLES.reduce((acc, r) => add(acc, scale(s, SIGN[r] * params.roleRatio[r])), zero());
  let expected = zero();
  for (const g of groups) {
    expected = add(expected, allRoles(g.diff));
    const laws = tree.get(g.id) ?? new Map<string, Map<string, Involvement[]>>();
    if (g.lawCount < laws.size) throw new Error(`群の法律の本数が関与の記録がある法律の本数より小さい：${g.id} ${g.lawCount}<${laws.size}`);
    const perLaw = 1 / g.lawCount;
    const noRecord = g.lawCount - laws.size;
    if (noRecord > 0) {
      unallocated.push({ groupId: g.id, role: null, laws: noRecord, exposureYen: scale(allRoles(g.diff), perLaw * noRecord), reason: 'この群の法律のうち関与の記録が無い法律の枠' });
    }
    for (const [lawId, slots] of laws) {
      for (const role of EXPOSURE_ROLES) {
        if (params.roleRatio[role] === 0) continue;
        for (const { house, share } of slotsOf(role)) {
          const slot = scale(g.diff, perLaw * SIGN[role] * params.roleRatio[role] * share);
          const list = slots.get(slotKey(role, house));
          if (!list) { pend(g.id, role, house, house ? MISSING_REASON[house] : 'この役割の関与の記録が無い法律の枠', lawId, slot); continue; }
          const totalWeight = list.reduce((x, y) => x + y.weight, 0);
          if (!Number.isFinite(totalWeight)) throw new Error(`重みの合計が有限でない：${g.id}`);
          for (const inv of list) {
            const amount = scale(slot, inv.weight / totalWeight);
            if (inv.actorKind === 'none') pend(g.id, role, house, inv.noneReason ?? '同姓同名で人物台帳に結べない票', lawId, amount);
            else give(inv, amount);
          }
        }
      }
    }
  }
  for (const e of pending.values()) unallocated.push({ groupId: e.groupId, role: e.role, ...(e.house ? { house: e.house } : {}), laws: e.laws.size, exposureYen: e.exposureYen, reason: e.reason });

  const topThree = (byLaw: Map<string, number>): number => {
    const abs = [...byLaw.values()].map(Math.abs).sort((x, y) => y - x);
    const all = abs.reduce((x, y) => x + y, 0);
    return all > 0 ? (abs[0] + (abs[1] ?? 0) + (abs[2] ?? 0)) / all : 0;
  };
  const toRows = (kind: ActorKind): ExposureRow[] => {
    const rows = [...actors.values()].filter(a => a.kind === kind).map(a => ({
      actorKind: a.kind,
      actorId: a.id,
      exposureYen: a.total,
      laws: a.laws.size,
      groups: a.groupIds.size,
      topThreeShare: topThree(a.byLaw),
      cells: [...a.cells.values()]
        .map(c => ({ groupId: c.groupId, role: c.role, laws: c.laws.size, exposureYen: c.exposure }))
        .sort((x, y) => x.groupId.localeCompare(y.groupId) || EXPOSURE_ROLES.indexOf(x.role) - EXPOSURE_ROLES.indexOf(y.role)),
    }));
    const few = (r: { laws: number }) => r.laws < params.minLaws;
    const concentrated = (r: { laws: number; topThreeShare: number }) => !few(r) && r.topThreeShare > params.topThreeShareCap + SHARE_EPS;
    const ranked = assignTiers(rows.filter(r => !few(r) && !concentrated(r))).map(r => ({ ...r, unrankedReason: '' }));
    const unranked = rows.filter(r => few(r) || concentrated(r))
      .sort((a, b) => b.exposureYen.median - a.exposureYen.median || a.actorId.localeCompare(b.actorId))
      .map(r => ({
        ...r, tier: null,
        unrankedReason: few(r)
          ? `関与した法律が${params.minLaws}本に満たない（${r.laws}本）`
          : `上位3本の占有率が${pct(params.topThreeShareCap)}を超える（${pct(r.topThreeShare)}）`,
      }));
    return [...ranked, ...unranked];
  };
  const people = toRows('person');
  const parties = toRows('party');
  const sum = (rs: { exposureYen: Range }[]) => rs.reduce((s, r) => add(s, r.exposureYen), zero());
  return {
    schema: 'exposure-ranking/v1',
    claim: 'descriptive',
    disclaimer: EXPOSURE_DISCLAIMER,
    params: { roleRatio: { ...params.roleRatio }, minLaws: params.minLaws, topThreeShareCap: params.topThreeShareCap },
    people,
    parties,
    unallocated,
    totals: { people: sum(people), parties: sum(parties), unallocated: sum(unallocated), expected },
  };
}

// ---------------------------------------------------------------------------------------------
// 公開用：書き出す JSON はこの形にする。法律1本ぶんの額（関与した法律が1本の人の額、本数の少ない内訳の額）を出さない。
// ---------------------------------------------------------------------------------------------
export type PublicExposureCell = { groupId: string; role: ExposureRole; laws: number; /** 額を出さないときは null。 */ exposureYen: Range | null };
export type PublicExposureRow = Omit<ExposureRow, 'exposureYen' | 'cells'> & {
  /** 階層に入らない行は null（本数・群の数・理由だけを出す）。 */
  exposureYen: Range | null;
  cells: PublicExposureCell[];
};
/** 額を出さない人（または会派）の合計。count は件数。額を出さない行が全体で1つだけのときは exposureYen を伏せて null にする。 */
export type HiddenTotal = { count: number; exposureYen: Range | null };
/**
 * 未配分の見せる単位：群×役割の合計（院と理由は束ねる）。本数（「N本ぶんの枠」）は出さない。
 * 束ねても関与した法律が下限（minLaws）に満たない群×役割は、群を分けずに役割ごとの1行（groupId: null）へまとめる（1本ぶんの枠の額を行として出さないため）。
 */
export type UnallocatedSummary = { groupId: string | null; role: ExposureRole | null; reasons: string[]; exposureYen: Range };
export type PublicUnallocated = Omit<UnallocatedSummary, 'exposureYen'> & { exposureYen: Range | null };

/**
 * 未配分を群×役割の合計に束ねる（純関数）。合計の額は束ねる前と同じ。
 * 群×役割の本数は、束ねる前の行（院・理由ごと）の本数の最大で見る。和集合は最大以上なので、下限を満たすと判定した行は必ず満たす（逆は少なめに見て役割ごとの1行へ回す）。
 */
export function summarizeUnallocated(rows: readonly Unallocated[], minLaws: number): UnallocatedSummary[] {
  type Acc = { groupId: string; role: ExposureRole | null; laws: number; reasons: Set<string>; exposureYen: Range };
  const byCell = new Map<string, Acc>();
  for (const u of rows) {
    const key = `${u.groupId}\u0000${u.role ?? ''}`;
    const a = byCell.get(key) ?? { groupId: u.groupId, role: u.role, laws: 0, reasons: new Set<string>(), exposureYen: zero() };
    a.laws = Math.max(a.laws, u.laws);
    a.reasons.add(u.reason);
    a.exposureYen = add(a.exposureYen, u.exposureYen);
    byCell.set(key, a);
  }
  const shown: UnallocatedSummary[] = [];
  const few = new Map<string, { role: ExposureRole | null; reasons: Set<string>; exposureYen: Range }>();
  for (const a of byCell.values()) {
    if (a.laws >= minLaws) { shown.push({ groupId: a.groupId, role: a.role, reasons: [...a.reasons].sort(), exposureYen: a.exposureYen }); continue; }
    const key = a.role ?? '';
    const f = few.get(key) ?? { role: a.role, reasons: new Set<string>(), exposureYen: zero() };
    a.reasons.forEach(r => f.reasons.add(r));
    f.exposureYen = add(f.exposureYen, a.exposureYen);
    few.set(key, f);
  }
  const order = (r: ExposureRole | null) => (r === null ? -1 : EXPOSURE_ROLES.indexOf(r));
  shown.sort((x, y) => (x.groupId ?? '').localeCompare(y.groupId ?? '') || order(x.role) - order(y.role));
  const rest = [...few.values()].sort((x, y) => order(x.role) - order(y.role))
    .map(f => ({ groupId: null, role: f.role, reasons: [`関与した法律が${minLaws}本に満たない群をまとめた合計`, ...[...f.reasons].sort()], exposureYen: f.exposureYen }));
  return [...shown, ...rest];
}
export type PublicExposureRanking = Omit<ExposureRanking, 'people' | 'parties' | 'totals' | 'unallocated'> & {
  people: PublicExposureRow[];
  parties: PublicExposureRow[];
  /** 額を出さない人・会派（階層に入らない行）の合計。 */
  hidden: { people: HiddenTotal; parties: HiddenTotal };
  /** 未配分の内訳（群×役割の合計。summarizeUnallocated）。額を出さない行が合わせて1つだけのときは額を null にする。 */
  unallocated: PublicUnallocated[];
  /** 全員ぶんの合計。額を出さない行が合わせて1つだけのときは、どの合計からでも引き算で読めるので全部 null。 */
  totals: { people: Range | null; parties: Range | null; unallocated: Range | null; expected: Range | null };
};

/** 画面部品（ExposureRankingPanel）の入力：未配分だけ群×役割の合計（summarizeUnallocated）にしたもの。 */
export type PanelExposureRanking = Omit<ExposureRanking, 'unallocated'> & { unallocated: UnallocatedSummary[] };
export const toPanelExposureRanking = (ranking: ExposureRanking): PanelExposureRanking =>
  ({ ...ranking, unallocated: summarizeUnallocated(ranking.unallocated, ranking.params.minLaws) });

/** 内訳の額を出してよいか：本数が下限に満たない内訳が1つも無いこと。 */
const cellsShowable = (cells: readonly ExposureCell[], minLaws: number): boolean => cells.every(c => c.laws >= minLaws);

/**
 * 集計結果を公開用に変える（純関数。入力は変えない）。
 * - 階層に入らない行（tier null）：exposureYen と cells の額を出さない（laws・groups・unrankedReason・cells の本数と役割は残す）。
 * - 階層に入った行：内訳に本数が minLaws 未満のものが1つでもあれば、内訳の額を全部出さない。
 * - 額を出さない人・会派の合計を hidden に件数つきで足す。額を出さない行が人・会派を合わせて1つだけのときは、
 *   hidden の額、totals の全部（expected・unallocated を含む）、未配分の内訳の額を null にする（expected − unallocated − 出ている額 で読めるため）。
 * - 未配分は群×役割の合計に束ね、本数を出さない。本数が minLaws に満たない群×役割は役割ごとの1行にまとめる（summarizeUnallocated）。
 */
export function toPublicExposureRanking(ranking: ExposureRanking, minLaws: number): PublicExposureRanking {
  const toRow = (r: ExposureRow): PublicExposureRow => {
    const ranked = r.tier !== null;
    const show = ranked && cellsShowable(r.cells, minLaws);
    return {
      ...r,
      exposureYen: ranked ? r.exposureYen : null,
      cells: r.cells.map(c => ({ groupId: c.groupId, role: c.role, laws: c.laws, exposureYen: show ? c.exposureYen : null })),
    };
  };
  const hiddenRows = (rows: readonly ExposureRow[]) => rows.filter(r => r.tier === null);
  const sumOf = (rows: readonly ExposureRow[]): Range => rows.reduce((s, r) => add(s, r.exposureYen), zero());
  const hp = hiddenRows(ranking.people);
  const pp = hiddenRows(ranking.parties);
  const withheld = hp.length + pp.length === 1;
  return {
    ...ranking,
    people: ranking.people.map(toRow),
    parties: ranking.parties.map(toRow),
    hidden: {
      people: { count: hp.length, exposureYen: withheld ? null : sumOf(hp) },
      parties: { count: pp.length, exposureYen: withheld ? null : sumOf(pp) },
    },
    unallocated: summarizeUnallocated(ranking.unallocated, minLaws).map(u => ({ ...u, exposureYen: withheld ? null : u.exposureYen })),
    totals: {
      people: withheld ? null : ranking.totals.people,
      parties: withheld ? null : ranking.totals.parties,
      unallocated: withheld ? null : ranking.totals.unallocated,
      expected: withheld ? null : ranking.totals.expected,
    },
  };
}
