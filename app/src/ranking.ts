/** 表示用派生データ。実人物データは検証・公開審査済みの別経路からのみ接続する。 */
export const RANKING_VERSION = 'fictional-actions-v1';
export const DOMAINS = ['economy', 'technology', 'fiscal', 'security', 'governance'] as const;
export type Domain = typeof DOMAINS[number];
export type RankedDomain = 'economy' | 'technology' | 'overall';
export type Direction = 'benefit' | 'harm';
export type Period = 2 | 4 | 8 | 30 | 40 | 'custom' | 'cumulative';
export type RankingEvidence = { id: string; title: string; date: string; kind: 'verified' | 'computed' | 'ai' | 'unknown'; source: string; summary: string; url?: string; locator?: string; sha256?: string };
export type Person = { id: string; name: string; house?: string; district?: string; electionIds?: string[]; roleClass?: string; actorType?: 'person' | 'organization' };
export type Policy = { id: string; title: string; domain: Domain; direction: Direction; impact: 1 | 2 | 3; reviewStatus: 'reviewed' | 'pending'; rationale: string; counterEvidence: string; alternativeExplanation: string; evidenceIds: string[] };
export type Involvement = { id?: string; personId: string; policyId: string; actionDate: string; role: 'lead' | 'coauthor' | 'vote' | 'context'; description: string; evidenceIds: string[] };
export type RankingDataset = { schemaVersion: 'ranking-dataset/v1'; fictional: boolean; asOf: string; coverage: { scope: string; assessedPeople: number; targetPeople: number | null; sourceStatus: string }; people: Person[]; policies: Policy[]; involvements: Involvement[]; evidence: RankingEvidence[]; held?: { personId?: string; policyId?: string; reason: string; sourceRefs?: string[] }[] };
export type RankingOptions = { domain: Domain | 'overall'; direction: Direction; period: Period; asOf: string; weights: { economy: number; technology: number }; dateFrom?: string; dateTo?: string; timeBasis?: 'action' | 'outcome'; actorGroup?: 'people' | 'organizations' };
export type RankingContribution = { policyId: string; actionKey: string; actionDate: string; role: Involvement['role']; score: number; outcomeId?: string };
export type RankingRow = { person: Person; score: number | null; rank: number | null; eligibleCount: number; heldCount: number; contributions: RankingContribution[] };

export const ROLE_FACTOR: Record<Involvement['role'], number> = { lead: 1, coauthor: .5, vote: .25, context: 0 };
/** 一つの政策に複数の異なる行動がある場合も選択先を区別する。 */
export const actionKey = (action: Involvement): string => JSON.stringify([action.personId, action.policyId, action.actionDate, action.role, action.description, [...action.evidenceIds].sort()]);
const check = (valid: boolean, message: string) => { if (!valid) throw new Error(message); };
const idCompare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
/** 入力検証は呼出し側の契約で行い、集計だけを共通化する。 */
export const sumRounded = (values: number[]): number | null => values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) * 100) / 100 : null;
export function assignRanks(rows: RankingRow[]): RankingRow[] {
  rows.sort((a, b) => (a.score === null ? b.score === null ? 0 : 1 : b.score === null ? -1 : b.score - a.score) || idCompare(a.person.id, b.person.id));
  rows.forEach((row, index) => { row.rank = row.score === null ? null : index > 0 && row.score === rows[index - 1].score ? rows[index - 1].rank : index + 1; });
  return rows;
}
const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const finiteWeight = (value: number) => Number.isFinite(value) && value >= 0 && value <= 100;

function periodStart(asOf: string, period: Period, dateFrom?: string): string | null {
  if (period === 'cumulative') return null;
  if (period === 'custom') return dateFrom ?? null;
  const date = new Date(`${asOf}T00:00:00Z`);
  date.setUTCFullYear(date.getUTCFullYear() - period);
  return date.toISOString().slice(0, 10);
}

/** 表示条件への一致だけを判定する。保留・参考行動も含み、算定資格は判定しない。 */
export function actionMatchesView(action: Involvement, policy: Policy, options: RankingOptions): boolean {
  const start = periodStart(options.asOf, options.period, options.dateFrom);
  return action.actionDate <= (options.period === 'custom' ? options.dateTo ?? options.asOf : options.asOf) && (!start || action.actionDate >= start)
    && policy.direction === options.direction && (options.domain === 'overall' || policy.domain === options.domain);
}

