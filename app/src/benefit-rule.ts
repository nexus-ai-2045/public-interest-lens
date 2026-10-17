/**
 * 規制の便益の判定ルール（判定ルール版 benefit-rule-v1.1）。提案は docs/提案/便益ルール-v1.md。
 * v1.1 の改定（R4 だけ）：測った結果が既に便益の側（影響段階が貢献で、測った純額も便益）の法律では、
 * 足されても便益を増やすだけの未測定（下の UNMEASURED_SIGN が「加算のみ」）は公開を止めず、額を「下限（未測定の便益あり）」として出す。
 * 便益を減らしうる未測定（費用を含む種類、符号が定まらない種類）は今までどおり止める。損失の側（悪影響）の法律は変えない。
 * 便益の状態（内包・円換算済み・検出されず・検出・未換算・未測定）と、公開の判定表（R1〜R6）、新型コロナの窓の扱いをここだけに置きます。
 * 便益の指標の差の判定は impact-rule-v1（app/src/impact-rule.ts の judgeImpact）をそのまま使い、ここでは判定しません。
 * 損失額は loss-rule-v1（app/src/loss-rule.ts）が出し、ここではその結果と便益を組み合わせるだけです。
 *
 * 既定（人が上書きできる。docs/提案/便益ルール-v1.md の 4）：
 * - 既定1：「検出されず」（測れたが差が出ない）は便益0とみなし、「便益は検出されず」と表示する。
 * - 既定2：損失額の窓が2020〜2022年と重なるときは2019年で切り、開始後が2年以上残り、切った窓で影響段階と向き（と損失額の向き）が再現するときだけ公開の候補にする。
 * - 既定3：円への換算は公的機関が公表した単価だけ。単価の無い種類は「検出・未換算」。
 */
import { judgeImpact, type ImpactPoint } from './impact-rule';
import type { LossResult } from './loss-rule';

export const BENEFIT_RULE_VERSION = 'benefit-rule-v1.1';

/** 便益の種類（提案 2-4 の対応表。事前に固定）。「対応表外（…）」は表に無い種類で、指標と比較群が決まっていないので未測定になる。 */
export const BENEFIT_KINDS = ['経済（内包）', '経済（付加価値の外）', '消費者保護', '金融の安定', '安全（事故）', '安全（犯罪）', 'プライバシー', '環境', '移転'] as const;
export type BenefitKind = (typeof BENEFIT_KINDS)[number] | `対応表外（${string}）`;
export const isKnownKind = (k: string): k is BenefitKind => (BENEFIT_KINDS as readonly string[]).includes(k) || /^対応表外（.+）$/.test(k);

export type BenefitState = '内包' | '円換算済み' | '検出されず' | '検出・未換算' | '未測定';
export type YenRange = { low: number; median: number; high: number };
export type BenefitMeasurement = {
  kind: string;
  state: BenefitState;
  /** 便益の額（円、累積）。正は便益（損失を減らす）、負は悪化（損失を増やす）。null は差し引けない。 */
  yen: YenRange | null;
  /** 測った系列の名前（同じ系列を2回数えないための鍵）。測っていなければ空。 */
  series: string;
  effect: number | null;
  spread: number | null;
  reason: string;
  /** 「検出・未換算」のとき、判定の向き（円換算した額の向きが判定と食い違ったものは付けない）。 */
  detected?: 'benefit' | 'harm';
};

/** 表示の文言。既定1：「検出されず」は「便益は検出されず」と書く。 */
export const stateLabel = (s: BenefitState) => s === '検出されず' ? '便益は検出されず' : s;

const ZERO: YenRange = { low: 0, median: 0, high: 0 };

/** 目的が経済だけで損失額の系列に入っている（内包）。移転（税収・財源・交付金）も便益にも損失にも数えないので0。 */
export function includedBenefit(kind: string, reason: string): BenefitMeasurement {
  return { kind, state: '内包', yen: ZERO, series: '', effect: null, spread: null, reason };
}
export function unmeasuredBenefit(kind: string, reason: string): BenefitMeasurement {
  return { kind, state: '未測定', yen: null, series: '', effect: null, spread: null, reason };
}

