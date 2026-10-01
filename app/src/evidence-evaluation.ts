import { ROLE_FACTOR, type Direction, type Involvement, type Person, type RankingOptions, type RankingRow, sumRounded, assignRanks } from './ranking';

export type ActionIdentity = { namespace: string; sourceActionId: string; sourceActorId: string; policyId: string };
const canonical = (value: unknown): string => {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
  return JSON.stringify(value);
};
export async function sha256(text: string): Promise<string> {
  return [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(v => v.toString(16).padStart(2, '0')).join('');
}
export const actionIdentity = (action: ActionIdentity): Promise<string> => sha256(canonical([action.namespace, action.sourceActionId, action.sourceActorId, action.policyId]));
export const actionRevision = (semanticContent: unknown): Promise<string> => sha256(canonical(semanticContent));

/** 正規化した保存本文上のUTF-16 code unit位置、endは排他的。本文を再正規化して照合しない。 */
export type QuoteRef = { materialId: string; start: number; end: number; text: string };
export type Material = { id: string; url: string; originalHash: string; contentHash: string; observedAt: string; publishedAt: string | null };
export type EvidenceAction = ActionIdentity & { actionId: string; revisionId: string; personId: string; policyVersion: string; actionDate: string; role: Involvement['role']; position: 'for' | 'against' | 'not_voted' | 'unknown'; description: string; quotes: QuoteRef[] };
export type PositionAssessment = { id: string; policyId: string; policyVersion: string; position: 'for' | 'against'; domain: 'economy' | 'technology'; direction: Direction; impact: 1 | 2 | 3; rationale: string; counterEvidence: string; alternativeExplanation: string; criterionVersion: string; analysisVersion: string; evaluatedAt: string; quotes: QuoteRef[] };
export type EvidenceEvaluationInput = { schemaVersion: 'evidence-evaluation/v1'; mode: 'real' | 'test-only'; options: RankingOptions; people: Person[]; materials: Material[]; actions: EvidenceAction[]; assessments: PositionAssessment[] };
export type TrustedContext = { readMaterial: (id: string) => Promise<({ text: string } & Omit<Material, 'id'>) | null>; resolvedPersonIds: ReadonlySet<string>; verifiedActionIds: ReadonlySet<string>; verifiedAssessmentIds: ReadonlySet<string>; verifiedActionRevisions: ReadonlyMap<string, string>; verifiedAssessmentRevisions: ReadonlyMap<string, string> };
export type HeldReason = { personId?: string; policyId?: string; actionId?: string; reason: string };
export type EvidenceEvaluationResult = { mode: 'real' | 'test-only'; rows: RankingRow[]; held: HeldReason[]; coverage: { inputActions: number; assessedActions: number; readableMaterials: number }; publicationStatus: 'requires_human_review' };
export const assessmentRevision = (assessment: PositionAssessment): Promise<string> => actionRevision(assessment);
const requireValid = (value: boolean, message: string): void => { if (!value) throw new Error(message); };
const nonempty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const hashValid = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const dateValid = (value: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const instantValid = (value: string): boolean => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && dateValid(value.slice(0, 10)) && !Number.isNaN(Date.parse(value));
function keys(value: object, allowed: string[]): void {
  requireValid(value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).every(key => allowed.includes(key)), '未許可の入力フィールドです');
}
function unique<T extends { id: string }>(items: T[]): Map<string, T> {
  requireValid(Array.isArray(items), '一覧が不正です');
  const map = new Map<string, T>();
  for (const item of items) { requireValid(nonempty(item.id) && !map.has(item.id), 'IDが空または重複しています'); map.set(item.id, item); }
  return map;
}
function validateQuotes(quotes: QuoteRef[], materials: Map<string, Material>): void {
  requireValid(Array.isArray(quotes) && quotes.length > 0, '引用がありません');
  for (const q of quotes) {
    keys(q, ['materialId', 'start', 'end', 'text']);
    requireValid(materials.has(q.materialId) && Number.isSafeInteger(q.start) && Number.isSafeInteger(q.end) && q.start >= 0 && q.end > q.start && nonempty(q.text) && q.end - q.start === q.text.length, '引用の参照または範囲が不正です');
  }
}
/** 実資料入口。信頼状態は入力JSONではなく、独立した検証実行の文脈からだけ供給する。 */
export async function evaluateEvidence(input: EvidenceEvaluationInput, trusted: TrustedContext): Promise<EvidenceEvaluationResult> {
  keys(input, ['schemaVersion', 'mode', 'options', 'people', 'materials', 'actions', 'assessments']);
  requireValid(input.schemaVersion === 'evidence-evaluation/v1' && ['real', 'test-only'].includes(input.mode), '評価スキーマまたはモードが不正です');
  const o = input.options;
  keys(o, ['domain', 'direction', 'period', 'asOf', 'weights']); keys(o.weights, ['economy', 'technology']);
  requireValid(dateValid(o.asOf) && [2, 4, 8, 'cumulative'].includes(o.period) && ['economy', 'technology', 'overall', 'fiscal', 'security', 'governance'].includes(o.domain) && ['benefit', 'harm'].includes(o.direction), '評価条件が不正です');
  requireValid(Object.values(o.weights).length === 2 && ['economy', 'technology'].every(k => { const n = o.weights[k as 'economy' | 'technology']; return typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 100; }), '重みが不正です');
  const people = unique(input.people); const materials = unique(input.materials); const assessments = unique(input.assessments);
  for (const p of people.values()) { keys(p, ['id', 'name', 'house', 'district', 'electionIds', 'roleClass']); requireValid(nonempty(p.name), '人物名がありません'); }
  for (const m of materials.values()) {
    keys(m, ['id', 'url', 'originalHash', 'contentHash', 'observedAt', 'publishedAt']);
    let validUrl = false; try { const url = new URL(m.url); validUrl = url.protocol === 'https:' && !url.username && !url.password; } catch { /* 不正URL */ }
    requireValid(validUrl && hashValid(m.originalHash) && hashValid(m.contentHash) && instantValid(m.observedAt) && (m.publishedAt === null || dateValid(m.publishedAt)), '資料のURL・ハッシュ・日時が不正です');
  }
  const assessmentKeys = new Set<string>();
  for (const a of assessments.values()) {
    keys(a, ['id', 'policyId', 'policyVersion', 'position', 'domain', 'direction', 'impact', 'rationale', 'counterEvidence', 'alternativeExplanation', 'criterionVersion', 'analysisVersion', 'evaluatedAt', 'quotes']);
    requireValid([a.policyId, a.policyVersion, a.rationale, a.counterEvidence, a.alternativeExplanation, a.criterionVersion, a.analysisVersion].every(nonempty) && instantValid(a.evaluatedAt) && ['for', 'against'].includes(a.position) && ['economy', 'technology'].includes(a.domain) && ['benefit', 'harm'].includes(a.direction) && [1, 2, 3].includes(a.impact), '影響分析が不正です');
    validateQuotes(a.quotes, materials);
    const key = canonical([a.policyId, a.policyVersion, a.position, a.domain, a.direction]);
    requireValid(!assessmentKeys.has(key), '同じ分野・方向の影響分析が競合しています'); assessmentKeys.add(key);
  }
  requireValid(Array.isArray(input.actions), '行動一覧が不正です');
  const actions = new Map<string, EvidenceAction>();
  for (const a of input.actions) {
    keys(a, ['namespace', 'sourceActionId', 'sourceActorId', 'policyId', 'actionId', 'revisionId', 'personId', 'policyVersion', 'actionDate', 'role', 'position', 'description', 'quotes']);
    requireValid([a.namespace, a.sourceActionId, a.sourceActorId, a.policyId, a.policyVersion, a.description].every(nonempty) && people.has(a.personId) && dateValid(a.actionDate) && Object.hasOwn(ROLE_FACTOR, a.role) && ['for', 'against', 'not_voted', 'unknown'].includes(a.position), '行動が不正です');
    validateQuotes(a.quotes, materials);
    const { actionId, revisionId, ...semantic } = a;
    requireValid(hashValid(actionId) && hashValid(revisionId) && actionId === await actionIdentity(a) && revisionId === await actionRevision(semantic), '行動IDまたは改訂IDが不一致です');
    const old = actions.get(actionId);
    requireValid(!old || canonical(old) === canonical(a), '同じ行動の複数改訂が競合しています'); actions.set(actionId, a);
  }
  const texts = new Map<string, string>();
  for (const m of materials.values()) {
    let stored: Awaited<ReturnType<TrustedContext['readMaterial']>> = null;
    try { stored = await trusted.readMaterial(m.id); } catch { /* 読めない資料は保留 */ }
    if (stored && stored.url === m.url && stored.originalHash === m.originalHash && stored.contentHash === m.contentHash && stored.observedAt === m.observedAt && stored.publishedAt === m.publishedAt && typeof stored.text === 'string' && await sha256(stored.text) === m.contentHash) texts.set(m.id, stored.text);
  }
  const quotesMatch = (quotes: QuoteRef[]) => quotes.every(q => texts.has(q.materialId) && texts.get(q.materialId)!.slice(q.start, q.end) === q.text);
  const startDate = new Date(`${o.asOf}T00:00:00Z`); if (o.period !== 'cumulative') startDate.setUTCFullYear(startDate.getUTCFullYear() - o.period);
  const start = o.period === 'cumulative' ? null : startDate.toISOString().slice(0, 10);
  const selectedActions = [...actions.values()].filter(a => a.actionDate <= o.asOf && (!start || a.actionDate >= start));
  const held: HeldReason[] = []; let assessedActions = 0;
  const validAssessments = new Set<string>();
  for (const a of assessments.values()) if (trusted.verifiedAssessmentIds.has(a.id) && trusted.verifiedAssessmentRevisions?.get(a.id) === await assessmentRevision(a) && quotesMatch(a.quotes)) validAssessments.add(a.id);
  const weightTotal = o.weights.economy + o.weights.technology;
  const rows = input.people.map(person => {
    const contributions: RankingRow['contributions'] = []; let heldCount = 0;
    const grouped = new Map<string, EvidenceAction[]>();
    for (const a of selectedActions) if (a.personId === person.id) { const group = grouped.get(a.policyId) ?? []; group.push(a); grouped.set(a.policyId, group); }
    const hold = (policyId: string, reason: string) => { heldCount++; held.push({ personId: person.id, policyId, reason }); };
    for (const [policyId, group] of grouped) {
      if (!trusted.resolvedPersonIds.has(person.id)) { hold(policyId, '人物照合が未検証です'); continue; }
      if (new Set(group.map(a => a.position)).size !== 1 || new Set(group.map(a => a.policyVersion)).size !== 1) { hold(policyId, '同じ政策への立場または政策版が競合しています'); continue; }
      if (!['for', 'against'].includes(group[0].position)) { hold(policyId, '個人の賛否が確認できません'); continue; }
      if (!['economy', 'technology', 'overall'].includes(o.domain) || (o.domain === 'overall' && weightTotal === 0)) { hold(policyId, '評価分野または重みが未評価です'); continue; }
      const eligible = group.filter(a => ROLE_FACTOR[a.role] > 0 && trusted.verifiedActionIds.has(a.actionId) && trusted.verifiedActionRevisions?.get(a.actionId) === a.revisionId && quotesMatch(a.quotes));
      if (!eligible.length) { hold(policyId, '行動または引用が未検証です'); continue; }
      eligible.sort((a, b) => ROLE_FACTOR[b.role] - ROLE_FACTOR[a.role] || a.actionDate.localeCompare(b.actionDate) || a.actionId.localeCompare(b.actionId));
      const action = eligible[0];
      const relevant = [...assessments.values()].filter(a => a.policyId === policyId && a.policyVersion === action.policyVersion && a.position === action.position && a.direction === o.direction && (o.domain === 'overall' || a.domain === o.domain) && (o.domain !== 'overall' || o.weights[a.domain] > 0));
      if (!relevant.length || relevant.some(a => !validAssessments.has(a.id))) { hold(policyId, '立場別の影響根拠が不足しています'); continue; }
      const impact = relevant.reduce((sum, a) => sum + a.impact * (o.domain === 'overall' ? o.weights[a.domain] / weightTotal : 1), 0);
      contributions.push({ policyId, actionKey: action.actionId, actionDate: action.actionDate, role: action.role, score: impact * ROLE_FACTOR[action.role] }); assessedActions++;
    }
    contributions.sort((a, b) => a.policyId.localeCompare(b.policyId));
    return { person, score: sumRounded(contributions.map(c => c.score)), rank: null, eligibleCount: contributions.length, heldCount, contributions };
  });
  return { mode: input.mode, rows: assignRanks(rows), held, coverage: { inputActions: actions.size, assessedActions, readableMaterials: texts.size }, publicationStatus: 'requires_human_review' };
}