/** 全資料が創作である表示fixtureだけを計算する。実人物への適用は別の検証済み入口が必要。 */
export function rankPeople(data: RankingDataset, options: RankingOptions): RankingRow[] {
  check(data.schemaVersion === 'ranking-dataset/v1' && data.fictional === true, '架空表示用データのみ算定できます');
  check(validDate(options.asOf) && [2, 4, 8, 30, 40, 'custom', 'cumulative'].includes(options.period), '比較期間が不正です');
  if (options.period === 'custom') check(validDate(options.dateFrom ?? '') && validDate(options.dateTo ?? '') && options.dateFrom! <= options.dateTo! && options.dateTo! <= options.asOf, '任意期間が不正です');
  check(DOMAINS.includes(options.domain as Domain) || options.domain === 'overall', '評価分野が不正です');
  check(['benefit', 'harm'].includes(options.direction), '影響方向が不正です');
  check(finiteWeight(options.weights.economy) && finiteWeight(options.weights.technology), '重みが不正です');
  function unique<T extends { id: string }>(items: T[]): Map<string, T> {
    const result = new Map<string, T>();
    for (const item of items) {
      check(typeof item.id === 'string' && item.id.trim().length > 0 && !result.has(item.id), 'IDが空または重複しています');
      result.set(item.id, item);
    }
    return result;
  }
  const people = unique(data.people);
  const policies = unique(data.policies);
  const evidence = unique(data.evidence);
  for (const item of evidence.values()) {
    check(validDate(item.date) && Boolean(item.title?.trim() && item.source?.trim() && item.summary?.trim()), '証拠が不正です');
    check(['verified', 'computed', 'ai', 'unknown'].includes(item.kind), '証拠分類が不正です');
  }
  const hasVerifiedEvidence = (ids: string[]): boolean => ids.length > 0 && ids.every(id => evidence.get(id)?.kind === 'verified');
  const validateEvidence = (ids: string[]) => {
    check(Array.isArray(ids) && new Set(ids).size === ids.length && ids.every(id => evidence.has(id)), '証拠参照が不正です');
  };
  for (const policy of policies.values()) {
    check(DOMAINS.includes(policy.domain) && ['benefit', 'harm'].includes(policy.direction), '政策の分類が不正です');
    check([1, 2, 3].includes(policy.impact) && ['reviewed', 'pending'].includes(policy.reviewStatus), '政策の評価が不正です');
    check(Boolean(policy.title?.trim() && policy.rationale?.trim() && policy.counterEvidence?.trim() && policy.alternativeExplanation?.trim()), '政策説明が不足しています');
    validateEvidence(policy.evidenceIds);
  }
  for (const action of data.involvements) {
    check(people.has(action.personId) && policies.has(action.policyId), '人物・政策の参照先がありません');
    check(validDate(action.actionDate) && Boolean(action.description?.trim()) && Object.hasOwn(ROLE_FACTOR, action.role), '行動が不正です');
    validateEvidence(action.evidenceIds);
  }
  const domainEnabled = options.domain === 'economy' || options.domain === 'technology' || options.domain === 'overall';
  const weightTotal = options.weights.economy + options.weights.technology;
  const rows: RankingRow[] = data.people.map(person => {
    const grouped = new Map<string, Involvement[]>();
    for (const action of data.involvements) {
      const policy = policies.get(action.policyId)!;
      if (action.personId !== person.id || !actionMatchesView(action, policy, options)) continue;
      const group = grouped.get(policy.id) ?? [];
      group.push(action);
      grouped.set(policy.id, group);
    }
    const contributions: RankingContribution[] = [];
    let heldCount = 0;
    for (const [policyId, actions] of grouped) {
      const policy = policies.get(policyId)!;
      const relevantWeight = policy.domain === 'economy' ? options.weights.economy : policy.domain === 'technology' ? options.weights.technology : 0;
      const canScore = domainEnabled && (options.domain !== 'overall' || weightTotal > 0) && (options.domain !== 'overall' || relevantWeight > 0) && policy.reviewStatus === 'reviewed' && hasVerifiedEvidence(policy.evidenceIds);
      const eligible = canScore ? actions.filter(action => ROLE_FACTOR[action.role] > 0 && hasVerifiedEvidence(action.evidenceIds)) : [];
      if (!eligible.length) { heldCount++; continue; }
      eligible.sort((a, b) => ROLE_FACTOR[b.role] - ROLE_FACTOR[a.role] || idCompare(a.actionDate, b.actionDate) || idCompare(actionKey(a), actionKey(b)));
      const action = eligible[0];
      const weight = options.domain === 'overall' ? relevantWeight / weightTotal : 1;
      contributions.push({ policyId, actionKey: actionKey(action), actionDate: action.actionDate, role: action.role, score: policy.impact * ROLE_FACTOR[action.role] * weight });
    }
    contributions.sort((a, b) => idCompare(a.policyId, b.policyId));
    return { person, score: sumRounded(contributions.map(item => item.score)), rank: null, eligibleCount: contributions.length, heldCount, contributions };
  });
  return assignRanks(rows);
}