/** 公的機関が公表した単価（既定3）。無ければ null。 */
export type UnitValue = { yen: number; source: string };

/** 便益の指標の入力。件数などの実測値をそのまま渡す（指数へのそろえはこの関数が行う）。 */
export type BenefitSeriesInput = {
  kind: string;
  /** 系列の名前（対象と比較の組）。 */
  series: string;
  definition: string;
  start: string;
  better: 'lower' | 'higher';
  treated: { asOf: string; value: number }[];
  control: { asOf: string; value: number }[];
  unit: UnitValue | null;
  /** 円に直して足す開始後の年数の上限（損失額と同じ年数）。 */
  maxYears: number;
};

const MAX_PRE_YEARS = 5;
const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length;

/**
 * 便益の指標を impact-rule-v1 にかけ、状態を決める。
 * - 開始前・開始後の観測が足りない（judgeImpact が効果を出せない）：未測定
 * - 効果が出たが段階が付かない（ばらつきの2倍を超えて2年続かない）：検出されず（既定1で0）
 * - 段階1以上：公的な単価があれば円換算済み、無ければ検出・未換算
 * 円換算は、開始前の差の平均を開始後も続くとした反実仮想の件数と実績の差 × 単価を、開始後1年目から maxYears 年分足す。
 */
export function measureBenefit(input: BenefitSeriesInput): BenefitMeasurement {
  const base = { kind: input.kind, series: input.series };
  const ctl = new Map(input.control.map(p => [p.asOf, p.value]));
  const common = input.treated.filter(p => ctl.has(p.asOf)).sort((a, b) => a.asOf.localeCompare(b.asOf));
  const pre = common.filter(p => p.asOf < input.start);
  if (!pre.length) return { ...base, state: '未測定', yen: null, effect: null, spread: null, reason: `${input.series}：開始前の観測が0年で、3年に足りません` };
  const b = pre[pre.length - 1];
  const tBase = b.value, cBase = ctl.get(b.asOf)!;
  const points: ImpactPoint[] = common.map(p => ({ asOf: p.asOf, treated: p.value / tBase * 100, control: ctl.get(p.asOf)! / cBase * 100 }));
  const j = judgeImpact({ definition: input.definition, start: input.start, better: input.better, target: points, economy: null, sectorGdpShare: null });
  const facts = { effect: j.effect, spread: j.spread };
  if (j.effect === null) return { ...base, ...facts, state: '未測定', yen: null, reason: `${input.series}：${j.reason}` };
  if (j.stage === null) return { ...base, ...facts, state: '検出されず', yen: ZERO, reason: `${input.series}：${j.reason}。既定1により便益0（便益は検出されず）` };
  const dir = j.direction === 'benefit' ? '改善' : '悪化';
  if (!input.unit) return { ...base, ...facts, state: '検出・未換算', yen: null, detected: j.direction ?? undefined, reason: `${input.series}：段階${j.stage}（${dir}）。公的機関が公表した単価が無いため円にしない（既定3）` };
  const prePts = points.filter(p => p.asOf < input.start).slice(-MAX_PRE_YEARS);
  const preGap = mean(prePts.map(p => p.treated - p.control));
  const post = points.filter(p => p.asOf >= input.start).slice(0, input.maxYears);
  let count = 0;
  for (const p of post) {
    // 反実仮想の指数＝比較の指数＋開始前の差の平均。低いほど良い指標は「反実仮想−実績」が防いだ件数。
    const gap = (p.control + preGap) - p.treated;
    count += (input.better === 'lower' ? gap : -gap) / 100 * tBase;
  }
  const yen = Math.round(count * input.unit.yen);
  if (Math.sign(yen) !== (j.direction === 'benefit' ? 1 : -1)) return { ...base, ...facts, state: '検出・未換算', yen: null, reason: `${input.series}：段階${j.stage}（${dir}）だが、円換算した額の向きが判定の向きと一致しないため円にしない` };
  return { ...base, ...facts, state: '円換算済み', yen: { low: yen, median: yen, high: yen }, reason: `${input.series}：段階${j.stage}（${dir}）。開始後${post.length}年の差の件数${Math.round(count)}×単価${input.unit.yen}円（${input.unit.source}）` };
}

