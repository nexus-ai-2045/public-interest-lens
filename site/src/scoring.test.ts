import { describe, expect, it } from 'vitest';
import { involvements, people, policies } from './data/fiction';
import { rank } from './scoring';

describe('rank', () => {
  it('同じ政策への関与は最も強い1件だけを数える', () => {
    const r = rank(
      [people[0]],
      [{ id: 'x', title: '架空', domain: 'economy', direction: 'harm', impact: 3, theme: 't' }],
      [
        { personId: people[0].id, policyId: 'x', role: 'vote', date: '2024-01-01', note: '' },
        { personId: people[0].id, policyId: 'x', role: 'lead', date: '2024-02-01', note: '' },
      ],
      'harm',
      'all',
    );
    expect(r[0].contributions).toHaveLength(1);
    expect(r[0].contributions[0].role).toBe('lead');
  });

  it('文脈のみの関与は採点しない', () => {
    const ranked = rank(people, policies, involvements, 'harm', 'all');
    expect(ranked.find((r) => r.person.id === 'p03')).toBeUndefined();
  });

  it('首位は100点で、点数の降順に並ぶ', () => {
    for (const d of ['harm', 'benefit'] as const) {
      const ranked = rank(people, policies, involvements, d, 'all');
      expect(ranked[0].score).toBe(100);
      for (let i = 1; i < ranked.length; i++) expect(ranked[i - 1].score).toBeGreaterThanOrEqual(ranked[i].score);
    }
  });

  it('分野で絞ると、その分野の政策だけが寄与する', () => {
    const ranked = rank(people, policies, involvements, 'harm', 'technology');
    for (const r of ranked) for (const c of r.contributions) expect(c.policy.domain).toBe('technology');
  });
});
