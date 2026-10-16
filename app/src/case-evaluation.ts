import { actionIdentity, actionRevision, sha256, type EvidenceAction, type EvidenceEvaluationInput, type Material, type PositionAssessment, type QuoteRef } from './evidence-evaluation';
import { judgeImpact, type ImpactSeries } from './impact-rule';
import type { Involvement, RankingOptions } from './ranking';

/** 公開配布版の事例（data/distribution/case-source.json）のうち、評価入力へ写す部分だけです。 */
export type CaseCitation = { id: string; url: string; quote: string };
export type CaseActor = { id: string; label: string; date: string; action: string; citationIds: string[] };
export type CaseSource = { caseId: string; observationFrom: string; observationTo: string; actors: CaseActor[]; citations: CaseCitation[] };

/** 役割・立場・同一人物の束ねは事例文から推定せず、人間が書いた評価仕様だけから取ります。 */
export type CasePersonSpec = { personId: string; name: string; roleClass?: string; actorIds: string[]; role: Involvement['role']; position: 'for' | 'against' };
/** 対照群つきの比較。無ければ前後比較（association）として結果期間評価では保留になります。 */
export type CaseComparison = { treatedGroup: string; controlGroup: string; observationFrom: string; observationTo: string; citations: CaseCitation[] };
export type CaseAssessmentSpec = Pick<PositionAssessment, 'domain' | 'direction' | 'rationale' | 'counterEvidence' | 'alternativeExplanation' | 'criterionVersion' | 'analysisVersion' | 'evaluatedAt' | 'scopeReason' | 'durationReason' | 'magnitudeReason'> & {
  id: string; position: 'for' | 'against'; impact: 1 | 2 | 3 | null; citationIds: string[]; comparison: CaseComparison | null;
  /** 実測の系列。あれば影響段階は判定ルール（impact-rule.ts、設計決定0007）で決め、impact は null にしておきます。 */
  series?: ImpactSeries;
};
export type CaseEvaluationSpec = { mode: EvidenceEvaluationInput['mode']; namespace: string; policyId: string; policyVersion: string; outcomeId: string; options: RankingOptions; people: CasePersonSpec[]; assessments: CaseAssessmentSpec[] };
/** 保存原本の本文。引用は本文中の位置で照合します（引用文そのものを本文とみなす推定はしません）。 */
export type CaseMaterialText = { text: string; observedAt: string; publishedAt: string | null; originalHash?: string };
export type CaseConversion = { input: EvidenceEvaluationInput; notes: { assessmentId: string; reason: string }[] };

const fail = (message: string): never => { throw new Error(message); };

