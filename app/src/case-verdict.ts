import caseSource from '../../data/distribution/case-source.json';
import { canonical, sha256Hex, validateVerification } from '../../scripts/verification_binding.mjs';
import { buildCaseEvaluationInput, FINANCIAL_REVIVAL_DRAFT, TABLE1_NPL_RATIO, type CaseMaterialText, type CaseSource } from './case-evaluation';
import { evaluateEvidence, sha256, type EvidenceEvaluationInput, type TrustedContext } from './evidence-evaluation';
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

/** evidence_pipeline の受領書。信頼へ写す前に validateVerification で入力束縛を確認する。 */
export type EvidenceReceipt = {
  inputHash: string;
  verifierId: string;
  verifierVersion: string;
  resolvedPersonIds: readonly string[];
  actionRevisions: readonly { id: string; revisionId: string }[];
  assessmentRevisions: readonly { id: string; revisionId: string }[];
};
/** texts は評価入力を組む保存本文。readback は独立再読。受領書が無いときは信頼集合を空のままにする。 */
export type CaseVerdictEvidence = {
  texts: ReadonlyMap<string, CaseMaterialText>;
  readback?: ReadonlyMap<string, CaseMaterialText>;
  receipt?: EvidenceReceipt | null;
};

const heldPerson = (personId: string, name: string, heldReason: string): PersonVerdict => ({ personId, name, status: 'held', score: null, direction: null, heldReason });
const VERIFICATION_REJECTION = new Set(['独立検証の入力束縛が不一致です', '人物検証の参照が不正です', '改訂検証が重複または不正です', '検証した改訂が入力と不一致です', '未許可の入力フィールドです']);

function acceptReceipt(input: EvidenceEvaluationInput, receipt: EvidenceReceipt) {
  try {
    const bound = validateVerification(input, structuredClone(receipt), sha256Hex(canonical(input)), sha256Hex);
    const actionRevisions = new Map(bound.actionRevisions.map(entry => [entry.id, entry.revisionId]));
    const assessmentRevisions = new Map(bound.assessmentRevisions.map(entry => [entry.id, entry.revisionId]));
    return {
      resolvedPersonIds: new Set(bound.resolvedPersonIds),
      verifiedActionIds: new Set(actionRevisions.keys()),
      verifiedAssessmentIds: new Set(assessmentRevisions.keys()),
      verifiedActionRevisions: actionRevisions,
      verifiedAssessmentRevisions: assessmentRevisions,
    };
  } catch (error) {
    if (error instanceof Error && VERIFICATION_REJECTION.has(error.message)) return null;
    throw error;
  }
}

/** 引用文を本文にせず、受領書が無い実在人物は加点しない。指標の段階は人物の点数と分ける。 */
export async function computeCaseVerdict(source: CaseSource = caseSource as CaseSource, evidence?: CaseVerdictEvidence): Promise<CaseVerdict> {
  const spec = FINANCIAL_REVIVAL_DRAFT;
  const series = spec.assessments[0].series!;
  const judgement = judgeImpact(series);
  const t = TABLE1_NPL_RATIO;
  const majorChange = r1(t.major.to - t.major.from), regionalChange = r1(t.regional.to - t.regional.from);
  const gaps = series.target.filter(p => p.asOf < series.start).slice(-5).map(p => p.treated - p.control);
  const measurements = { judgement, table1: { majorChange, regionalChange, diffInDiff: r1(majorChange - regionalChange) },
    series: { definition: series.definition, start: series.start, preGapMin: Math.min(...gaps), preGapMax: Math.max(...gaps), preYears: gaps.length } };
  if (!evidence?.texts) return { ...measurements, persons: spec.people.map(p => heldPerson(p.personId, p.name, '人物照合が未検証です')) };

  const { input } = await buildCaseEvaluationInput(source, spec, evidence.texts);
  const readback = evidence.readback ?? evidence.texts;
  const materials = new Map(input.materials.map(m => [m.id, m]));
  // runEvidencePipeline と同じく、信頼は空から始め、束縛を通過した受領書だけを写す。
  const trusted: TrustedContext = {
    readMaterial: async id => {
      const material = materials.get(id);
      const stored = readback.get(id);
      if (!material || !stored || typeof stored.text !== 'string') return null;
      const contentHash = await sha256(stored.text);
      return { url: material.url, originalHash: stored.originalHash ?? contentHash, contentHash, observedAt: stored.observedAt, publishedAt: stored.publishedAt, text: stored.text };
    },
    resolvedPersonIds: new Set(), verifiedActionIds: new Set(), verifiedAssessmentIds: new Set(),
    verifiedActionRevisions: new Map(), verifiedAssessmentRevisions: new Map(),
  };
  const accepted = evidence.receipt ? acceptReceipt(input, evidence.receipt) : null;
  if (accepted) Object.assign(trusted, accepted);
  const result = await evaluateEvidence(input, trusted);
  const order = spec.people.map(p => p.personId);
  const persons = [...result.rows].sort((x, y) => order.indexOf(x.person.id) - order.indexOf(y.person.id)).map(row => {
    const held = result.held.find(item => item.personId === row.person.id);
    const name = spec.people.find(p => p.personId === row.person.id)?.name ?? row.person.name;
    return row.score === null ? heldPerson(row.person.id, name, held?.reason ?? '根拠が不足しています')
      : { personId: row.person.id, name, status: 'scored' as const, score: row.score, direction: spec.options.direction, heldReason: null };
  });
  return { ...measurements, persons };
}
