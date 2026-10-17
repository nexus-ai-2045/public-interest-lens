/**
 * loss-v1 の法律に benefit-rule-v1.1（app/src/benefit-rule.ts）をかける処理（benefit-v1）。
 * 目的の分類は app/src/benefit-classification.ts（2系統）、便益の指標の差は impact-rule-v1、額は loss-rule-v1、
 * 便益の状態と公開の判定は benefit-rule.ts だけが行い、ここでは系列を選んで入力を作り、結果を表にするだけです。
 * 法律だけを扱います。人物・採決・役職のデータは読まない。ファイルの読み書きは app/scripts/run-benefit-v1.mjs。
 * 方法の説明は data/derived/benefit-v1/spec.md。
 */
import { INDICATOR_MAP, asOfYear, buildImpactSeries, chooseOption, extractSeries, type Ref, type Row, type Tables } from './impact-batch';
import { judgeImpact } from './impact-rule';
import { amountCell, evaluateLosses, lossWindow, observationGroups, type ImpactRow, type LossRow } from './loss-batch';
import { estimateLoss, MAX_LOSS_YEARS, type LossInput, type LossResult } from './loss-rule';
import {
  combineBenefits, cutAtCovid, decidePublication, includedBenefit, judgeCovidSeparation, LOWER_BOUND_LABEL, measureBenefit, overlapsCovid, sideLabel, stateLabel, unmeasuredBenefit, unmeasuredSign,
  type BenefitMeasurement, type CovidCheck, type PublishDecision, type YenRange,
} from './benefit-rule';
import { classifyLaw, type Classification } from './benefit-classification';

/** 便益の指標の候補（対象と比較の組）。unit は公的機関が公表した単価の系列（既定3）。無ければ null。 */
export type BenefitOption = { name: string; definition: string; better: 'lower' | 'higher'; treated: Ref; control: Ref; unit: { ref: Ref; source: string } | null };
export type BenefitSource = { options: BenefitOption[]; missing: string };

const COURTS = 'benefit-data/courts_bankruptcy.csv';
const bankruptcy = (cls: string): Ref => ({ file: COURTS, where: { 系列: '破産新受件数（全地方裁判所）', 区分: cls } });

/**
 * 便益の種類 → 指標（提案 2-4。結果を見る前に固定）。「経済（内包）」「移転」は測らない（0）。
 * options が空の種類は、取得済みの系列が無いか比較群が作れないので未測定。missing に足りない出典を書く。
 */
export const BENEFIT_SOURCES: Record<string, BenefitSource> = {
  '消費者保護': {
    options: [{
      name: '司法統計 破産新受件数「自然人」対「法人・その他」（全地方裁判所、暦年）',
      definition: '自然人の破産新受件数の指数と、法人・その他の破産新受件数の指数（開始前最後の年=100）', better: 'lower',
      treated: bankruptcy('自然人'), control: bankruptcy('法人・その他'),
      unit: null,
    }],
    missing: 'PIO-NET の商品・役務等別の相談件数と平均既支払金額（公的な単価）は2015〜2021年度の上位25位だけで、順位の入れ替わりで系列が連続せず、2014年度以前は消費生活年報が公開されていない（docs/reports/benefit-data.md）。司法統計の破産は2005年から（1990〜2004年は取得できず）で、破産1件あたりの公的な単価は無い。金融庁の貸金業の苦情件数は2002年度から',
  },
  '金融の安定': {
    options: [],
    missing: '金融庁 金融再生法開示債権（全国銀行）は全銀行に及ぶ法律では比較群が作れず、信用金庫を含まない。預金保険機構の年ごとの破綻件数は公開ページに表が無く未取得（累計額だけ）。公的な単価も無い',
  },
  '安全（犯罪）': { options: [], missing: '警察庁「サイバー空間をめぐる脅威の情勢等」（D9）・犯罪統計（D10）は未取得。取得しても国内の比較群と国際の同じ定義の系列が無い見込み。公的な単価も無い' },
  '安全（事故）': { options: [], missing: '交通事故・労働災害・火災の統計は未取得' },
  'プライバシー': { options: [], missing: '個人情報保護委員会 年次報告の漏えい等の報告件数は未取得。公的な単価も無い' },
  '環境': { options: [], missing: '温室効果ガス排出量などは未取得。公的な炭素価格が無いので円にしない' },
  '経済（付加価値の外）': { options: [], missing: '日本銀行 国際収支統計のサービス収支「通信・コンピュータ・情報サービス」の受取と OECD の同じ項目（D11）は未取得' },
};

