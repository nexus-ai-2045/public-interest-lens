/**
 * 曝露ランキング（案B）の集計器。純関数で、ファイルも通信も読まない。
 *
 * 何を出すか：議員や会派が関与した法律の属する「産業×期間の群」の伸び損ね額（OECD 同産業・同時期の中央値との差）を、
 * 役割ごとの固定比率で配った額。これは「関与していた群がどれだけ伸び損ねたか」の記述であって、
 * その人や法律が伸び損ねを起こしたという因果の推定ではない（設計確定 v2.1 の L1・L3）。
 *
 * 決まり：
 * 1. 群の額は、群に属する法律の本数 n で等分した「1本ぶんの枠」に分け、枠の中を役割の比率で分ける。
 *    枠は配るための数え方で、法律単位の額としては出さない（出力の型に法律の ID も法律ごとの額も無い）。
 * 2. 役割の比率は取り決め（つまみ①）。反対は逆向き（符号を反転）で配る。
 * 3. 1本・1役割の中は、渡された重みの割合で配る（閣議決定は閣僚に均等、のような重みは呼ぶ側が決める）。
 *    重みの合計で割るので、1本・1役割の枠は必ず配り切る。
 * 4. 配り先は人か会派のどちらか一方。個人の記録が無い賛否は会派に置き、同じ枠を人と会派へ二重に配らない。
 * 5. ある法律で関与の記録が無い役割の枠は「未配分」に理由つきで積む（黙って消さない、ほかの役割へ寄せない）。
 * 6. 幅（low・median・high）は端どうしを足す。群どうしの相関を仮定しない広めの幅になる。反対は端が入れ替わるので、
 *    検算の合計（totals.expected）も役割ごとに幅を作ってから足す。
 * 7. 階層は、額の中央値の大きい順に並べ、幅が階層の先頭の人と重なる間は同じ階層とする。
 *    群の額の幅をそのまま使った記述の階層で、統計的な同時信頼集合ではない。
 * 8. 関与した法律が下限（minLaws）に満たない人・会派は階層に入れず、額と本数だけを出す。
 */

export type Range = { low: number; median: number; high: number };
export type ExposureRole = 'proposer' | 'yes' | 'no' | 'cabinet';
export const EXPOSURE_ROLES: readonly ExposureRole[] = ['proposer', 'yes', 'no', 'cabinet'];
export type RoleRatio = Readonly<Record<ExposureRole, number>>;
/** つまみ①の初期値（設計確定 v2.1 §2）：発議0.4・賛成0.2・反対0.2（逆向き）・閣議決定0.2。 */
export const DEFAULT_ROLE_RATIO: RoleRatio = Object.freeze({ proposer: 0.4, yes: 0.2, no: 0.2, cabinet: 0.2 });
/** 反対だけ逆向き。 */
const SIGN: Readonly<Record<ExposureRole, 1 | -1>> = { proposer: 1, yes: 1, no: -1, cabinet: 1 };

/** 産業×期間の群と、その伸び損ね額（正が伸び損ね、負は中央値より伸びた）。 */
export type ExposureGroup = { id: string; industry: string; period: string; shortfallYen: Range };
export type ActorKind = 'person' | 'party';
/** 1つの関与：誰が、どの群のどの法律に、どの役割で関わったか。weight は同じ法律・同じ役割の中での重み（正の数）。 */
export type Involvement = { actorKind: ActorKind; actorId: string; groupId: string; lawId: string; role: ExposureRole; weight: number };
export type ExposureParams = { roleRatio: RoleRatio; /** 階層に入れるのに要る、関与した法律の本数の下限。 */ minLaws: number };

