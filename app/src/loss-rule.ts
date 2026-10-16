/**
 * 反実仮想の損失額と個人への配分（判定ルール版 loss-rule-v1）。
 * 設計は M2 技術帰属設計 §2-3・§2-4。入力は公的統計の実測値と、一次資料で確認できた行動だけです。
 * 損失額は impact-rule-v1 で段階2以上（経済全体の指標でも差がある）になった政策にだけ出します。
 * 出せないものは null（保留）にし、0 で埋めません。
 */
import type { CountryPoint, CountrySeries } from './impact-rule';

export type LossInput = {
  /** 分野の実質付加価値の定義。定義の違う系列はつながない。 */
  definition: string;
  /** 施策の開始日。 */
  start: string;
  /** impact-rule-v1 の結果。段階2未満や向きが無ければ損失額は出さない。 */
  judgement: { stage: 1 | 2 | 3 | null; direction: 'benefit' | 'harm' | null };
  /** 日本の分野の実質付加価値（年1点、どの単位でもよい。比で使う）。 */
  treated: CountryPoint[];
  /** 比較国の同じ定義の系列。 */
  controls: CountrySeries[];
  /** 開始前の最後の年の、日本の分野の名目付加価値（円）。金額への換算に使う。 */
  baseNominalYen: number;
  /** 規制の便益（安全・住宅・雇用など）を実測で見積もった額（円、累積）。未測定は null で、その場合は公開しない。 */
  regulationBenefitYen: number | null;
};

export type LossResult = {
  ruleVersion: 'loss-rule-v1';
  /** 累積の損失額（円）。正は失った額、負は得た額。low/high は比較国の伸びの四分位で作った幅。 */
  lossYen: { low: number; median: number; high: number } | null;
  years: number;
  /** 規制の便益を差し引いた額か。false なら公開しない。 */
  publishable: boolean;
  reason: string;
};

export const MAX_LOSS_YEARS = 10;
const MIN_PRE_YEARS = 3;
const MIN_CONTROLS = 3;

