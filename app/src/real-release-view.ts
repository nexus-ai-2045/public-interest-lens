import { actionRevision, evaluateEvidence, type EvidenceAction, type EvidenceEvaluationInput, type EvidenceEvaluationResult } from './evidence-evaluation';
import { sumRounded } from './ranking';

export const REAL_RELEASE_MAX_BYTES = 5_000_000;
export function realActionHeading(action: Pick<EvidenceAction, 'namespace' | 'policyId' | 'actionDate' | 'position' | 'description'>): string {
  if (action.namespace !== 'sangiin-plenary-vote/v1') return `${action.actionDate}・${action.description}`;
  const bill = /^(\d+)-(\d+)$/.exec(action.policyId);
  const label = bill ? `第${bill[1]}回国会・閣法第${Number(bill[2])}号` : '議案番号未確認';
  const position = { for: '賛成', against: '反対', not_voted: '投票なし', unknown: '賛否不明' }[action.position];
  return `${label}｜${action.actionDate}・参議院本会議で${position}`;
}
export type RealRelease = { schemaVersion: 'evidence-release/v1'; engineHash: string; releaseId: string; input: { evidenceEvaluation: EvidenceEvaluationInput; materialRefs: { id: string; originalHash: string; selector: Record<string, unknown> }[] }; result: EvidenceEvaluationResult; publicationStatus: 'requires_human_review'; verification?: unknown };
export type RealRoute = { dataset: 'real' | 'fiction'; release: string; person: string };
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const requireValid = (v: unknown, message: string): void => { if (!v) throw new Error(message); };
const keys = (v: unknown, allowed: string[]) => requireValid(object(v) && Object.keys(v).every(k => allowed.includes(k)), '評価版の項目が不正です。');
const count = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const score = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;

/** SHAは保存版の整合性だけを検査します。独立検証や公開承認を生成しません。 */
export async function parseRealRelease(text: string): Promise<RealRelease> {
  requireValid(new TextEncoder().encode(text).byteLength <= REAL_RELEASE_MAX_BYTES, 'ファイルは5MB以下にしてください。');
  const raw: unknown = JSON.parse(text);
  keys(raw, ['schemaVersion', 'engineHash', 'releaseId', 'input', 'result', 'publicationStatus', 'verification']);
  const release = raw as RealRelease;
  keys(release.input, ['evidenceEvaluation', 'materialRefs']);
  const input = release.input.evidenceEvaluation;
  requireValid(release.schemaVersion === 'evidence-release/v1' && hash(release.releaseId) && hash(release.engineHash)
    && release.publicationStatus === 'requires_human_review' && object(input) && input.mode === 'real' && Array.isArray(release.input.materialRefs), '非公開実評価の保存版ではありません。');
  const { releaseId, ...body } = release;
  requireValid(await actionRevision(body) === releaseId, '評価版のハッシュが一致しません。');
  // 既存入口の構造・参照・改訂検査を再利用します。空の信頼集合で検証状態を昇格させません。
  await evaluateEvidence(input, { readMaterial: async () => null, resolvedPersonIds: new Set(), verifiedActionIds: new Set(), verifiedAssessmentIds: new Set(), verifiedActionRevisions: new Map(), verifiedAssessmentRevisions: new Map() });
  const refIds = new Set<string>();
  for (const ref of release.input.materialRefs) {
    keys(ref, ['id', 'originalHash', 'selector']);
    const material = input.materials.find(m => m.id === ref.id);
    requireValid(typeof ref.id === 'string' && ref.id.trim() && hash(ref.originalHash) && object(ref.selector) && !refIds.has(ref.id) && material?.originalHash === ref.originalHash, '保存原本の参照が不正です。');
    refIds.add(ref.id);
  }
  requireValid(refIds.size === input.materials.length, '保存原本の参照が欠落しています。');
  const r = release.result;
  keys(r, ['mode', 'rows', 'held', 'coverage', 'publicationStatus']);
  requireValid(r.mode === 'real' && r.publicationStatus === 'requires_human_review' && Array.isArray(r.rows) && Array.isArray(r.held), '保存された計算結果が不正です。');
  keys(r.coverage, ['inputActions', 'assessedActions', 'readableMaterials']);
  const people = new Map(input.people.map(p => [p.id, p]));
  const selectedPeople = new Set(input.people.filter(person => input.options.actorGroup === 'organizations' ? person.actorType === 'organization' : person.actorType !== 'organization').map(person => person.id));
  const actions = new Map(input.actions.map(a => [a.actionId, a]));
  const seen = new Set<string>();
  for (const row of r.rows) {
    keys(row, ['person', 'score', 'rank', 'eligibleCount', 'heldCount', 'contributions']);
    requireValid(object(row.person) && selectedPeople.has(row.person.id) && !seen.has(row.person.id), '人物の参照が不正です。');
    requireValid(await actionRevision(row.person) === await actionRevision(people.get(row.person.id)), '人物の内容が一致しません。');
    seen.add(row.person.id);
    requireValid((row.score === null || score(row.score)) && (row.rank === null || (count(row.rank) && row.rank > 0))
      && (row.score === null) === (row.rank === null) && count(row.eligibleCount) && count(row.heldCount) && Array.isArray(row.contributions), '点数・順位が不正です。');
    const policies = new Set<string>();
    for (const c of row.contributions) {
      keys(c, ['policyId', 'actionKey', 'actionDate', 'role', 'score', 'outcomeId']);
      const a = actions.get(c.actionKey);
      const resultKey = input.options.timeBasis === 'outcome' ? c.outcomeId : c.policyId;
      requireValid(typeof resultKey === 'string' && Boolean(resultKey) && a && (input.options.timeBasis !== 'outcome' || a.outcomeId === c.outcomeId) && a.personId === row.person.id && a.policyId === c.policyId && a.actionDate === c.actionDate && a.role === c.role && score(c.score) && !policies.has(resultKey), '計算内訳の行動参照が不正です。');
      policies.add(resultKey!);
    }
    requireValid(row.eligibleCount === row.contributions.length && row.score === sumRounded(row.contributions.map(c => c.score)), '保存点数と内訳が一致しません。');
  }
  requireValid(seen.size === selectedPeople.size, '人物の計算結果が欠落しています。');
  for (const h of r.held) {
    keys(h, ['personId', 'policyId', 'actionId', 'reason']);
    requireValid(typeof h.reason === 'string' && h.reason.trim() && (!h.personId || people.has(h.personId)) && (!h.actionId || actions.has(h.actionId))
      && (!h.policyId || input.actions.some(a => a.policyId === h.policyId)), '保留の参照が不正です。');
  }
  requireValid(count(r.coverage.inputActions) && r.coverage.inputActions === actions.size && count(r.coverage.assessedActions)
    && r.coverage.assessedActions === r.rows.reduce((n, row) => n + row.contributions.length, 0)
    && count(r.coverage.readableMaterials) && r.coverage.readableMaterials <= input.materials.length, '取得範囲が不正です。');
  return release;
}