export type ExposureCell = { groupId: string; role: ExposureRole; laws: number; exposureYen: Range };
export type ExposureRow = {
  actorKind: ActorKind;
  actorId: string;
  exposureYen: Range;
  /** 関与した法律の本数（重複なし）と群の数。 */
  laws: number;
  groups: number;
  /** 群×役割ごとの内訳。法律ごとの額は持たない。 */
  cells: ExposureCell[];
  /** 階層（1が最も曝露が大きい）。下限に満たないときは null で、unrankedReason に理由。 */
  tier: number | null;
  unrankedReason: string;
};
export type Unallocated = { groupId: string; role: ExposureRole | null; laws: number; exposureYen: Range; reason: string };
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

const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });
/** 負の数を掛けると端が入れ替わる。 */
const scale = (r: Range, x: number): Range => (x >= 0
  ? { low: r.low * x, median: r.median * x, high: r.high * x }
  : { low: r.high * x, median: r.median * x, high: r.low * x });

const EPS = 1e-9;

function checkParams(p: ExposureParams): void {
  let sum = 0;
  for (const r of EXPOSURE_ROLES) {
    const v = p.roleRatio[r];
    if (!Number.isFinite(v) || v < 0) throw new Error(`役割の比率が不正：${r}=${v}`);
    sum += v;
  }
  if (Math.abs(sum - 1) > EPS) throw new Error(`役割の比率の合計が1でない：${sum}`);
  if (!Number.isInteger(p.minLaws) || p.minLaws < 1) throw new Error(`法律の本数の下限が不正：${p.minLaws}`);
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

export function buildExposureRanking(groups: readonly ExposureGroup[], involvements: readonly Involvement[], params: ExposureParams): ExposureRanking {
  checkParams(params);
  const groupById = new Map<string, ExposureGroup>();
  for (const g of groups) {
    if (groupById.has(g.id)) throw new Error(`群の ID が重複：${g.id}`);
    const s = g.shortfallYen;
    if (![s.low, s.median, s.high].every(Number.isFinite) || s.low > s.median || s.median > s.high) throw new Error(`群の額の幅が不正：${g.id}`);
    groupById.set(g.id, g);
  }
  // 群 → 法律 → 役割 → 関与。
  const tree = new Map<string, Map<string, Map<ExposureRole, Involvement[]>>>();
  for (const inv of involvements) {
    if (!groupById.has(inv.groupId)) throw new Error(`関与の群が群の一覧に無い：${inv.groupId}`);
    if (!EXPOSURE_ROLES.includes(inv.role)) throw new Error(`役割が不正：${inv.role}`);
    if (inv.actorKind !== 'person' && inv.actorKind !== 'party') throw new Error(`配り先の種類が不正：${inv.actorKind}`);
    if (!Number.isFinite(inv.weight) || inv.weight <= 0) throw new Error(`重みが不正：${inv.actorId} ${inv.lawId} ${inv.weight}`);
    if (!inv.actorId || !inv.lawId) throw new Error('関与に配り先か法律の ID が無い');
    const laws = tree.get(inv.groupId) ?? new Map<string, Map<ExposureRole, Involvement[]>>();
    const roles = laws.get(inv.lawId) ?? new Map<ExposureRole, Involvement[]>();
    const list = roles.get(inv.role) ?? [];
    list.push(inv);
    roles.set(inv.role, list);
    laws.set(inv.lawId, roles);
    tree.set(inv.groupId, laws);
  }

  type Acc = { kind: ActorKind; id: string; total: Range; laws: Set<string>; cells: Map<string, { groupId: string; role: ExposureRole; laws: Set<string>; exposure: Range }> };
  const actors = new Map<string, Acc>();
  const give = (inv: Involvement, amount: Range) => {
    const key = `${inv.actorKind}\u0000${inv.actorId}`;
    const a = actors.get(key) ?? { kind: inv.actorKind, id: inv.actorId, total: zero(), laws: new Set<string>(), cells: new Map() };
    a.total = add(a.total, amount);
    a.laws.add(inv.lawId);
    const cellKey = `${inv.groupId}\u0000${inv.role}`;
    const c = a.cells.get(cellKey) ?? { groupId: inv.groupId, role: inv.role, laws: new Set<string>(), exposure: zero() };
    c.laws.add(inv.lawId);
    c.exposure = add(c.exposure, amount);
    a.cells.set(cellKey, c);
    actors.set(key, a);
  };

  const unallocated: Unallocated[] = [];
  // 群の額を全役割へ配り切ったときの合計。反対は端が入れ替わるので、役割ごとに幅を作ってから足す（先に比率を足し引きすると幅が合わない）。
  const allRoles = (s: Range): Range => EXPOSURE_ROLES.reduce((acc, r) => add(acc, scale(s, SIGN[r] * params.roleRatio[r])), zero());
  let expected = zero();
  for (const g of groups) {
    expected = add(expected, allRoles(g.shortfallYen));
    const laws = tree.get(g.id);
    if (!laws) {
      unallocated.push({ groupId: g.id, role: null, laws: 0, exposureYen: allRoles(g.shortfallYen), reason: 'この群に関与の記録がある法律が無い' });
      continue;
    }
    const perLaw = 1 / laws.size;
    const missing = new Map<ExposureRole, number>();
    for (const roles of laws.values()) {
      for (const role of EXPOSURE_ROLES) {
        const list = roles.get(role);
        if (!list) { missing.set(role, (missing.get(role) ?? 0) + 1); continue; }
        const slot = scale(g.shortfallYen, perLaw * SIGN[role] * params.roleRatio[role]);
        const totalWeight = list.reduce((s, x) => s + x.weight, 0);
        if (!Number.isFinite(totalWeight)) throw new Error(`重みの合計が有限でない：${g.id}`);
        for (const inv of list) give(inv, scale(slot, inv.weight / totalWeight));
      }
    }
    for (const [role, n] of missing) {
      if (params.roleRatio[role] === 0) continue;
      unallocated.push({ groupId: g.id, role, laws: n, exposureYen: scale(g.shortfallYen, perLaw * n * SIGN[role] * params.roleRatio[role]), reason: 'この役割の関与の記録が無い法律の枠' });
    }
  }

  const toRows = (kind: ActorKind): ExposureRow[] => {
    const rows = [...actors.values()].filter(a => a.kind === kind).map(a => ({
      actorKind: a.kind,
      actorId: a.id,
      exposureYen: a.total,
      laws: a.laws.size,
      groups: new Set([...a.cells.values()].map(c => c.groupId)).size,
      cells: [...a.cells.values()]
        .map(c => ({ groupId: c.groupId, role: c.role, laws: c.laws.size, exposureYen: c.exposure }))
        .sort((x, y) => x.groupId.localeCompare(y.groupId) || EXPOSURE_ROLES.indexOf(x.role) - EXPOSURE_ROLES.indexOf(y.role)),
    }));
    const ranked = assignTiers(rows.filter(r => r.laws >= params.minLaws)).map(r => ({ ...r, unrankedReason: '' }));
    const unranked = rows.filter(r => r.laws < params.minLaws)
      .sort((a, b) => b.exposureYen.median - a.exposureYen.median || a.actorId.localeCompare(b.actorId))
      .map(r => ({ ...r, tier: null, unrankedReason: `関与した法律が${params.minLaws}本に満たない（${r.laws}本）` }));
    return [...ranked, ...unranked];
  };
  const people = toRows('person');
  const parties = toRows('party');
  const sum = (rs: { exposureYen: Range }[]) => rs.reduce((s, r) => add(s, r.exposureYen), zero());
  return {
    schema: 'exposure-ranking/v1',
    claim: 'descriptive',
    disclaimer: EXPOSURE_DISCLAIMER,
    params: { roleRatio: { ...params.roleRatio }, minLaws: params.minLaws },
    people,
    parties,
    unallocated,
    totals: { people: sum(people), parties: sum(parties), unallocated: sum(unallocated), expected },
  };
}
