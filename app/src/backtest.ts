/** バックテスト（backtest-v1）の配布データ backtest.json の読み取りと表示用の整形。定義は docs/adr/0020。 */

export const backtestUrl = '/distribution/backtest.json';

export type BacktestCase = { id: string; policy: string; source: string; truth: number; predicted: number; hit: boolean; laws: { id: string; year: number; side: 'loss' | 'benefit' }[] };
export type BacktestLevel = {
  level: string; name: string; definition: string; n: number; hits: number; rate: number | null;
  wilson95: [number, number] | null; verdict: '達成' | '未達' | '判定不能'; cases: BacktestCase[];
};
export type BacktestRun = {
  label: string; date: string; note: string; spec_version: string; target: number; min_n: number;
  cases_total: number; funnel: { excluded_by_reason: Record<string, number> };
  levels: BacktestLevel[];
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