/**
 * 1法律の便益の合計。未測定・検出・未換算が1つでもあれば null（差し引けない）。
 * 同じ系列を指す種類は1回だけ数える（提案 3-5 の二重計上の禁止）。
 */
export function combineBenefits(ms: BenefitMeasurement[]): YenRange | null {
  if (ms.some(m => m.yen === null)) return null;
  const seen = new Set<string>();
  const sum = { ...ZERO };
  for (const m of ms) {
    if (m.series) { if (seen.has(m.series)) continue; seen.add(m.series); }
    sum.low += m.yen!.low; sum.median += m.yen!.median; sum.high += m.yen!.high;
  }
  return sum;
}

// ---- 未測定の符号（v1.1。種類ごとに事前に固定する） ----

/**
 * 未測定（または検出・未換算）の便益が、測れたときに便益を減らしうるか。
 * - 加算のみ：防いだ被害だけを数える種類で、規制の費用の項目を同じ種類に含まない。測れても便益を増やす（または0）だけ。
 * - 減らしうる：費用・悪化の面を同じ種類に含む、または指標・向きが事前に固定されていない。
 * 法律ごとの調整はしない（種類だけで決める）。表の当てはめは AI の解釈で、採用には人の確認が要る。
 */
export type UnmeasuredSign = '加算のみ' | '減らしうる';
export const UNMEASURED_SIGN: Record<string, { sign: UnmeasuredSign; why: string }> = {
  '安全（犯罪）': { sign: '加算のみ', why: '指標は罪種別の認知・検挙件数で、防いだ被害だけを数える（費用の項目を含まない）' },
  '安全（事故）': { sign: '加算のみ', why: '指標は事故・災害の件数で、防いだ被害だけを数える（費用の項目を含まない）' },
  'プライバシー': { sign: '加算のみ', why: '指標は漏えい等の報告件数で、防いだ被害だけを数える（費用の項目を含まない）' },
  '環境': { sign: '加算のみ', why: '指標は排出量・測定値で、防いだ被害だけを数える（費用の項目を含まない）' },
  '消費者保護': { sign: '減らしうる', why: '供給・取引の制限で、消費者が利用できる商品・融資が減る面（費用）を同じ種類に含む' },
  '金融の安定': { sign: '減らしうる', why: '規制による貸出の抑制や、救済の期待による危険の増加（モラルハザード）で、破綻・不良債権が増える向きもありうる' },
  '経済（付加価値の外）': { sign: '減らしうる', why: '海外の出資先から得る所得は、出資の損失（減損）で負になりうる。出資に使った資金の機会費用も損失額の系列の外' },
};
export function unmeasuredSign(m: BenefitMeasurement): { sign: UnmeasuredSign; why: string } {
  if (m.kind === '目的の分類') return { sign: '減らしうる', why: '目的の分類が保留で、種類が決まっていない' };
  if (/^対応表外（.+）$/.test(m.kind)) return { sign: '減らしうる', why: '対応表に無い種類で、指標・比較群・向きが事前に固定されていない' };
  const t = UNMEASURED_SIGN[m.kind];
  if (!t) return { sign: '減らしうる', why: '符号の表に無い種類' };
  if (t.sign === '加算のみ' && m.state === '検出・未換算' && m.detected !== 'benefit') {
    return { sign: '減らしうる', why: m.detected === 'harm' ? '指標が悪化の向きで検出された' : '円換算した額の向きが判定の向きと一致しない' };
  }
  return t;
}

/** 下限の表示（v1.1）。 */
export const LOWER_BOUND_LABEL = '下限（未測定の便益あり）';

/** 法律の側（影響段階の向き）。国士側＝貢献、国賊側＝悪影響。法律についての表示で、人物には付けない。 */
export const sideLabel = (d: 'benefit' | 'harm' | null | undefined) => d === 'benefit' ? '国士側（貢献）' : d === 'harm' ? '国賊側（悪影響）' : '保留（向きなし）';

