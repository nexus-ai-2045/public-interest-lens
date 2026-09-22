export const RANKING_VERSION = 'fictional-policy-attribution-v1';
export const DOMAINS = ['productivity', 'income', 'fiscal'] as const;
export type Domain = typeof DOMAINS[number];
export type RankingEvidence = { id: string; title: string; date: string; kind: 'verified' | 'computed' | 'ai' | 'unknown'; source: string; summary: string };
export type Person = { id: string; name: string };
export type Policy = { id: string; title: string; year: number; domain: Domain; harm: number; causalConfidence: number; reviewStatus: 'reviewed' | 'pending'; rationale: string; counterEvidence: string; alternativeExplanation: string; evidenceIds: string[] };
export type Involvement = { personId: string; policyId: string; role: string; attribution: number; evidenceIds: string[] };
export type RankingDataset = { fictional: true; people: Person[]; policies: Policy[]; involvements: Involvement[]; evidence: RankingEvidence[] };
export type RankingOptions = { fromYear: number; toYear: number; weights: Record<Domain, number> };
export type RankingRow = { person: Person; score: number | null; rank: number | null; eligibleCount: number; omittedCount: number; coverage: number; contributions: { policyId: string; score: number }[] };

const check = (valid: boolean, message: string) => { if (!valid) throw new Error(message); };
const numberIn = (value: number, min: number, max: number) => Number.isFinite(value) && value >= min && value <= max;
const yearValid = (value: number) => Number.isInteger(value) && numberIn(value, 1868, 2100);
const compareId = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
const round = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;

/** 確認済み資料で裏付けた、人間レビュー済みの架空政策だけを算定する。 */
export function rankPeople(data: RankingDataset, options: RankingOptions): RankingRow[] {
  check(data.fictional === true, 'この版は架空データ専用です');
  check(yearValid(options.fromYear) && yearValid(options.toYear) && options.fromYear <= options.toYear, '対象期間が不正です');
  DOMAINS.forEach(domain => check(numberIn(options.weights[domain], 0, 100), '重みは0〜100の有限数です'));
  function unique<T extends { id: string }>(items: T[]) {
    const map = new Map<string, T>();
    items.forEach(item => { check(typeof item.id === 'string' && item.id.trim().length > 0 && !map.has(item.id), 'IDが空または重複しています'); map.set(item.id, item); });
    return map;
  }
  const people = unique(data.people), policies = unique(data.policies), evidence = unique(data.evidence);
  evidence.forEach(e => {
    check(/^\d{4}-\d{2}-\d{2}$/.test(e.date) && Number.isFinite(Date.parse(e.date)) && new Date(e.date).toISOString().slice(0, 10) === e.date && yearValid(Number(e.date.slice(0, 4))), '証拠の日付が不正です');
    check(['verified', 'computed', 'ai', 'unknown'].includes(e.kind), '証拠分類が不正です');
    check(Boolean(e.title.trim() && e.source.trim() && e.summary.trim()), '証拠の説明が不足しています');
  });
  const validateRefs = (ids: string[]) => {
    check(new Set(ids).size === ids.length, '証拠参照が重複しています');
    ids.forEach(id => check(evidence.has(id), '証拠参照先がありません'));
  };
  policies.forEach(policy => {
    check(yearValid(policy.year) && DOMAINS.includes(policy.domain), '政策の年・分野が不正です');
    check(numberIn(policy.harm, 0, 100) && numberIn(policy.causalConfidence, 0, 1), '政策係数が不正です');
    check(['reviewed', 'pending'].includes(policy.reviewStatus), 'レビュー状態が不正です');
    check(Boolean(policy.title.trim() && policy.rationale.trim() && policy.counterEvidence.trim() && policy.alternativeExplanation.trim()), '政策の検証説明が不足しています');
    validateRefs(policy.evidenceIds);
  });
  const seen = new Set<string>();
  data.involvements.forEach(involvement => {
    check(people.has(involvement.personId) && policies.has(involvement.policyId), '人物・政策の参照先がありません');
    const key = JSON.stringify([involvement.personId, involvement.policyId]);
    check(!seen.has(key), '同一人物・政策の重複集計は禁止です'); seen.add(key);
    check(numberIn(involvement.attribution, 0, 1) && Boolean(involvement.role.trim()), '関与情報が不正です');
    validateRefs(involvement.evidenceIds);
  });
  const totalWeight = DOMAINS.reduce((sum, domain) => sum + options.weights[domain], 0);
  const verified = (ids: string[]) => ids.length > 0 && ids.every(id => evidence.get(id)!.kind === 'verified');
  const rows: RankingRow[] = data.people.map(person => {
    const selected = data.involvements.filter(i => {
      const p = policies.get(i.policyId)!;
      return i.personId === person.id && p.year >= options.fromYear && p.year <= options.toYear;
    }).sort((a, b) => compareId(a.policyId, b.policyId));
    const eligible = selected.filter(i => {
      const p = policies.get(i.policyId)!;
      return p.reviewStatus === 'reviewed' && verified(p.evidenceIds) && verified(i.evidenceIds);
    });
    const contributions = eligible.map(i => {
      const p = policies.get(i.policyId)!;
      return { policyId: p.id, score: totalWeight === 0 ? 0 : p.harm * p.causalConfidence * i.attribution * options.weights[p.domain] / totalWeight };
    });
    return { person, score: eligible.length && totalWeight > 0 ? round(contributions.reduce((sum, c) => sum + c.score, 0)) : null, rank: null, eligibleCount: eligible.length, omittedCount: selected.length - eligible.length, coverage: selected.length ? eligible.length / selected.length : 0, contributions };
  });
  rows.sort((a, b) => (a.score === null ? b.score === null ? 0 : 1 : b.score === null ? -1 : b.score - a.score) || compareId(a.person.id, b.person.id));
  rows.forEach((row, index) => { if (row.score !== null) row.rank = index > 0 && row.score === rows[index - 1].score ? rows[index - 1].rank : index + 1; });
  return rows;
}
