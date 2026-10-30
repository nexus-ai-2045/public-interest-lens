// 「全議員」の表の絞り込み・並べ替え（画面に依存しない部分）。
import type { PublicMember } from './members-build';
import type { ReferenceMember } from './members-reference';

export const distributionReferenceUrl = '/distribution/members-reference.json';

export type HouseFilter = 'all' | '衆議院' | '参議院' | 'former';
export type SortKey = 'reference-loss' | 'reference-benefit' | 'confirmed' | 'laws' | 'name';
export const SORT_LABEL: Record<SortKey, string> = {
  'reference-loss': '参考の額：国賊側から', 'reference-benefit': '参考の額：国士側から', confirmed: '確かな額：国賊側から', laws: '関わった法律の多い順', name: '名前順',
};
export type Row = ReferenceMember & { confirmed: number | null; confirmedRank: number | null };

const zeroRange = { low: 0, median: 0, high: 0 };
/**
 * 参考の表に、確かな額（members.json の純額の中央値と順位）を人物IDで付ける。確かな額の無い人は null。
 * 氏名の文字列では結ばない（同姓同名の別人を取り違えない）。
 * 確かな額だけがあり参考の表にいない人（元職で、参考の額の法律に記録がない人）も、参考の額0円の行として足す。
 */
export function joinConfirmed(reference: ReferenceMember[], confirmed: PublicMember[]): Row[] {
  const byId = new Map(confirmed.map(m => [m.id, m]));
  const rows: Row[] = reference.map(r => { const c = byId.get(r.id); return { ...r, confirmed: c ? c.net.median : null, confirmedRank: c ? c.rank : null }; });
  const seen = new Set(reference.map(r => r.id));
  for (const [id, c] of byId) {
    if (seen.has(id)) continue;
    rows.push({ id, name: c.name, current: null, lastSangiinParty: '', lastKnownCaucus: null, loss: zeroRange, credit: zeroRange, net: zeroRange, laws: 0, top: [],
      reason: '参考の額の法律で、提出者・参議院の賛成としての記録がない', confirmed: c.net.median, confirmedRank: c.rank });
  }
  return rows;
}

/** 元職の所属の説明。記録のある最後の年の会派（国会会議録）を優先し、無ければ参議院の最終会派。どちらも無ければ空。 */
export function formerNote(r: Pick<ReferenceMember, 'lastKnownCaucus' | 'lastSangiinParty'>): string {
  if (r.lastKnownCaucus) return `${r.lastKnownCaucus.date.slice(0, 4)}年の会派：${r.lastKnownCaucus.name}`;
  return r.lastSangiinParty ? `参議院の最終会派：${r.lastSangiinParty}` : '';
}

export function partiesOf(rows: Row[]): string[] {
  const count = new Map<string, number>();
  for (const r of rows) if (r.current) count.set(r.current.party, (count.get(r.current.party) ?? 0) + 1);
  return [...count].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([p]) => p);
}

/** 額のある人（「額のある人だけ」の絞り込みと同じ決まり）。 */
const hasAmount = (r: Row): boolean => r.laws > 0 || r.confirmed !== null;

export type Breakdown = { total: number; current: number; currentWithAmount: number; shu: number; shuWithAmount: number; san: number; sanWithAmount: number; confirmed: number; withAmount: number };
/** 表の先頭に出す内訳。公開人数・現職・額のある現職（院別）・確かな額のある人。 */
export function breakdownOf(rows: Row[]): Breakdown {
  const out: Breakdown = { total: rows.length, current: 0, currentWithAmount: 0, shu: 0, shuWithAmount: 0, san: 0, sanWithAmount: 0, confirmed: 0, withAmount: 0 };
  for (const r of rows) {
    if (r.confirmed !== null) out.confirmed += 1;
    if (hasAmount(r)) out.withAmount += 1;
    if (!r.current) continue;
    out.current += 1;
    const amount = hasAmount(r) ? 1 : 0;
    out.currentWithAmount += amount;
    if (r.current.house === '衆議院') { out.shu += 1; out.shuWithAmount += amount; } else { out.san += 1; out.sanWithAmount += amount; }
  }
  return out;
}

export function filterRows(rows: Row[], o: { house: HouseFilter; party: string; query: string; withAmount: boolean }): Row[] {
  const words = o.query.trim().split(/[\s　]+/).filter(Boolean);
  return rows.filter(r => {
    if (o.house === 'former' ? r.current !== null : o.house !== 'all' && r.current?.house !== o.house) return false;
    if (o.party && r.current?.party !== o.party) return false;
    if (o.withAmount && !hasAmount(r)) return false;
    const hay = `${r.name} ${r.current?.party ?? ''} ${r.current?.district ?? ''} ${formerNote(r)}`;
    return words.every(w => hay.includes(w));
  });
}

export function sortRows(rows: Row[], key: SortKey): Row[] {
  const by = (f: (r: Row) => number) => (a: Row, b: Row) => f(a) - f(b) || a.name.localeCompare(b.name, 'ja');
  const sorted = [...rows];
  if (key === 'reference-loss') sorted.sort(by(r => r.net.median));
  else if (key === 'reference-benefit') sorted.sort(by(r => -r.net.median));
  else if (key === 'confirmed') sorted.sort(by(r => r.confirmed ?? Number.POSITIVE_INFINITY));
  else if (key === 'laws') sorted.sort(by(r => -r.laws));
  else sorted.sort((a, b) => a.name.localeCompare(b.name, 'ja'));
  return sorted;
}
