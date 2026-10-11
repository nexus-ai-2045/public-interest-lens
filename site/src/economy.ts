import raw from './data/economy-jpn.json';

/** 実在データ（世界銀行 WDI、日本）。人物・政策の評価には使いません。 */
export interface Point { year: number; value: number }
export interface Series { id: string; label: string; unit: string; sourceUrl: string; points: Point[] }

export const economy = raw as unknown as {
  observedAt: string;
  provider: string;
  country: string;
  note: string;
  series: Series[];
};

export function seriesById(id: string): Series {
  const s = economy.series.find((x) => x.id === id);
  if (!s) throw new Error(`series not found: ${id}`);
  return s;
}

/** 年平均成長率（%）。from〜to の両端の値がある場合だけ計算します。 */
export function cagr(points: Point[], from: number, to: number): number | null {
  const a = points.find((p) => p.year === from);
  const b = points.find((p) => p.year === to);
  if (!a || !b || a.value <= 0 || to <= from) return null;
  return (Math.pow(b.value / a.value, 1 / (to - from)) - 1) * 100;
}

/** 期間ごとの年平均成長率。表示用の機械計算で、原因の推定ではありません。 */
export function periodGrowth(points: Point[], edges: number[]): { from: number; to: number; rate: number | null }[] {
  const out: { from: number; to: number; rate: number | null }[] = [];
  for (let i = 0; i + 1 < edges.length; i++) out.push({ from: edges[i], to: edges[i + 1], rate: cagr(points, edges[i], edges[i + 1]) });
  return out;
}
