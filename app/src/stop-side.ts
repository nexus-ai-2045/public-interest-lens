/** 技術を止めた側の記録と規制をめぐる判決（/stop-side）。配布ファイル stop-side.json は scripts/build_public_stop_side.py が作る。 */
export const distributionStopSideUrl = '/distribution/stop-side.json';

export type CheckState = 'c' | 'h' | 'u';
export type StopActor = {
  /** 行の識別（照合結果の行ハッシュ。重複行は同じ値になる）。 */
  h: string; g: string; v: CheckState;
  o: string; d?: string; s?: string; t?: string; x?: string; k?: string; l?: string; a?: string; p?: string;
  /** 一次資料（官公庁の資料）の URL。 */
  u?: string;
  /** 保留の理由（照合で見つかった食い違いの型）。 */
  r?: string;
};
export type StopRuling = {
  id: string; name: string; rule: string; court: string; date: string; no: string; judge: string; summary: string; check: string;
  agency?: string; field?: string; kind?: string; result?: string; after?: string; u?: string; fulltext?: 'no';
};
export type StopGroup = { key: string; label: string; about: string };
export type StopSide = {
  schema: 'public-stop-side/v1'; notes: string[]; counts: Record<string, number>;
  groups: StopGroup[]; actors: StopActor[]; rulings: StopRuling[]; rulingsHeld: { id: string; name: string; reason: string }[];
};

export const CHECK_LABEL: Record<CheckState, string> = { c: '確認済み', h: '保留', u: '未照合' };
export const CHECK_NOTE: Record<CheckState, string> = {
  c: '原本と機械の照合＋AI2系統がすべて一致',
  h: '照合で食い違いが見つかった。中身は未確定',
  u: 'まだ原本と照らしていない',
};

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const httpsOnly = (url: unknown) => url === undefined || (typeof url === 'string' && /^https:\/\//.test(url));

/** 形式が不正なら全体を読み込みません。URL は https だけ、確認の印は3種だけ通します。 */
export function parseStopSide(text: string): StopSide {
  if (text.length > 4_000_000) throw new Error('止めた側のデータが大きすぎます。');
  const v = JSON.parse(text) as unknown;
  if (!isRecord(v) || v.schema !== 'public-stop-side/v1' || !Array.isArray(v.actors) || !Array.isArray(v.rulings) || !Array.isArray(v.groups) || !Array.isArray(v.rulingsHeld) || !Array.isArray(v.notes) || !isRecord(v.counts)) throw new Error('止めた側のデータの形式が不正です。');
  const groups = new Set((v.groups as StopGroup[]).map(g => g.key));
  for (const a of v.actors as StopActor[]) {
    if (!isRecord(a) || typeof a.h !== 'string' || typeof a.o !== 'string' || !groups.has(a.g) || !['c', 'h', 'u'].includes(a.v)) throw new Error('記録の項目が不正です。');
    if (!httpsOnly(a.u)) throw new Error('出典の URL が不正です。');
  }
  for (const r of v.rulings as StopRuling[]) {
    if (!isRecord(r) || typeof r.id !== 'string' || typeof r.name !== 'string' || typeof r.date !== 'string') throw new Error('判決の項目が不正です。');
    if (!httpsOnly(r.u)) throw new Error('判決の URL が不正です。');
  }
  return v as unknown as StopSide;
}

export type ActorFilter = { group: string; state: CheckState | 'all'; query: string };

/** 検索語は空白で分けた全部が、主体・件名・要旨・技術・法令・相手のどこかに入る行に当てる。 */
export function filterActors(actors: StopActor[], f: ActorFilter): StopActor[] {
  const words = f.query.split(/[\s　]+/).filter(Boolean);
  return actors.filter(a => {
    if (f.group !== 'all' && a.g !== f.group) return false;
    if (f.state !== 'all' && a.v !== f.state) return false;
    if (!words.length) return true;
    const hay = [a.o, a.t, a.x, a.k, a.l, a.a, a.s].filter(Boolean).join(' ');
    return words.every(w => hay.includes(w));
  });
}

export function countByState(actors: StopActor[]): Record<CheckState, number> {
  const out: Record<CheckState, number> = { c: 0, h: 0, u: 0 };
  for (const a of actors) out[a.v] += 1;
  return out;
}

/** 規制への判断は、括弧書きの説明を除いた頭の語で分ける。 */
export const rulingKind = (r: StopRuling): string => r.judge.replace(/（.*$/, '').trim() || 'その他';

export function filterRulings(rulings: StopRuling[], kind: string, query: string): StopRuling[] {
  const words = query.split(/[\s　]+/).filter(Boolean);
  return rulings.filter(r => {
    if (kind !== 'all' && rulingKind(r) !== kind) return false;
    const hay = [r.name, r.rule, r.court, r.field, r.summary, r.no].filter(Boolean).join(' ');
    return words.every(w => hay.includes(w));
  });
}
