/** 全法律の結果一覧（law-outcomes.json）の型と、施行年での絞り込み・結果別の並べ替え。/history の「この期間に施行された法律・政策と評価」が使う。 */

export const lawOutcomesUrl = '/distribution/law-outcomes.json';
export type OutcomeResult = '額あり' | '保留' | '測定できない' | '評価対象外' | '効果なし（定例）';
export const RESULT_ORDER: OutcomeResult[] = ['額あり', '効果なし（定例）', '保留', '測定できない', '評価対象外'];
/** 先に出す「評価が出ているもの」。残りは「その他」に畳む。 */
export const EVALUATED_RESULTS: OutcomeResult[] = ['額あり', '効果なし（定例）'];
export type LawOutcome = {
  id: string; title: string; field: string; indicator: string; certainty: string; result: OutcomeResult; reason: string; route: string;
  enforced: string; kind: string; stage: string; direction: string; side: 'loss' | 'benefit' | null; median: number | null; unit: string; publishable: boolean;
};
export type LawOutcomes = { schema: 'law-outcomes/v1'; counts: Record<OutcomeResult, number>; items: LawOutcome[] };

export function parseLawOutcomes(text: string): LawOutcomes {
  const data = JSON.parse(text) as LawOutcomes;
  if (data?.schema !== 'law-outcomes/v1' || !Array.isArray(data.items)) throw new Error('law-outcomes.json の形が違います');
  for (const item of data.items) if (typeof item.id !== 'string' || !RESULT_ORDER.includes(item.result)) throw new Error(`行の形が違います: ${String(item.id)}`);
  return data;
}

/** 参考の額か。確かさに「参考」を含む、または公開不可。合計には足さない。 */
export const isReferenceAmount = (item: LawOutcome) => item.result === '額あり' && (item.certainty.includes('参考') || !item.publishable);
export const enforcedYear = (item: LawOutcome): number | null => (/^\d{4}/.test(item.enforced) ? Number(item.enforced.slice(0, 4)) : null);

/** 施行年が from〜to（両端を含む）の行。施行日が不明の行は、期間に入るか判断できないので含めない（件数は別に返す）。 */
export function enforcedBetween(items: LawOutcome[], from: number, to: number): { inRange: LawOutcome[]; unknownDate: number } {
  const inRange: LawOutcome[] = [];
  let unknownDate = 0;
  for (const item of items) {
    const year = enforcedYear(item);
    if (year === null) unknownDate += 1; else if (year >= from && year <= to) inRange.push(item);
  }
  return { inRange, unknownDate };
}

export function countByResult(items: LawOutcome[]): Record<OutcomeResult, number> {
  const counts = Object.fromEntries(RESULT_ORDER.map(key => [key, 0])) as Record<OutcomeResult, number>;
  for (const item of items) counts[item.result] += 1;
  return counts;
}

/** 結果別の並び。額あり：確かな額 → 額の絶対値の大きい順。ほか：施行日の新しい順、同じなら id。 */
export function sortWithinResult(items: LawOutcome[]): LawOutcome[] {
  return [...items].sort((a, b) => Number(isReferenceAmount(a)) - Number(isReferenceAmount(b)) || Math.abs(b.median ?? 0) - Math.abs(a.median ?? 0) || (a.enforced < b.enforced ? 1 : a.enforced > b.enforced ? -1 : 0) || (a.id < b.id ? -1 : 1));
}

export function groupByResult(items: LawOutcome[]): Record<OutcomeResult, LawOutcome[]> {
  const groups = Object.fromEntries(RESULT_ORDER.map(key => [key, [] as LawOutcome[]])) as Record<OutcomeResult, LawOutcome[]>;
  for (const item of items) groups[item.result].push(item);
  for (const key of RESULT_ORDER) groups[key] = sortWithinResult(groups[key]);
  return groups;
}

/** 結果ごとの理由の内訳（同じ理由の文を数えて多い順。数字入りの理由は先頭の区切りまでで束ねる）。 */
export function reasonBreakdown(items: LawOutcome[], limit = 5): { reason: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = item.reason.split(/[：（／。]/)[0].trim() || item.reason;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts].map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count || (a.reason < b.reason ? -1 : 1)).slice(0, limit);
}
