/**
 * /numbers（数字で見る）のデータ charts.json（public-charts/v1）の型と、グラフに直す計算。
 * charts.json は scripts/build_database.py がデータベースから作る。ここでは並べ替え・目盛り・単位だけを扱い、額は作らない。
 */
import { formatYen } from './laws-catalog';

export const chartsUrl = '/distribution/charts.json';

export type Side = 'loss' | 'benefit';
export type HistogramBin = { exp: number; loss: number; benefit: number };
export type TimelineYear = { year: number; laws: number; confirmedLoss: number; confirmedBenefit: number; referenceLoss: number; referenceBenefit: number };
export type ChartMember = { id: string; name: string; rank: number; net: number; low: number; high: number; loss: number; credit: number };
export type ChartRole = { role: string; kind: string; loss: number; benefit: number };
export type ChartParty = { party: string; laws: number; loss: number; benefit: number };
export type PublicCharts = {
  schema: 'public-charts/v1';
  spec: string;
  histogram: HistogramBin[];
  byCertainty: { certainty: string; loss: number; benefit: number; laws: number }[];
  timeline: TimelineYear[];
  members: ChartMember[];
  roles: ChartRole[];
  parties: ChartParty[];
  inputs: string;
};

export function parseCharts(value: unknown): PublicCharts {
  const v = value as PublicCharts;
  if (!v || v.schema !== 'public-charts/v1' || !Array.isArray(v.histogram) || !Array.isArray(v.timeline) || !Array.isArray(v.members)) throw new Error('charts.json の形が違います');
  return v;
}

export const SIDE_LABEL: Record<Side, string> = { loss: '国賊側（損失）', benefit: '国士側（便益）' };

/** 10^exp 円の桁の名前（1兆円・10兆円・1000億円…）。 */
export function magnitudeLabel(exp: number): string {
  if (exp >= 12) return `${10 ** (exp - 12)}兆円`;
  if (exp >= 8) return `${10 ** (exp - 8)}億円`;
  if (exp >= 4) return `${10 ** (exp - 4)}万円`;
  return `${10 ** exp}円`;
}

/** 目盛りのきりのよい上限（1・2・5 × 10^k）。 */
export function niceMax(value: number): number {
  if (!(value > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(value));
  for (const m of [1, 2, 5, 10]) if (m * p >= value) return m * p;
  return 10 * p;
}

export function ticks(max: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, i) => max * i / count);
}

/** 時系列の1本の向き：国士は上、国賊は下（0 を挟む）。 */
export function timelineValues(t: TimelineYear, ledger: 'confirmed' | 'reference'): { up: number; down: number } {
  return ledger === 'confirmed' ? { up: t.confirmedBenefit, down: t.confirmedLoss } : { up: t.referenceBenefit, down: t.referenceLoss };
}

/** 議員の上位：国賊の向きなら純額の小さい順、国士なら大きい順。 */
export function topMembers(members: ChartMember[], tone: 'harm' | 'benefit', n = 10): ChartMember[] {
  const list = tone === 'harm' ? members.filter(m => m.net < 0).sort((a, b) => a.net - b.net) : members.filter(m => m.net > 0).sort((a, b) => b.net - a.net);
  return list.slice(0, n);
}

/** 議員の棒の幅：純額の推計の幅がゼロをまたぐときは下限を0にする（向きが逆の可能性を消さない。MembersPage の topBars と同じ）。 */
export function memberRange(m: ChartMember): { low: number; high: number } {
  const ends = [Math.abs(m.low), Math.abs(m.high)].sort((a, b) => a - b);
  return { low: m.low < 0 && m.high > 0 ? 0 : ends[0], high: ends[1] };
}

/** 議員ページで、その議員を選んで開くリンク。 */
export function memberHref(id: string): string {
  return `/members?name=${encodeURIComponent(id)}`;
}

export const ROLE_LABEL: Record<string, string> = {
  proposer: '提出者（閣法の大臣・発議者）', vote: '参議院本会議の賛成票', 'proposer+vote': '提出者で参院でも賛成', chair: '委員長', party: '衆議院の賛成会派（党）', unidentified: '名前の確かめられない賛成票',
};

/** 配り先の内訳を、合計に対する割合で。 */
export function roleShares(roles: ChartRole[], side: Side): { role: string; label: string; value: number; share: number }[] {
  const rows = roles.map(r => ({ role: r.role, label: ROLE_LABEL[r.role] ?? r.role, value: side === 'loss' ? r.loss : r.benefit })).filter(r => r.value > 0);
  const total = rows.reduce((s, r) => s + r.value, 0) || 1;
  return rows.sort((a, b) => b.value - a.value).map(r => ({ ...r, share: r.value / total }));
}

export const yen = formatYen;