export async function buildCaseEvaluationInput(source: CaseSource, spec: CaseEvaluationSpec, texts: ReadonlyMap<string, CaseMaterialText>): Promise<CaseConversion> {
  const citations = new Map<string, CaseCitation>();
  const addCitation = (c: CaseCitation) => { if (citations.has(c.id) && citations.get(c.id)!.url !== c.url) fail('引用IDが競合しています'); citations.set(c.id, c); };
  source.citations.forEach(addCitation);
  spec.assessments.forEach(a => a.comparison?.citations.forEach(addCitation));
  const actors = new Map(source.actors.map(a => [a.id, a]));
  const materials = new Map<string, Material>();
  const quotesFor = async (ids: string[]): Promise<QuoteRef[]> => Promise.all(ids.map(async id => {
    const citation = citations.get(id) ?? fail(`引用 ${id} が事例にありません`);
    const stored = texts.get(id) ?? fail(`引用 ${id} の保存原本がありません`);
    const start = stored.text.indexOf(citation.quote);
    if (start < 0) fail(`引用 ${id} が保存原本の本文に見つかりません`);
    if (!materials.has(id)) {
      const contentHash = await sha256(stored.text);
      materials.set(id, { id, url: citation.url, originalHash: stored.originalHash ?? contentHash, contentHash, observedAt: stored.observedAt, publishedAt: stored.publishedAt });
    }
    return { materialId: id, start, end: start + citation.quote.length, text: citation.quote };
  }));

  const usedActors = new Set<string>();
  const actions: EvidenceAction[] = [];
  for (const person of spec.people) {
    if (!person.actorIds.length) fail(`${person.personId} に行動がありません`);
    for (const actorId of person.actorIds) {
      const actor = actors.get(actorId) ?? fail(`行動 ${actorId} が事例にありません`);
      if (usedActors.has(actorId)) fail(`行動 ${actorId} が複数人物に割り当てられています`);
      usedActors.add(actorId);
      const identity = { namespace: spec.namespace, sourceActionId: actor.id, sourceActorId: person.personId, policyId: spec.policyId };
      const semantic = { ...identity, personId: person.personId, policyVersion: spec.policyVersion, actionDate: actor.date, role: person.role, position: person.position,
        description: actor.action, quotes: await quotesFor(actor.citationIds), interventionId: source.caseId, outcomeId: spec.outcomeId };
      actions.push({ ...semantic, actionId: await actionIdentity(identity), revisionId: await actionRevision(semantic) });
    }
  }

  const notes: CaseConversion['notes'] = [];
  const assessments: PositionAssessment[] = [];
  for (const a of spec.assessments) {
    let impact = a.impact;
    if (a.series) {
      if (a.impact !== null) fail(`${a.id} は実測の系列を持つので、影響段階を手で入れず判定ルールに任せてください`);
      const judged = judgeImpact(a.series);
      notes.push({ assessmentId: a.id, reason: `判定ルール ${judged.ruleVersion}: ${judged.reason}` });
      if (judged.direction !== null && judged.direction !== a.direction) { notes.push({ assessmentId: a.id, reason: '判定ルールの向きが仕様の向きと逆のため分析を作りません' }); continue; }
      impact = judged.stage;
    }
    // 影響段階が未確定のまま仮の値を置かない。分析を作らず、評価器側で「影響根拠不足」として保留させる。
    if (impact === null) { notes.push({ assessmentId: a.id, reason: '影響の段階が未確定のため分析を作りません' }); continue; }
    const { comparison, citationIds, impact: _manual, series: _series, ...rest } = a;
    assessments.push({ ...rest, impact, policyId: spec.policyId, policyVersion: spec.policyVersion, outcomeId: spec.outcomeId,
      quotes: await quotesFor([...citationIds, ...(comparison?.citations.map(c => c.id) ?? [])]),
      observationFrom: comparison?.observationFrom ?? source.observationFrom, observationTo: comparison?.observationTo ?? source.observationTo,
      implementationStatus: 'implemented', evaluationKind: 'observed', evidenceMethod: comparison ? 'quantitative' : 'association' });
    if (!comparison) notes.push({ assessmentId: a.id, reason: '対照群が無く前後比較のみです' });
  }
  const people = spec.people.map(({ personId, name, roleClass }) => ({ id: personId, name, ...(roleClass ? { roleClass } : {}) }));
  return { input: { schemaVersion: 'evidence-evaluation/v1', mode: spec.mode, options: spec.options, people, materials: [...materials.values()], actions, assessments }, notes };
}

/**
 * 金融再生プログラムの評価仕様。独立検証と原本readbackを通るまでは実在評価として成立していません。
 * 影響段階は判定ルール（impact-rule.ts、設計決定0007）が実測の系列から決めます。2026-10-13の人間判断（段階1）は、ルール導入で置き換えました。比較群の系列は金融庁「（表６）リスク管理債権額等の推移」で平成10年3月期まで遡ったもの（docs/reports/fsa-npl-backfill-1997.md）。判定は段階1（2026-10-14）。
 * 伊藤（2002副大臣・2005大臣）は同一人物の公式在職記録が未確認です。
 */