export function readRealRoute(search: string, pathname = ''): RealRoute {
  const url = new URL(search.startsWith('/') ? search : `${pathname || '/'}${search}`, 'https://local.invalid');
  const p = url.searchParams;
  return { dataset: ['/evaluation', '/policies', '/actors'].includes(url.pathname) || p.get('dataset') === 'real' ? 'real' : 'fiction', release: p.get('release') ?? '', person: p.get('realPerson') ?? '' };
}
export function realRouteLocation(route: RealRoute): string {
  if (route.dataset !== 'real') return '/ranking';
  const p = new URLSearchParams();
  if (route.release) p.set('release', route.release);
  if (route.person) p.set('realPerson', route.person);
  return `/evaluation${p.size ? `?${p}` : ''}`;
}
export function realRouteSearch(route: RealRoute): string {
  const p = new URLSearchParams({ dataset: route.dataset });
  if (route.dataset === 'real') { if (route.release) p.set('release', route.release); if (route.person) p.set('realPerson', route.person); }
  return `?${p}`;
}
export const availableRealRelease = (route: RealRoute, release: RealRelease | null): RealRelease | null => route.dataset === 'real' && release && route.release === release.releaseId ? release : null;

/** 保存された照合記録の件数です。ブラウザで再検証した件数ではありません。 */
export function recordedIdentityCoverage(release: RealRelease): { matched: number; unresolved: number } | null {
  const verification = release.verification;
  if (!object(verification) || !Array.isArray(verification.resolvedPersonIds)) return null;
  const input = release.input.evidenceEvaluation;
  const people = new Set(input.people.map(p => p.id));
  const ids = verification.resolvedPersonIds;
  if (ids.some(id => typeof id !== 'string' || !people.has(id)) || new Set(ids).size !== ids.length) return null;
  const selected = new Set(input.people.filter(p => input.options.actorGroup === 'organizations' ? p.actorType === 'organization' : p.actorType !== 'organization').map(p => p.id));
  const matched = ids.filter(id => selected.has(id)).length;
  return { matched, unresolved: selected.size - matched };
}

/** 非同期読込の最後の選択だけを採用し、不正入力では前正常版を保ちます。 */
export function createReleaseLoader(onValid: (release: RealRelease) => void, onError: (message: string) => void) {
  let request = 0;
  return { cancel: () => { request++; }, load: async (file: { size: number; text: () => Promise<string> }, expectedRelease = '') => {
    const id = ++request;
    try { requireValid(file.size <= REAL_RELEASE_MAX_BYTES, 'ファイルは5MB以下にしてください。'); const release = await parseRealRelease(await file.text()); requireValid(!expectedRelease || release.releaseId === expectedRelease, '指定版と一致しません。'); if (id === request) onValid(release); }
    catch { if (id === request) onError('実評価版を読み取れませんでした。形式・ハッシュ・参照を確認してください。直前の正常版は保持しています。'); }
  } };
}
