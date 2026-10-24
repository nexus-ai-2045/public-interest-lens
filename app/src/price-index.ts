/** 物価の換算表（scripts/build_price_index.py が作る price-index.json、計算方法の仕様 price-v1）。 */
export type PriceIndex = { schema: 'price-index/v1'; latestYear: number; sourceUrl: string; deflator: Record<string, number> };

export const priceIndexUrl = '/distribution/price-index.json';

export function parsePriceIndex(raw: unknown): PriceIndex {
  const data = raw as PriceIndex;
  if (!data || data.schema !== 'price-index/v1' || typeof data.latestYear !== 'number' || !data.deflator || typeof data.deflator !== 'object') throw new Error('物価の換算表の形が不正です。');
  for (const [year, value] of Object.entries(data.deflator)) if (!/^\d{4}$/.test(year) || !(typeof value === 'number' && value > 0)) throw new Error('物価の換算表の値が不正です。');
  if (!data.deflator[String(data.latestYear)]) throw new Error('最新年の物価がありません。');
  return data;
}

/** 額の窓「2005〜2014年」の開始前の年（額の円の年）。 */
export function windowBaseYear(window: string | undefined): number | null {
  const m = window?.match(/^(\d{4})/);
  return m ? Number(m[1]) - 1 : null;
}

/** b 年の円を最新年の円に直す（P_T / P_b を掛ける）。表に b 年が無ければ null（換算しない）。 */
export function toLatestYen(amount: number, baseYear: number | null, index: PriceIndex): number | null {
  if (baseYear === null) return null;
  const from = index.deflator[String(baseYear)];
  const to = index.deflator[String(index.latestYear)];
  return from && to ? Math.round(amount * to / from) : null;
}

let pending: Promise<PriceIndex> | null = null;
export function loadPriceIndex(): Promise<PriceIndex> {
  pending ??= fetch(priceIndexUrl).then(async r => { if (!r.ok) throw new Error('missing'); return parsePriceIndex(await r.json()); }).catch(e => { pending = null; throw e; });
  return pending;
}