/** 種類ごとの便益を測る。cut は新型コロナの規則（既定2）で2019年に切るか。 */
export function measureKind(tables: Tables, kind: string, start: string, cut: boolean, maxYears: number, sources = BENEFIT_SOURCES): BenefitMeasurement {
  if (kind === '経済（内包）') return includedBenefit(kind, '目的が経済の効果で、損失額の系列（分野の付加価値・貸出）に内包される。別の便益として足さない（追加の便益0）');
  if (kind === '移転') return includedBenefit(kind, '移転（税収・財源・交付金・納付金）は便益にも損失にも数えない（提案 3-5）。0');
  const source = sources[kind];
  if (!source) return unmeasuredBenefit(kind, '提案 2-4 の対応表に無い種類で、指標・比較群・単価が事前に固定されていない');
  if (!source.options.length) return unmeasuredBenefit(kind, `系列なし：${source.missing}`);
  const chosen = chooseOption(tables, start, source.options, o => [o.treated, o.control]);
  const o = chosen!.option;
  const pts = (m: Map<number, number>) => {
    const p = [...m.keys()].sort((x, y) => x - y).map(y => ({ asOf: asOfYear(y), value: m.get(y)! }));
    return cut ? cutAtCovid(p) : p;
  };
  const treated = pts(chosen!.a), control = pts(chosen!.b);
  const pre = treated.filter(p => p.asOf < start);
  const unitYear = pre.length ? Number(pre[pre.length - 1].asOf.slice(0, 4)) : null;
  const unitValue = o.unit && unitYear !== null ? extractSeries(tables, o.unit.ref).get(unitYear) : undefined;
  const m = measureBenefit({
    kind, series: o.name, definition: o.definition, start, better: o.better, treated, control, maxYears,
    unit: o.unit && unitValue !== undefined ? { yen: unitValue, source: `${o.unit.source}（${unitYear}年）` } : null,
  });
  const span = treated.length ? `系列は${treated[0].asOf.slice(0, 4)}〜${treated[treated.length - 1].asOf.slice(0, 4)}年` : '系列なし';
  return m.state === '未測定' ? { ...m, reason: `${m.reason}（${span}）。ほかの候補：${source.missing}` } : m;
}

const postPoints = (input: LossInput) => input.treated.filter(p => p.asOf >= input.start);
const cutInput = (input: LossInput): LossInput => ({ ...input, treated: cutAtCovid(input.treated), controls: input.controls.map(c => ({ ...c, points: cutAtCovid(c.points) })) });

export type BenefitLawResult = {
  row: LossRow;
  classification: Classification;
  benefits: BenefitMeasurement[];
  covid: CovidCheck;
  /** 判定に使った窓の loss-rule-v1 の入力（便益なし）。 */
  usedInput: LossInput | null;
  grossLoss: LossResult | null;
  finalLoss: LossResult | null;
  benefitYen: YenRange | null;
  decision: PublishDecision;
  recomputed: { stage: 1 | 2 | 3 | null; direction: 'benefit' | 'harm' | null } | null;
};