const quantile = (xs: number[], q: number) => {
  const s = [...xs].sort((a, b) => a - b);
  const pos = (s.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
};
const yearOf = (asOf: string) => Number(asOf.slice(0, 4));
const round = (x: number) => Math.round(x);

/**
 * 日本が比較国と同じ伸び方をしていた場合の付加価値（反実仮想）と、実績との差を合計する。
 * 開始前から日本の伸びが比較国より低かった分（開始前の年平均の伸びの差）は、政策の前から続く動きとして反実仮想に織り込み、損失に数えない。
 * 合計は開始後1年目から最大10年。
 */
export function estimateLoss(input: LossInput): LossResult {
  const base = { ruleVersion: 'loss-rule-v1' as const };
  const none = (reason: string, years = 0): LossResult => ({ ...base, lossYen: null, years, publishable: false, reason });
  const { stage, direction } = input.judgement;
  if (stage === null || stage < 2 || direction === null) return none('影響段階が2以上でないため、損失額は出さない（経済全体の指標で差が確認できていない）');
  if (input.controls.length < MIN_CONTROLS) return none(`比較国が${input.controls.length}か国で、${MIN_CONTROLS}か国に足りません`);

  const jp = new Map(input.treated.map(p => [p.asOf, p.value]));
  const pre = input.treated.filter(p => p.asOf < input.start).sort((a, b) => a.asOf.localeCompare(b.asOf));
  if (pre.length < MIN_PRE_YEARS) return none(`開始前の観測が${pre.length}年で、${MIN_PRE_YEARS}年に足りません`);
  const baseAsOf = pre[pre.length - 1].asOf, firstAsOf = pre[Math.max(0, pre.length - 5)].asOf;
  const preSpan = yearOf(baseAsOf) - yearOf(firstAsOf);
  const post = input.treated.filter(p => p.asOf >= input.start).sort((a, b) => a.asOf.localeCompare(b.asOf)).slice(0, MAX_LOSS_YEARS);
  if (post.length === 0) return none('開始後の観測がありません');

  const ctl = input.controls.map(c => new Map(c.points.map(p => [p.asOf, p.value])));
  if (ctl.some(m => !m.has(baseAsOf) || !m.has(firstAsOf) || post.some(p => !m.has(p.asOf)))) return none('比較国の系列に、日本と同じ年の観測が欠けています');

  // 開始前の年平均の伸び（対数）。日本と比較国の中央値の差を、開始後も続く傾きとして扱う。
  const growth = (a: number, b: number) => Math.log(b / a) / preSpan;
  const jpPreGrowth = growth(jp.get(firstAsOf)!, jp.get(baseAsOf)!);
  const ctlPreGrowth = quantile(ctl.map(m => growth(m.get(firstAsOf)!, m.get(baseAsOf)!)), 0.5);
  const drift = jpPreGrowth - ctlPreGrowth;

  const jpBase = jp.get(baseAsOf)!;
  const sums = { low: 0, median: 0, high: 0 };
  for (const p of post) {
    const k = yearOf(p.asOf) - yearOf(baseAsOf);
    const ratios = ctl.map(m => m.get(p.asOf)! / m.get(baseAsOf)!);
    // 比較国の伸びが高いほど反実仮想が高く、損失が大きい。low は伸びの第1四分位、high は第3四分位。
    for (const [key, q] of [['low', 0.25], ['median', 0.5], ['high', 0.75]] as const) {
      const counterfactual = jpBase * quantile(ratios, q) * Math.exp(drift * k);
      sums[key] += (counterfactual - p.value) / jpBase * input.baseNominalYen;
    }
  }
  // 1円未満の差は浮動小数点の誤差として0とみなす。
  const sign = Math.sign(round(sums.median));
  if (sign === 0 || (sign > 0) !== (direction === 'harm')) return none('損失額の向きが影響段階の向きと一致しないため保留', post.length);
  const offset = input.regulationBenefitYen ?? 0;
  const lossYen = { low: round(sums.low - offset), median: round(sums.median - offset), high: round(sums.high - offset) };
  const publishable = input.regulationBenefitYen !== null;
  return { ...base, lossYen, years: post.length, publishable, reason: `開始後${post.length}年の累積。比較国${input.controls.length}か国の伸びの中央値（幅は四分位）と、開始前の伸びの差を織り込んだ反実仮想との差${publishable ? '。規制の便益を差し引き済み' : '。規制の便益が未測定のため公開しない'}` };
}

/** 一次資料で確認できた個人の行動。行動の重みは設計 §2-4 の表、立場の重みは当時の役職。 */
export type Action = 'decide' | 'amend' | 'chair' | 'question' | 'vote';
export type Position = 'prime_minister' | 'minister_or_party_exec' | 'vice_minister_or_chair' | 'other';
export const ACTION_WEIGHT: Record<Action, number> = { decide: 5, amend: 4, chair: 3, question: 2, vote: 1 };
export const POSITION_WEIGHT: Record<Position, number> = { prime_minister: 3, minister_or_party_exec: 2, vice_minister_or_chair: 1.5, other: 1 };
export type Involvement = { personId: string; action: Action; position: Position; evidenceUrl: string };
export type Allocation = { personId: string; weight: number; shareYen: { low: number; median: number; high: number } };

/**
 * 損失額 × 帰属率 を、確認できた行動の重み × 立場の重みで按分する。
 * 1人が複数の行動をした場合は最大の行動だけを数える。一次資料（URL）の無い行動は数えない。
 * 個人の配分の合計は、損失額 × 帰属率 を超えない（残りは組織・未帰属）。
 */
export function allocateLoss(lossYen: NonNullable<LossResult['lossYen']>, involvements: Involvement[], attributionRate = 0.5): Allocation[] {
  if (!(attributionRate >= 0 && attributionRate <= 1)) throw new Error('帰属率は0〜1です');
  const best = new Map<string, number>();
  for (const v of involvements) {
    if (!/^https?:\/\//.test(v.evidenceUrl)) continue;
    const w = ACTION_WEIGHT[v.action] * POSITION_WEIGHT[v.position];
    best.set(v.personId, Math.max(best.get(v.personId) ?? 0, w));
  }
  const total = [...best.values()].reduce((s, w) => s + w, 0);
  if (total === 0) return [];
  const share = (x: number, w: number) => Math.round(x * attributionRate * w / total);
  return [...best.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([personId, weight]) => ({ personId, weight, shareYen: { low: share(lossYen.low, weight), median: share(lossYen.median, weight), high: share(lossYen.high, weight) } }));
}
