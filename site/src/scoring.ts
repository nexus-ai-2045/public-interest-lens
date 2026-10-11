import type { Direction, Domain, FictionInvolvement, FictionPerson, FictionPolicy, Role } from './data/fiction';

/** 行動の関与係数。団体所属などの文脈情報は採点しません。 */
export const ROLE_FACTOR: Record<Role, number> = { lead: 1, vote: 0.5, context: 0 };
export const ROLE_LABEL: Record<Role, string> = { lead: '主導', vote: '個人採決', context: '文脈のみ' };

export type DomainFilter = Domain | 'all';

export interface Contribution {
  policy: FictionPolicy;
  role: Role;
  date: string;
  note: string;
  points: number;
}

export interface RankedPerson {
  person: FictionPerson;
  score: number;
  rank: number;
  contributions: Contribution[];
}

/**
 * 方向と分野で絞り、政策ごとに最も強い関与だけを数えます（同じ政策の重複加算なし）。
 * 点数 = 影響段階 × 関与係数 の合計を 0〜100 に正規化します。
 */
export function rank(
  people: FictionPerson[],
  policies: FictionPolicy[],
  involvements: FictionInvolvement[],
  direction: Direction,
  domain: DomainFilter,
): RankedPerson[] {
  const policyById = new Map(policies.map((p) => [p.id, p]));
  const raw = people.map((person) => {
    const best = new Map<string, Contribution>();
    for (const inv of involvements) {
      if (inv.personId !== person.id) continue;
      const policy = policyById.get(inv.policyId);
      if (!policy || policy.direction !== direction) continue;
      if (domain !== 'all' && policy.domain !== domain) continue;
      const points = policy.impact * ROLE_FACTOR[inv.role];
      const prev = best.get(policy.id);
      if (!prev || points > prev.points) best.set(policy.id, { policy, role: inv.role, date: inv.date, note: inv.note, points });
    }
    const contributions = [...best.values()].sort((a, b) => b.points - a.points);
    return { person, total: contributions.reduce((s, c) => s + c.points, 0), contributions };
  });
  const scored = raw.filter((r) => r.total > 0);
  const max = Math.max(1, ...scored.map((r) => r.total));
  scored.sort((a, b) => b.total - a.total || a.person.id.localeCompare(b.person.id));
  let lastScore = -1;
  let lastRank = 0;
  return scored.map((r, i) => {
    const score = Math.round((r.total / max) * 100);
    const rankNo = score === lastScore ? lastRank : i + 1;
    lastScore = score;
    lastRank = rankNo;
    return { person: r.person, score, rank: rankNo, contributions: r.contributions };
  });
}