/** impact-rule-v1 の国内の判定を、2019年で切った窓（cut=false なら元の窓）でやり直す。 */
export function rejudgeImpact(tables: Tables, indicator: string, start: string, cut: boolean) {
  const mapping = INDICATOR_MAP.find(m => m.indicator === indicator);
  const built = mapping ? buildImpactSeries(tables, mapping, start) : null;
  if (!built) return null;
  const f = <T extends { asOf: string }>(p: T[]) => cut ? cutAtCovid(p) : p;
  const s = built.series;
  const j = judgeImpact({ ...s, target: f(s.target), economy: s.economy ? { ...s.economy, points: f(s.economy.points) } : null });
  return { stage: j.stage, direction: j.direction };
}

export function evaluateBenefit(tables: Tables, row: LossRow, purposes: Row[]): BenefitLawResult {
  const { law, built, result } = row;
  const classification = classifyLaw(purposes, { id: law.id, title: law.title, indicator: law.indicator });
  const w = lossWindow(law.start);
  const applies = overlapsCovid(w.from, w.to);

  let covid: CovidCheck = { applies, separable: !applies, reason: applies ? 'loss-rule-v1 が保留のため、2019年で切った窓は計算しない' : '損失額の窓が2020〜2022年と重ならない' };
  let usedInput: LossInput | null = built && !built.blocked ? built.input : null;
  let grossLoss = built && !built.blocked ? result : null;
  let recomputed: BenefitLawResult['recomputed'] = null;
  if (applies && usedInput && result?.lossYen) {
    const truncated = cutInput(usedInput);
    const truncatedLoss = estimateLoss({ ...truncated, regulationBenefitYen: null });
    recomputed = rejudgeImpact(tables, law.indicator, law.start, true);
    covid = judgeCovidSeparation({
      window: w, postYearsAfterCut: postPoints(truncated).length, original: { stage: law.stage, direction: law.direction },
      recomputed, originalLoss: result, truncatedLoss,
    });
    if (covid.separable) { usedInput = truncated; grossLoss = truncatedLoss; }
  }

  const years = usedInput ? Math.min(postPoints(usedInput).length, MAX_LOSS_YEARS) : MAX_LOSS_YEARS;
  const benefits: BenefitMeasurement[] = classification.kinds === null || classification.kinds.length === 0 || classification.holdReason
    ? [unmeasuredBenefit('目的の分類', `保留：${classification.holdReason}`)]
    : classification.kinds.map(k => measureKind(tables, k, law.start, applies, years));
  const benefitYen = combineBenefits(benefits);
  // v1.1：貢献の法律で未測定があるときは、測った便益だけの合計（下限）を渡しておく。下限で出してよいかは decidePublication の R4 が決める。
  const lowerBoundYen = !benefitYen && law.direction === 'benefit' ? combineBenefits(benefits.filter(b => b.yen !== null)) : null;
  const passed = benefitYen ?? lowerBoundYen;
  const finalLoss = usedInput && grossLoss?.lossYen ? estimateLoss({ ...usedInput, regulationBenefitYen: passed ? passed.median : null }) : null;
  const decision = decidePublication({
    reference: built?.reference ?? false, lossBlocked: built ? built.blocked ?? null : '損失額の入力の対応がない指標',
    originalLoss: result, directionConflict: classification.directionConflict, covid, benefits, grossLoss, finalLoss, direction: law.direction,
  });
  return { row, classification, benefits, covid, usedInput, grossLoss, finalLoss, benefitYen, decision, recomputed };
}

export function evaluateBenefits(tables: Tables, impactRows: ImpactRow[], purposes: Row[]): BenefitLawResult[] {
  return evaluateLosses(tables, impactRows).map(r => evaluateBenefit(tables, r, purposes));
}

/** 同じ便益の系列で窓が重なる法律のまとまり（足さない）。測った系列のある種類だけ。 */
export function benefitGroups(results: BenefitLawResult[]): Map<string, string> {
  const items = results.flatMap(r => r.benefits.filter(b => b.series).map(b => ({ id: `${r.row.law.id}|${b.kind}`, indicator: b.series, start: r.row.law.start })));
  return observationGroups(items);
}

// ---- 表 ----

