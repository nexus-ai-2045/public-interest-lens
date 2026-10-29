/** 公約と成立法の対応（/pledges）。配布ファイル pledges.json は scripts/build_public_pledges.py が作る。点数・順位には入れない。 */
export const distributionPledgesUrl = '/distribution/pledges.json';

export type PledgeStatus = 'enacted' | 'review' | 'none' | 'no_law';
export type PledgeLaw = { id: string; title: string; url: string; stance: 'yes' | 'no' | 'split' | 'none' };
export type PledgeItem = { id: string; text: string; status: PledgeStatus; judges: string[]; laws: PledgeLaw[] };
export type PledgeParty = { name: string; governing: boolean; source: { url: string; note: string; observedAt: string }; total: number; counts: Record<PledgeStatus, number>; items: PledgeItem[] };
export type PublicPledges = { schema: 'public-pledges/v1'; election: { name: string; date: string }; lawsAsOf: string; notes: string[]; parties: PledgeParty[] };

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const STATUSES: PledgeStatus[] = ['enacted', 'review', 'none', 'no_law'];

/** 形式が不正なら全体を読み込みません。件数は項目から数え直して照合します。 */
export function parsePledges(text: string): PublicPledges {
  if (text.length > 6_000_000) throw new Error('公約データが大きすぎます。');
  const v = JSON.parse(text) as unknown;
  if (!isRecord(v) || v.schema !== 'public-pledges/v1' || !Array.isArray(v.parties) || !Array.isArray(v.notes) || !isRecord(v.election)) throw new Error('公約データの形式が不正です。');
  for (const p of v.parties as PledgeParty[]) {
    if (!isRecord(p) || typeof p.name !== 'string' || !Array.isArray(p.items) || !isRecord(p.counts)) throw new Error('党の項目が不正です。');
    if (p.source.url && !/^https:\/\//.test(p.source.url)) throw new Error('出典の URL が不正です。');
    for (const s of STATUSES) if (p.items.filter(i => i.status === s).length !== p.counts[s]) throw new Error('件数が項目と合いません。');
    if (p.total !== p.items.length) throw new Error('総数が項目と合いません。');
    for (const i of p.items) for (const l of i.laws) if (!/^https:\/\//.test(l.url)) throw new Error('出典の URL が不正です。');
  }
  return v as unknown as PublicPledges;
}

const pct = (n: number, d: number) => d > 0 ? Math.round(n / d * 100) : null;
/** 成立の割合を幅で返す。確定＝一致した成立のみ、上限＝要確認が全部成立だった場合、法律不要を除いた分母も併記。 */
export function pledgeRates(p: PledgeParty) {
  const { enacted, review, no_law } = p.counts;
  return { confirmed: pct(enacted, p.total), upper: pct(enacted + review, p.total), measurable: pct(enacted, p.total - no_law), measurableDenominator: p.total - no_law };
}
/** 成立した対応法のうち、その党が衆院で賛成側にいた本数（重複する法律は1本）。 */
export function stanceTally(p: PledgeParty) {
  const seen = new Map<string, PledgeLaw['stance']>();
  for (const i of p.items) if (i.status === 'enacted') for (const l of i.laws) seen.set(l.id, l.stance);
  const t = { yes: 0, no: 0, split: 0, none: 0 };
  for (const s of seen.values()) t[s]++;
  return { laws: seen.size, ...t };
}
