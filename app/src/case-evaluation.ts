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
 * 金融再生プログラムの評価仕様の下書き。実在評価として成立していません。
 * 伊藤（2002副大臣・2005大臣）は同一人物の公式在職記録が未確認、影響段階と対照群は未確定です。
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
    id: 'npl-ratio-major-banks', position: 'for', domain: 'economy', direction: 'benefit', impact: null, comparison: null,
    citationIds: ['danwa20050525', 'ito20050525'],
    rationale: '主要行の不良債権比率が8.4%から2.9%へ下がったと実施主体が発表している。',
    counterEvidence: '査定の厳格化、貸出の増減、対象行の範囲でも比率は動く。',
    alternativeExplanation: '日銀の量的緩和、輸出回復、りそな救済などの交絡を分離していない。',
    criterionVersion: 'outcome-v1', analysisVersion: 'draft-1', evaluatedAt: '2026-10-13T00:00:00Z',
    scopeReason: '主要行の不良債権比率に限る。GDPへの経路は未確立。', durationReason: '2002-10-30の公表から2005-05-25の目標達成発表まで。', magnitudeReason: '未確定（対照群の結果で決める）。',
  }],
};