// ---- 新型コロナの窓（既定2） ----

export const COVID_YEARS = [2020, 2021, 2022];
export const COVID_CUTOFF_YEAR = 2019;
const MIN_POST_YEARS_AFTER_CUT = 2;
export const overlapsCovid = (from: number, to: number) => from <= COVID_YEARS[COVID_YEARS.length - 1] && to >= COVID_YEARS[0];
/** 2019年末より後の観測を落とす。2023年以降をつなぐことはしない（系列接続禁止と同じ考え方）。 */
export const cutAtCovid = <T extends { asOf: string }>(points: T[]): T[] => points.filter(p => p.asOf <= `${COVID_CUTOFF_YEAR}-12-31`);

export type Judged = { stage: 1 | 2 | 3 | null; direction: 'benefit' | 'harm' | null };
export type CovidCheck = { applies: boolean; separable: boolean; reason: string };

const judgedLabel = (j: Judged | null) => !j || j.stage === null ? '保留' : `段階${j.stage}・${j.direction === 'benefit' ? '貢献' : '悪影響'}`;

/**
 * 既定2。窓が2020〜2022年と重ならなければ対象外。重なれば、2019年で切った窓で
 * (1) 開始後が2年以上ある、(2) impact-rule-v1 の段階と向きが元と同じ、(3) loss-rule-v1 の額が出て向きが元と同じ、のときだけ分離できる。
 */
export function judgeCovidSeparation(a: {
  window: { from: number; to: number };
  postYearsAfterCut: number;
  original: Judged;
  recomputed: Judged | null;
  originalLoss: LossResult | null;
  truncatedLoss: LossResult | null;
}): CovidCheck {
  if (!overlapsCovid(a.window.from, a.window.to)) return { applies: false, separable: true, reason: '損失額の窓が2020〜2022年と重ならない' };
  const head = `損失額の窓（${a.window.from}〜${a.window.to}年）が新型コロナの2020〜2022年と重なるため${COVID_CUTOFF_YEAR}年で切った`;
  if (a.postYearsAfterCut < MIN_POST_YEARS_AFTER_CUT) return { applies: true, separable: false, reason: `コロナ期と分離できない：${head}が、開始後が${a.postYearsAfterCut}年で${MIN_POST_YEARS_AFTER_CUT}年に足りない` };
  if (!a.recomputed || a.recomputed.stage !== a.original.stage || a.recomputed.direction !== a.original.direction) {
    return { applies: true, separable: false, reason: `コロナ期と分離できない：${head}窓で影響段階と向きが再現しない（元：${judgedLabel(a.original)}、切った窓：${judgedLabel(a.recomputed)}）` };
  }
  const o = a.originalLoss?.lossYen, t = a.truncatedLoss?.lossYen;
  if (!o || !t || Math.sign(o.median) !== Math.sign(t.median)) return { applies: true, separable: false, reason: `コロナ期と分離できない：${head}窓で損失額の向きが再現しない${a.truncatedLoss && !t ? `（${a.truncatedLoss.reason}）` : ''}` };
  return { applies: true, separable: true, reason: `${head}。開始後${a.postYearsAfterCut}年で、影響段階と向き（${judgedLabel(a.recomputed)}）と損失額の向きが再現したため、切った窓の額を使う` };
}

// ---- 公開の判定表（提案 3-3） ----

export type PublishRow = 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'R6';
export type PublishInput = {
  /** 参考の行（貸出残高）。 */
  reference: boolean;
  /** loss-v1 で入力を作れなかった理由（系列の断絶など）。 */
  lossBlocked: string | null;
  /** loss-rule-v1 の元の結果（便益は未測定のまま）。 */
  originalLoss: LossResult | null;
  /** 2系統が一致して「目的が損失額の指標を抑える」と判定した。 */
  directionConflict: boolean;
  covid: CovidCheck;
  benefits: BenefitMeasurement[];
  /** 判定に使う窓（新型コロナの規則で切った窓、または元の窓）での、便益を差し引く前の額。 */
  grossLoss: LossResult | null;
  /** 同じ窓で、便益（regulationBenefitYen）を渡した loss-rule-v1 の結果。下限で出す場合は、測った便益だけの合計を渡したもの。 */
  finalLoss: LossResult | null;
  /** impact-rule-v1 の影響段階の向き（v1.1 の R4 で使う）。省略は null（緩めない）。 */
  direction?: 'benefit' | 'harm' | null;
};
export type PublishDecision = { row: PublishRow; publishable: boolean; reason: string; net: YenRange | null; lowerBound: boolean };

