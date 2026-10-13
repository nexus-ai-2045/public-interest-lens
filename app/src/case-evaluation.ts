import { actionIdentity, actionRevision, sha256, type EvidenceAction, type EvidenceEvaluationInput, type Material, type PositionAssessment, type QuoteRef } from './evidence-evaluation';
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
    // 影響段階が未確定のまま仮の値を置かない。分析を作らず、評価器側で「影響根拠不足」として保留させる。
    if (a.impact === null) { notes.push({ assessmentId: a.id, reason: '影響の段階が未確定のため分析を作りません' }); continue; }
    const { comparison, citationIds, impact, ...rest } = a;
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
 * 影響段階1（限定的）は2026-10-13の人間判断。比較群は金融庁「（表１）金融再生法開示債権等の推移」（docs/reports/fsa-financial-revival-2002.md）。
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
    id: 'npl-ratio-major-banks', position: 'for', domain: 'economy', direction: 'benefit', impact: 1,
    // 引用文は Mac 側で保存した業態別表（CSV）の行。原本readbackでの一致は独立検証で確かめる。
    comparison: { treatedGroup: '主要行', controlGroup: '地域銀行', observationFrom: '2002-03-31', observationTo: '2005-03-31',
      citations: [{ id: 'fsaNplTable1', url: 'https://www.fsa.go.jp/status/npl/20070809/data01.xlsx', quote: '平成17年3月期,主要行,2.9' }] },
    citationIds: ['danwa20050525', 'ito20050525'],
    rationale: '主要行の不良債権比率は平成14年3月期8.4%から平成17年3月期2.9%へ下がり、同期間の地域銀行（8.0%→5.5%）との差の差は−3.0ポイント。差は平成19年3月期まで続いた。',
    counterEvidence: '開始前（平成12→14年3月期）に主要行は地域銀行より1.2ポイント多く悪化しており、差の一部は揺り戻しの可能性がある。査定の厳格化や債権売却でも比率は下がる。',
    alternativeExplanation: '日銀の量的緩和、輸出回復、りそな救済、再生専門子会社の算入時期の違い、埼玉りそな銀行の地域銀行への編入を分離していない。地域銀行にもリレーションシップバンキングの行動計画がかかっていた。',
    criterionVersion: 'outcome-v1', analysisVersion: 'did-1', evaluatedAt: '2026-10-13T00:00:00Z',
    scopeReason: '主要行（都銀・信託）の不良債権比率に限る。GDPや貸出への経路は未確立。', durationReason: '平成14年3月期から平成17年3月期。差は平成19年3月期まで持続。', magnitudeReason: '差の差−3.0ポイント。経済全体への経路が未確立のため、段階1（限定的）とした（2026-10-13の人間判断）。',
  }],
};