export const FINANCIAL_REVIVAL_DRAFT: CaseEvaluationSpec = {
  mode: 'real', namespace: 'fsa-financial-revival-2002', policyId: 'fsa-financial-revival-2002', policyVersion: '2002-10-30', outcomeId: 'major-bank-npl-ratio',
  options: { domain: 'economy', direction: 'benefit', period: 'custom', dateFrom: '2002-10-30', dateTo: '2005-05-25', asOf: '2026-10-13', weights: { economy: 100, technology: 0 }, timeBasis: 'outcome' },
  people: [
    { personId: 'takenaka-heizo', name: '竹中平蔵', roleClass: '金融担当大臣（民間閣僚）', actorIds: ['takenaka-20021030', 'takenaka-20021129'], role: 'lead', position: 'for' },
    { personId: 'ito-fsa', name: '伊藤（金融担当副大臣→大臣）', roleClass: '金融担当副大臣・大臣', actorIds: ['ito-20021030', 'ito-20050525'], role: 'coauthor', position: 'for' },
    { personId: 'okamoto-fsa', name: '岡本（金融危機対応室長）', roleClass: '行政官', actorIds: ['okamoto-20021219'], role: 'context', position: 'for' },
  ],
  assessments: [{
    id: 'npl-ratio-major-banks', position: 'for', domain: 'economy', direction: 'benefit', impact: null,
    series: {
      definition: '金融庁「（表６）リスク管理債権額等の推移」（平成19年版）のリスク管理債権÷貸出金×100（％、小数2桁）。主要行は平成14年3月期まで都銀・信託・興銀、平成15年3月期から都銀・信託（表の定義どおり。新生・あおぞらは全期間除く）。地域銀行＝地方銀行・第二地方銀行。docs/reports/fsa-npl-backfill-1997.md',
      start: '2002-10-30', better: 'lower', economy: null, sectorGdpShare: null,
      target: [
        { asOf: '1998-03-31', treated: 5.51, control: 4.15 }, { asOf: '1999-03-31', treated: 6.32, control: 5.03 }, { asOf: '2000-03-31', treated: 5.82, control: 5.90 },
        { asOf: '2001-03-31', treated: 5.72, control: 7.33 }, { asOf: '2002-03-31', treated: 9.16, control: 8.00 }, { asOf: '2003-03-31', treated: 7.79, control: 7.87 },
        { asOf: '2004-03-31', treated: 5.54, control: 6.93 }, { asOf: '2005-03-31', treated: 3.10, control: 5.60 }, { asOf: '2006-03-31', treated: 1.89, control: 4.58 },
        { asOf: '2007-03-31', treated: 1.67, control: 4.02 },
      ],
    },
    // 引用文は Mac 側で保存した業態別表（CSV）の行。xlsx は読み戻し対象外で、引用文はセルの文字列そのものではない（見出しは「17年3月期」の形）。
    // 数値は openpyxl で別に確認済み（主要行 14年3月期 8.4・17年3月期 2.9、地域銀行 8.0・5.5）。判定結果の数値には使わない。
    comparison: { treatedGroup: '主要行', controlGroup: '地域銀行', observationFrom: '2002-03-31', observationTo: '2005-03-31',
      citations: [{ id: 'fsaNplTable1', url: 'https://www.fsa.go.jp/status/npl/20070809/data01.xlsx', quote: '平成17年3月期,主要行,2.9' }] },
    citationIds: ['danwa20050525', 'ito20050525'],
    rationale: 'リスク管理債権比率で、主要行は平成14年3月期9.16%から平成17年3月期3.10%へ下がり、地域銀行（8.00%→5.60%）より大きく下がった。判定ルールの効果（開始後2〜5年目の差の平均−開始前5年の差の平均）は−2.66ポイントで、平成19年3月期まで同じ向きが続いた。',
    counterEvidence: '開始前の差は平成10〜14年3月期に+1.36〜−1.61ポイントと揺れ（ばらつき1.28）、平成14年3月期だけ主要行が大きく悪化しているため、差の一部は揺り戻しの可能性がある。主要行の範囲は平成15年3月期に変わる（興銀が抜ける）。当時の発表値とは平成12〜14年3月期で0.26〜0.43ポイント違う。査定の厳格化や債権売却でも比率は下がる。',
    alternativeExplanation: '日銀の量的緩和、輸出回復、りそな救済、再生専門子会社の算入時期の違い、埼玉りそな銀行の地域銀行への編入を分離していない。地域銀行にもリレーションシップバンキングの行動計画がかかっていた。',
    criterionVersion: 'outcome-v1', analysisVersion: 'did-1', evaluatedAt: '2026-10-13T00:00:00Z',
    scopeReason: '主要行（都銀・信託）の不良債権比率に限る。GDPや貸出への経路は未確立。', durationReason: '平成14年3月期から平成17年3月期。差は平成19年3月期まで持続。', magnitudeReason: '効果−2.66ポイント（ばらつき1.28の2倍を超える）。段階は判定ルールが系列から決める。',
  }],
};

/**
 * 金融庁「（表１）金融再生法開示債権等の推移」の不良債権比率（％、公表値、小数第1位）。
 * 値の出どころは docs/reports/fsa-financial-revival-2002.md 第2・3節（Excel と PDF で一致を確認、独立検証は未実施）。
 * 判定ルールの系列（表６、リスク管理債権）とは別の表です。ここは「参考の差の差」にだけ使い、段階は決めません。
 */
export const TABLE1_NPL_RATIO = {
  source: '金融庁「（表１）金融再生法開示債権等の推移」（平成19年3月期、平成19年8月9日公表）不良債権比率',
  report: 'docs/reports/fsa-financial-revival-2002.md',
  from: '平成14年3月期', to: '平成17年3月期',
  major: { from: 8.4, to: 2.9 }, regional: { from: 8.0, to: 5.5 },
} as const;
