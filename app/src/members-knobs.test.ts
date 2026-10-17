// Node の型定義を入れずに、配布データを読むため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { DEFAULT_KNOBS } from './causal-allocation';
import { adjustMembers } from './members-knobs';

const data = JSON.parse(readFileSync(join(process.cwd(), 'public/distribution/members.json'), 'utf8'));

it('初期値では配布データをそのまま使う', () => {
  expect(adjustMembers(data, DEFAULT_KNOBS)).toBe(data.members);
});

it('どのつまみでも、法律ごとの配分の合計は額を超えない', () => {
  for (const knobs of [{ proposer: 0, party: 'voters', chairVeto: true, rate: 1 }, { proposer: 0.5, party: 'party', chairVeto: false, rate: 0.3 }]) {
    const members = adjustMembers(data, knobs);
    expect(members.map(m => m.rank)).toEqual(members.map((_, i) => i + 1));
    for (const law of data.laws) {
      const total = members.flatMap(m => m.laws).filter(l => l.lawId === law.id).reduce((s, l) => s + l.share.median, 0);
      expect(total).toBeLessThanOrEqual(law.amount.median);
    }
  }
});

it('提出者の重みを0にすると、提出だけの人は0円になる', () => {
  const members = adjustMembers(data, { ...DEFAULT_KNOBS, proposer: 0 });
  const proposerOnly = data.members.find(m => m.laws.every(l => Object.keys(l.roles).join() === 'proposer'));
  expect(members.find(m => m.name === proposerOnly.name).net.median).toBe(0);
});
