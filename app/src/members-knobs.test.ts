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
      // 反対票の分（direction: against）は法律の額の配分（合計1）とは別に数える（設計決定0014）。成立させた側の分と役職の帳簿の合計が額を超えないこと。
      const total = members.flatMap(m => m.laws).filter(l => l.lawId === law.id && l.direction !== 'against').reduce((s, l) => s + l.share.median + (l.office?.median ?? 0), 0);
      expect(total).toBeLessThanOrEqual(law.amount.median);
    }
  }
});

it('提出者の重みを0にすると、提出だけの人は0円になる', () => {
  const members = adjustMembers(data, { ...DEFAULT_KNOBS, proposer: 0 });
  const proposerOnly = data.members.find(m => m.laws.every(l => Object.keys(l.roles).join() === 'proposer'));
  expect(members.find(m => m.id === proposerOnly.id).net.median).toBe(0);
});

it('つまみを変えても、反対票の割合は賛成1票の割合と同じ', () => {
  const members = adjustMembers(data, { ...DEFAULT_KNOBS, party: 'voters', rate: 0.5 });
  const law = data.laws.find(l => l.game.opposers > 0 && l.game.voters > 0);
  const rows = members.flatMap(m => m.laws.filter(l => l.lawId === law.id));
  const against = rows.find(l => l.direction === 'against');
  const voter = rows.find(l => l.direction === 'with' && Object.keys(l.roles).join() === 'vote');
  expect(against.fraction).toBeCloseTo(voter.roles.vote, 12);
});