/**
 * 純額の幅。向きが厳しい側で組む：下限＝損失の下限−便益の上限、上限＝損失の上限−便益の下限。
 */
export const netRange = (loss: YenRange, benefit: YenRange): YenRange => ({ low: loss.low - benefit.high, median: loss.median - benefit.median, high: loss.high - benefit.low });

/** 上から順に当てはめ、最初に当たった行で決める。「公開可」は公開の候補で、実際の公開は人が一括で承認する（設計決定0007 §6）。 */
export function decidePublication(p: PublishInput): PublishDecision {
  const no = (row: PublishRow, reason: string, net: YenRange | null = null, lowerBound = false): PublishDecision => ({ row, publishable: false, reason, net, lowerBound });
  if (p.reference) return no('R1', '公開不可：参考の行（貸出残高）は合計に入れず公開の対象にしない');
  if (p.lossBlocked) return no('R1', `公開不可：loss-rule-v1 が保留（${p.lossBlocked}）`);
  if (!p.originalLoss?.lossYen) return no('R1', `公開不可：loss-rule-v1 が保留（${p.originalLoss?.reason ?? '入力なし'}）`);
  if (p.directionConflict) return no('R2', '保留（向きの矛盾）：目的が損失額の指標を抑えることなので、その減少を損失に数えない');
  if (p.covid.applies && !p.covid.separable) return no('R3', `公開不可：${p.covid.reason}`);
  const missing = p.benefits.filter(b => b.yen === null);
  const measured = p.benefits.filter(b => b.yen !== null);
  const gross = p.grossLoss?.lossYen;
  let lowerBound = false;
  if (missing.length) {
    const block = (extra = '') => no('R4', `公開不可（便益を差し引けない）：${missing.map(b => `${b.kind}が${b.state}（${b.reason}）`).join('／')}${extra}`);
    // v1.1：貢献の法律で、測った分だけの純額が便益の側なら、加算のみの未測定は止めない（額は下限）。
    const measuredNet = gross ? netRange(gross, combineBenefits(measured)!) : null;
    if (p.direction !== 'benefit' || !measuredNet || measuredNet.median >= 0) return block();
    const signs = missing.map(b => ({ b, ...unmeasuredSign(b) }));
    const reducing = signs.filter(s => s.sign === '減らしうる');
    if (reducing.length) return block(`。v1.1：便益の側だが、便益を減らしうる未測定がある（${reducing.map(s => `${s.b.kind}：${s.why}`).join('／')}）`);
    lowerBound = true;
  }
  const benefit = combineBenefits(measured)!;
  if (!gross || !p.finalLoss?.lossYen || !p.finalLoss.publishable) return no('R1', `公開不可：判定に使う窓で loss-rule-v1 が保留（${p.finalLoss?.reason ?? p.grossLoss?.reason ?? '入力なし'}）`);
  const net = netRange(gross, benefit);
  if (net.low <= 0 && net.high >= 0) return no('R5', `公開不可：純額の幅（${net.low}〜${net.high}円）が0をまたぎ、向きが定まらない`, net, lowerBound);
  const kind = net.median > 0 ? '純損失' : '純便益';
  const lb = lowerBound ? `。${LOWER_BOUND_LABEL}：加算のみの未測定（${missing.map(b => `${b.kind}：${unmeasuredSign(b).why}`).join('／')}）を0として出した便益の下限` : '';
  return { row: 'R6', publishable: true, reason: `公開可（公開の候補。実際の公開は人が一括で承認する）：${kind}${lb}。便益は${p.benefits.map(b => `${b.kind}＝${stateLabel(b.state)}`).join('・')}`, net, lowerBound };
}
