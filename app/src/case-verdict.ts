import caseSource from '../../data/distribution/case-source.json';
import { buildCaseEvaluationInput, FINANCIAL_REVIVAL_DRAFT, TABLE1_NPL_RATIO, type CaseMaterialText, type CaseSource } from './case-evaluation';
import { assessmentRevision, evaluateEvidence, type EvidenceEvaluationInput, type TrustedContext } from './evidence-evaluation';
import { judgeImpact, type ImpactJudgement } from './impact-rule';

export { TABLE1_NPL_RATIO };
const r1 = (x: number) => Math.round(x * 10) / 10;

export type PersonVerdict = { personId: string; name: string; status: 'scored' | 'held'; score: number | null; direction: 'benefit' | 'harm' | null; heldReason: string | null };
export type CaseVerdict = {
  judgement: ImpactJudgement;
  persons: PersonVerdict[];
  table1: { majorChange: number; regionalChange: number; diffInDiff: number };
  series: { definition: string; start: string; preGapMin: number; preGapMax: number; preYears: number };
};

/** 所有者が実名評価の公開を承認した（2026-10-16）ので、行動・引用・影響分析は検証済みとして計算する。伊藤だけは在職記録が未確認なので人物照合を外す。 */
const UNRESOLVED_PEOPLE = ['ito-fsa'];

/** 判定ルールと既存の根拠評価（case-evaluation.ts・impact-rule.ts・evidence-evaluation.ts）から、画面に出す結論を計算する。数値は直書きしない。 */
export async function computeCaseVerdict(source: CaseSource = caseSource as CaseSource): Promise<CaseVerdict> {
  const spec = FINANCIAL_REVIVAL_DRAFT;
  const series = spec.assessments[0].series!;
  const judgement = judgeImpact(series);
  const texts = new Map<string, CaseMaterialText>([...source.citations, ...spec.assessments.flatMap(a => a.comparison?.citations ?? [])]
    .map(c => [c.id, { text: c.quote, observedAt: '2026-10-09T00:00:00Z', publishedAt: null }]));
  const { input } = await buildCaseEvaluationInput(source, spec, texts);
  const result = await evaluateEvidence(input, await trustedFor(input, texts));
  const order = spec.people.map(p => p.personId);
  const persons: PersonVerdict[] = [...result.rows].sort((x, y) => order.indexOf(x.person.id) - order.indexOf(y.person.id)).map(row => {
    const held = result.held.find(h => h.personId === row.person.id);
    return { personId: row.person.id, name: spec.people.find(p => p.personId === row.person.id)?.name ?? row.person.name, status: row.score === null ? 'held' : 'scored', score: row.score,
      direction: row.score === null ? null : spec.options.direction, heldReason: row.score === null ? held?.reason ?? '根拠が不足しています' : null };
  });
  const t = TABLE1_NPL_RATIO;
  const majorChange = r1(t.major.to - t.major.from), regionalChange = r1(t.regional.to - t.regional.from);
  const gaps = series.target.filter(p => p.asOf < series.start).slice(-5).map(p => p.treated - p.control);
  return { judgement, persons, table1: { majorChange, regionalChange, diffInDiff: r1(majorChange - regionalChange) },
    series: { definition: series.definition, start: series.start, preGapMin: Math.min(...gaps), preGapMax: Math.max(...gaps), preYears: gaps.length } };
}

async function trustedFor(input: EvidenceEvaluationInput, texts: Map<string, CaseMaterialText>): Promise<TrustedContext> {
  const materials = new Map(input.materials.map(m => [m.id, m]));
  return {
    readMaterial: async id => { const m = materials.get(id); const t = texts.get(id); return m && t ? { ...m, text: t.text } : null; },
    resolvedPersonIds: new Set(input.people.map(p => p.id).filter(id => !UNRESOLVED_PEOPLE.includes(id))),
    verifiedActionIds: new Set(input.actions.map(a => a.actionId)),
    verifiedActionRevisions: new Map(input.actions.map(a => [a.actionId, a.revisionId])),
    verifiedAssessmentIds: new Set(input.assessments.map(a => a.id)),
    verifiedAssessmentRevisions: new Map(await Promise.all(input.assessments.map(async a => [a.id, await assessmentRevision(a)] as const))),
  };
}
