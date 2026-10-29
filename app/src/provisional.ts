/** 暫定評価（provisional-v1）の配布データ provisional.json の読み取りと表示用の整形。 */

export const provisionalUrl = '/distribution/provisional.json';

export type ProvisionalEffect = { low: number; high: number; perComparator: Record<string, number> };
export type ProvisionalCard = {
  id: string;
  country: string;
  countryName: string;
  title: string;
  startYear: number;
  purpose: string;
  targetIndustry: string;
  instrument: string;
  startLevel: string;
  measure: string;
  applicableToJapan: boolean;
  applicabilityNote: string;
  sourceCertainty: string;
  source: string;
  window: { pre: [number, number]; post: [number, number] };
  crisisYears: number[];
  status: 'measured' | 'unmeasured';
  reason?: string;
  comparatorsUsed?: string[];
  effect?: ProvisionalEffect;
  spansZero?: boolean;
};
export type ProvisionalItem = {
  id: string;
  title: string;
  what?: string | null;
  year: number;
  field: string;
  cards: string[];
  amount: { low: number; high: number };
  direction: 'loss' | 'benefit' | 'unclear';
  size: { year: number; yen: number; label: string };
  marks: string[];
};
export type NearMiss = { id: string; title: string; cardId: string; reason: string };
export type TheoryItem = { id: string; mechanism: string; what: string; inputs: { obligation: string; count: number; hours: number; wage_in_assessment: number }[]; uncomputed: string[]; sources: string[]; low_yen: number; high_yen: number; direction: string; calc_note: string; period?: 'annual' | 'one_time' | 'unverified'; period_note?: string };
export type Theory = { version: string; status: string; note: string; items: TheoryItem[]; not_computed: { id: string; mechanism: string; reason: string }[]; backtest: { n: number; coverage: number | null; interval_width: number | null; note: string } };
export type Provisional = {
  schema: 'provisional/v1';
  version: string;
  recentFromYear: number;
  counts: { recent: number; provisional: number; unmeasured: number };
  cards: ProvisionalCard[];
  items: ProvisionalItem[];
  nearMisses: NearMiss[];
  theory: Theory | null;
};

export function parseProvisional(text: string): Provisional {
  const data = JSON.parse(text) as Provisional;
  if (data.schema !== 'provisional/v1' || !Array.isArray(data.cards) || !Array.isArray(data.items)) throw new Error('暫定評価データの形が違います');
  return data;
}

/** 効果（水準の差の割合）を「+12%」のように読む。 */
export function formatGap(value: number): string {
  const percent = value * 100;
  const text = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(Math.abs(percent));
  return `${percent < 0 ? '−' : '+'}${text}%`;
}

export function formatGapRange(effect: { low: number; high: number }): string {
  return `${formatGap(effect.low)}〜${formatGap(effect.high)}`;
}

export function directionLabel(direction: ProvisionalItem['direction']): string {
  return direction === 'loss' ? '国賊側（損失の幅）' : direction === 'benefit' ? '国士側（便益の幅）' : '向きが定まらない（幅が0をまたぐ）';
}

export function periodLabel(period: TheoryItem['period']): string {
  return period === 'annual' ? '年間' : period === 'one_time' ? '一時' : '期間未確認';
}
