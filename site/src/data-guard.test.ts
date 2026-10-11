import { describe, expect, it } from 'vitest';
import { FICTIONAL, involvements, people, policies } from './data/fiction';

describe('架空データの境界', () => {
  it('ランキングの人物と政策はすべて架空と明示されている', () => {
    expect(FICTIONAL).toBe(true);
    for (const p of people) expect(p.name.startsWith('架空')).toBe(true);
    for (const p of people) expect(p.district.startsWith('架空')).toBe(true);
    for (const p of policies) expect(p.title.startsWith('架空')).toBe(true);
  });

  it('関与は登録済みの人物と政策だけを指す', () => {
    const pid = new Set(people.map((p) => p.id));
    const qid = new Set(policies.map((p) => p.id));
    for (const i of involvements) {
      expect(pid.has(i.personId)).toBe(true);
      expect(qid.has(i.policyId)).toBe(true);
    }
  });
});