const windowLabel = (input: LossInput | null) => {
  if (!input) return '';
  const post = postPoints(input);
  return post.length ? `${post[0].asOf.slice(0, 4)}〜${post[post.length - 1].asOf.slice(0, 4)}年の${post.length}年` : '';
};
const rangeCell = (label: string, r: YenRange) => `${label}：中央値=${r.median};第1四分位=${r.low};第3四分位=${r.high}`;

export const CLASSIFICATION_HEADER = ['id', '題名', '指標', '使った第1条', '印', '系統A_種類', '系統A_引用', '系統B_種類', '系統B_引用', '系統B_注記', '種類の一致', '向きの矛盾_A', '向きの矛盾_B', '採用する種類', '保留の理由', '出典URL'];
export function classificationRow(r: BenefitLawResult): string[] {
  const c = r.classification, l = r.row.law;
  const yn = (b: boolean) => b ? '抑える' : 'なし';
  return [
    l.id, l.title, l.indicator, c.texts.map(t => `${t.lawName}（${t.version}）`).join('／'), c.flags.join('／'),
    c.a.kinds.join('・'), c.a.quotes.join('／'), c.b?.kinds.join('・') ?? '', c.b?.quotes.map(q => `「${q}」`).join('／') ?? '', c.b?.note ?? '',
    c.agreed ? '一致' : '不一致', yn(c.a.directionConflict), c.b ? yn(c.b.directionConflict) : '',
    c.kinds === null ? '保留' : c.kinds.join('・') || 'なし', c.holdReason ?? '', c.texts.map(t => t.url).join(' '),
  ];
}

export const BENEFIT_HEADER = ['id', '題名', '便益の種類', '便益の状態', '表示', '便益の額（円）', '未測定の符号', '系列', '効果', 'ばらつき', '理由', '便益グループ'];
export function benefitRows(r: BenefitLawResult, groups: Map<string, string>): string[][] {
  return r.benefits.map(b => [
    r.row.law.id, r.row.law.title, b.kind, b.state, stateLabel(b.state), b.yen ? String(b.yen.median) : '',
    b.yen === null ? (u => `${u.sign}（${u.why}）`)(unmeasuredSign(b)) : '', b.series,
    b.effect === null ? '' : String(b.effect), b.spread === null ? '' : String(b.spread), b.reason, groups.get(`${r.row.law.id}|${b.kind}`) ?? '',
  ]);
}

export const PUBLISH_HEADER = ['id', '題名', '側', '損失または便益', '便益の状態', '判定表の行', '公開可否', '理由'];
export function publishRow(r: BenefitLawResult): string[] {
  const d = r.decision;
  let amount: string;
  if (d.net) amount = `${d.lowerBound ? `${LOWER_BOUND_LABEL}：` : ''}${rangeCell(d.net.median > 0 ? '純損失' : '純便益', d.net)}（円、${windowLabel(r.usedInput)}${r.covid.applies ? '、2019年で切った窓' : ''}）`;
  else if (r.grossLoss?.lossYen && r.covid.separable) amount = `${amountCell(r.grossLoss)}（円、便益を差し引く前、${windowLabel(r.usedInput)}${r.covid.applies ? '、2019年で切った窓' : ''}）`;
  else if (r.row.result?.lossYen) amount = `${amountCell(r.row.result)}（円、loss-v1 の元の窓、便益を差し引く前）`;
  else amount = '保留';
  const reasons = [d.reason];
  if (r.covid.applies && d.row !== 'R3' && d.row !== 'R1') reasons.push(r.covid.reason);
  if (r.classification.flags.length) reasons.push(`第1条の印：${r.classification.flags.join('／')}`);
  reasons.push(`独立でない：観測グループ ${r.row.group} の中の額は足さない`);
  return [r.row.law.id, r.row.law.title, sideLabel(r.row.law.direction), amount, r.benefits.map(b => `${b.kind}：${stateLabel(b.state)}`).join('／'), d.row, d.publishable ? '公開可' : '公開不可', reasons.join('／')];
}

