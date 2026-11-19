/**
 * /numbers（数字で見る）のデータ charts.json（public-charts/v1）の型と、グラフに直す計算。
 * charts.json は scripts/build_database.py がデータベースから作る。ここでは並べ替え・目盛り・単位だけを扱い、額は作らない。
 */
import { formatYen } from './laws-catalog';

export const chartsUrl = '/distribution/charts.json';

/** 向きの区分。undetermined は向き未確定（産業と比較国の差の符号しか無く、法律の効果の向きの証拠が無い参考の額）で、国賊側・国士側に分けない。 */
export type Side = 'loss' | 'benefit' | 'undetermined';
export type HistogramBin = { exp: number; loss: number; benefit: number; undetermined: number };
export type TimelineYear = { year: number; laws: number; confirmedLoss: number; confirmedBenefit: number; referenceLoss: number; referenceBenefit: number; referenceUndetermined: number };
/** 時系列の切り替え。確かな額・参考（向きあり）・参考（向き未確定）は1つの軸に混ぜない。 */
export type Ledger = 'confirmed' | 'reference' | 'undetermined';
export type PublicCharts = {
  schema: 'public-charts/v2';
  spec: string;
  histogram: HistogramBin[];
  byCertainty: { certainty: string; loss: number; benefit: number; undetermined: number; laws: number }[];
  timeline: TimelineYear[];
  inputs: string;
};

export function parseCharts(value: unknown): PublicCharts {
  const v = value as PublicCharts;
  if (!v || v.schema !== 'public-charts/v2' || !Array.isArray(v.histogram) || !Array.isArray(v.timeline)) throw new Error('charts.json の形が違います');
  return v;
}

export const SIDE_LABEL: Record<Side, string> = { loss: '国賊側（損失）', benefit: '国士側（便益）', undetermined: '向き未確定（参考）' };
/** 向き未確定の印。どの図表でも、向き未確定の値の近くに出す。 */
export const UNDETERMINED_NOTE = '向き未確定：損失か便益かは産業と比較国の差の符号だけで決まり、その法律の効果の向きを示す証拠ではありません。国賊側・国士側に分けず、差の大きさだけを参考として出します（順位・議員には使いません）。';

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

/** 時系列の1本の向き：国士は上、国賊は下（0 を挟む）。向き未確定は向きが無いので、大きさだけを上に出し、下は0。 */
export function timelineValues(t: TimelineYear, ledger: Ledger): { up: number; down: number } {
  if (ledger === 'undetermined') return { up: t.referenceUndetermined, down: 0 };
  return ledger === 'confirmed' ? { up: t.confirmedBenefit, down: t.confirmedLoss } : { up: t.referenceBenefit, down: t.referenceLoss };
}

export const yen = formatYen;
