/**
 * /numbers（数字で見る）のデータ charts.json（public-charts/v1）の型と、グラフに直す計算。
 * charts.json は scripts/build_database.py がデータベースから作る。ここでは並べ替え・目盛り・単位だけを扱い、額は作らない。
 */
import { formatYen } from './laws-catalog';

export const chartsUrl = '/distribution/charts.json';

export type Side = 'loss' | 'benefit';
export type HistogramBin = { exp: number; loss: number; benefit: number };
export type TimelineYear = { year: number; laws: number; confirmedLoss: number; confirmedBenefit: number; referenceLoss: number; referenceBenefit: number };
export type PublicCharts = {
  schema: 'public-charts/v1';
  spec: string;
  histogram: HistogramBin[];
  byCertainty: { certainty: string; loss: number; benefit: number; laws: number }[];
  timeline: TimelineYear[];
  inputs: string;
};

export function parseCharts(value: unknown): PublicCharts {
  const v = value as PublicCharts;
  if (!v || v.schema !== 'public-charts/v1' || !Array.isArray(v.histogram) || !Array.isArray(v.timeline)) throw new Error('charts.json の形が違います');
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

export const yen = formatYen;
