/**
 * 影響段階の判定ルール（設計決定0007 §5、判定ルール版 impact-rule-v1）。
 * 入力は公的統計の実測値だけです。段階は人や AI の裁量ではなく、この計算で決まります。
 * 条件を満たさないものは段階を作らず保留（stage: null）にします。
 */
export type ImpactPoint = { asOf: string; treated: number; control: number };
export type ImpactSeries = {
  /** 統計の名前と定義。定義の異なる系列をつないだ点列は渡さない（PROJECT_SSOT の系列接続禁止）。 */
  definition: string;
  /** 施策の開始日。これより前の観測が開始前、これ以降が開始後です。 */
  start: string;
  /** 指標が低いほど良いか、高いほど良いか。効果の向き（貢献か悪影響か）はこれと符号で機械的に決まります。 */
  better: 'lower' | 'higher';
  /** 狙った指標（年1点、期末日の昇順）。 */
  target: ImpactPoint[];
  /** 経済全体の指標（分野の付加価値・GDP・貸出・雇用のどれか）。無ければ段階2以上になりません。 */
  economy: (Omit<ImpactSeries, 'start' | 'target' | 'economy' | 'sectorGdpShare'> & { points: ImpactPoint[] }) | null;
  /** 対象分野の付加価値の GDP 比（0〜1）。無ければ段階3になりません。 */
  sectorGdpShare: number | null;
};
export type ImpactJudgement = {
  ruleVersion: 'impact-rule-v1';
  stage: 1 | 2 | 3 | null;
  /** 効果の向き。stage が null のときも、計算できた範囲で記録します。 */
  direction: 'benefit' | 'harm' | null;
  reason: string;
  preYears: number;
  effect: number | null;
  spread: number | null;
};

export const MIN_PRE_YEARS = 3;
const MAX_PRE_YEARS = 5;
const SPREAD_MULTIPLIER = 2;
const MIN_PERSISTENT_YEARS = 2;
const MIN_SECTOR_GDP_SHARE = 0.01;

const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length;
const sampleSd = (xs: number[]) => { const m = mean(xs); return Math.sqrt(xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1)); };
const round = (x: number) => Math.round(x * 1e6) / 1e6;

type Measured = { ok: true; effect: number; spread: number; preYears: number; preGaps: number[]; prePoints: ImpactPoint[]; postGaps: number[]; postPoints: ImpactPoint[] } | { ok: false; reason: string; preYears: number };

/** 差＝対象−比較。効果＝開始後2〜5年目の差の平均−開始前の差の平均。ばらつき＝開始前の差の標本標準偏差。 */
function measure(points: ImpactPoint[], start: string): Measured {
  const sorted = [...points].sort((a, b) => a.asOf.localeCompare(b.asOf));
  if (sorted.some((p, i) => i > 0 && p.asOf === sorted[i - 1].asOf)) return { ok: false, reason: '同じ期末の観測が重複しています', preYears: 0 };
  const prePoints = sorted.filter(p => p.asOf < start).slice(-MAX_PRE_YEARS);
  const post = sorted.filter(p => p.asOf >= start);
  if (prePoints.length < MIN_PRE_YEARS) return { ok: false, reason: `開始前の観測が${prePoints.length}年で、${MIN_PRE_YEARS}年に足りません`, preYears: prePoints.length };
  // 開始後1年目は効果の立ち上がりとして除き、2〜5年目を使う。
  const postPoints = post.slice(1, 5);
  if (postPoints.length < MIN_PERSISTENT_YEARS) return { ok: false, reason: '開始後2年目以降の観測が足りません', preYears: prePoints.length };
  const preGaps = prePoints.map(p => p.treated - p.control);
  const postGaps = postPoints.map(p => p.treated - p.control);
  return { ok: true, effect: mean(postGaps) - mean(preGaps), spread: sampleSd(preGaps), preYears: prePoints.length, preGaps, prePoints, postGaps, postPoints };
}

const directionOf = (effect: number, better: ImpactSeries['better']): 'benefit' | 'harm' => (effect < 0) === (better === 'lower') ? 'benefit' : 'harm';

/** 効果がばらつきの2倍を超え、開始前平均から同じ向きに外れた年が2年以上続く。 */
function passesBasic(m: Extract<Measured, { ok: true }>): boolean {
  if (Math.abs(m.effect) <= SPREAD_MULTIPLIER * m.spread) return false;
  const preMean = mean(m.preGaps);
  let run = 0, best = 0;
  for (const g of m.postGaps) { run = Math.sign(g - preMean) === Math.sign(m.effect) ? run + 1 : 0; best = Math.max(best, run); }
  return best >= MIN_PERSISTENT_YEARS;
}

/** 開始前の差に直線を当て、その延長を開始後から差し引いても効果が残るか。 */
function survivesPreTrend(m: Extract<Measured, { ok: true }>): boolean {
  const xs = m.prePoints.map(p => Date.parse(p.asOf)), ys = m.preGaps;
  const mx = mean(xs), my = mean(ys);
  const slope = xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0) / xs.reduce((s, x) => s + (x - mx) ** 2, 0);
  const residual = mean(m.postPoints.map((p, i) => m.postGaps[i] - (my + slope * (Date.parse(p.asOf) - mx))));
  return Math.sign(residual) === Math.sign(m.effect) && Math.abs(residual) > SPREAD_MULTIPLIER * m.spread;
}

export function judgeImpact(series: ImpactSeries): ImpactJudgement {
  const base = { ruleVersion: 'impact-rule-v1' as const };
  const m = measure(series.target, series.start);
  if (!m.ok) return { ...base, stage: null, direction: null, reason: m.reason, preYears: m.preYears, effect: null, spread: null };
  const direction = directionOf(m.effect, series.better);
  const facts = { preYears: m.preYears, effect: round(m.effect), spread: round(m.spread), direction };
  const describe = `効果${facts.effect}（開始前のばらつき${facts.spread}の${SPREAD_MULTIPLIER}倍＝${round(SPREAD_MULTIPLIER * m.spread)}と比較）`;
  if (!passesBasic(m)) return { ...base, ...facts, stage: null, reason: `${describe}。ばらつきの${SPREAD_MULTIPLIER}倍を超えて${MIN_PERSISTENT_YEARS}年以上続いた差がないため保留` };
  const economy = series.economy ? measure(series.economy.points, series.start) : null;
  const economyPasses = economy?.ok === true && passesBasic(economy) && directionOf(economy.effect, series.economy!.better) === direction;
  if (!economyPasses) return { ...base, ...facts, stage: 1, reason: `${describe}。狙った指標の差は確認できたが、経済全体の指標で同じ向きの差が確認できないため段階1` };
  const largeSector = series.sectorGdpShare !== null && series.sectorGdpShare >= MIN_SECTOR_GDP_SHARE;
  if (!survivesPreTrend(m) || !largeSector) return { ...base, ...facts, stage: 2, reason: `${describe}。経済全体の指標でも差があるが、開始前の傾きを除いた効果か分野の規模（GDPの${MIN_SECTOR_GDP_SHARE * 100}%以上）を満たさないため段階2` };
  return { ...base, ...facts, stage: 3, reason: `${describe}。経済全体の指標・開始前の傾きの除去・分野の規模をすべて満たすため段階3` };
}
