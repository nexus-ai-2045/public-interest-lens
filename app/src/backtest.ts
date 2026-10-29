/** バックテストの配布データ backtest.json の読み取りと表示用の整形。定義は docs/adr/0020（v1・v1.1）と 0021（v2）。 */

export const backtestUrl = '/distribution/backtest.json';

export type BacktestCase = { id: string; policy: string; source: string; truth: number; predicted: number; hit: boolean; laws: { id: string; year: number; side: 'loss' | 'benefit' }[] };
export type BacktestLevel = {
  level: string; name: string; definition: string; n: number; hits: number; rate: number | null;
  wilson95: [number, number] | null; verdict: '達成' | '未達' | '判定不能'; cases: BacktestCase[];
};
export type AlignedCase = { id: string; policy: string; source: string; truth: number; predicted: number; hit: boolean; indicator: string; alignment: string };
export type AlignmentGap = { japan_linked_cases: number; by_alignment: Record<string, number>; none_by_outcome_class: Record<string, number>; stopped_by: Record<string, number>; reading: string };
export type TransplantForeign = { fg: string; authors: string; year: number; country: string; outcome_class: string; sign: number };
export type TransplantCase = { id: string; group: string; policy: string; source: string; outcome_class: string; truth: number; predicted: number | null; hit: boolean; reason: string | null; foreign: TransplantForeign[] };
export type TransplantLevel = {
  level: string; name: string; definition: string; n: number; hits: number; rate: number | null; wilson95: [number, number] | null;
  groups: number; verdict: '達成' | '未達' | '判定不能'; targets: number; coverage: number | null; baseline: number | null; cases: TransplantCase[];
};
export type Transplant = {
  target: number; min_n: number; min_groups: number; note: string; match_splits: number;
  pool: { entries: number; usable: number; labels_held: string[]; events: number; from_cases: number; from_search: number };
  levels: TransplantLevel[];
  by_outcome_class: Record<string, { targets: number; n: number; hits: number; rate: number | null; verdict: string; provisional_value: string }>;
};
export type BacktestRun = {
  label: string; date: string; note: string; spec_version: string; target: number; min_n: number;
  cases_total: number; funnel: { excluded_by_reason: Record<string, number> };
  levels: BacktestLevel[];
  aligned_levels?: (Omit<BacktestLevel, 'cases'> & { cases: AlignedCase[] })[];
  alignment_gap?: AlignmentGap;
  transplant?: Transplant;
  amount_and_interval: { status: string; n: number; reason: string };
  excluded: { id: string; policy: string; source: string; reason: string }[];
};
export type Backtest = { schema: 'backtest-runs/v1'; runs: BacktestRun[] };

export function parseBacktest(text: string): Backtest {
  const data = JSON.parse(text) as Backtest;
  if (data.schema !== 'backtest-runs/v1' || !Array.isArray(data.runs)) throw new Error('バックテストのデータの形が違います');
  return data;
}

export function formatPercent(value: number | null): string {
  return value === null ? '—' : `${Math.round(value * 100)}%`;
}

/** 一致率を「11%（2〜44%）」のように読む。件数が0のときは「—」。 */
export function formatRate(level: Pick<BacktestLevel, 'rate' | 'wilson95'>): string {
  if (level.rate === null || !level.wilson95) return '—';
  return `${formatPercent(level.rate)}（${Math.round(level.wilson95[0] * 100)}〜${Math.round(level.wilson95[1] * 100)}%）`;
}

export function signLabel(sign: number): string {
  return sign > 0 ? '便益（国士側）' : sign < 0 ? '損失（国賊側）' : '同数';
}

/** 外国の研究の向き（+1/−1/0）。0 は有意でない・向きが定まらない。 */
export function foreignSignLabel(sign: number | null): string {
  return sign === null ? '—' : sign > 0 ? '便益（国士側）' : sign < 0 ? '損失（国賊側）' : '効果なし';
}
