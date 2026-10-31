// Node の型定義を入れずに、配布データを読むため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { DEFAULT_KNOBS } from './causal-allocation';
import { adjustMembers } from './members-knobs';
import { buildMembers } from './members-build';

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

// 配布データは検証を通った配分の法律が無いと議員0人になる。つまみの計算は、合成した小さな入力で確かめる。
const header = '法律ID,題名,氏名,氏名_原表記,院,行動,当時の肩書,立場区分,立場の根拠,日付,証拠URL,系統A,系統B,参院本会議の賛否,算入,除外理由';
const row = (name: string, action: string) => `衆法-1-1,題,${name},${name},参議院,${action},,other,,2018-01-01,https://kokkai.ndl.go.jp/txt/1/1,,,,はい,`;
const fixture = () => buildMembers({
  involvements: [header, row('甲', 'decide'), row('乙', 'vote'), row('戊', 'vote')].join('\n'),
  publish: ['id,題名,側,損失または便益,便益の状態,判定表の行,公開可否,理由', '衆法-1-1,損の法律,国賊側（悪影響）,中央値=1000;第1四分位=800;第3四分位=1200,,R4,公開可,'].join('\n'),
  loss: ['id,損失または便益の額,参考フラグ,観測グループ', '衆法-1-1,1000,,G1'].join('\n'),
  enacted: ['種別,提出回次,番号,経過URL', '衆法,1,1,https://www.shugiin.go.jp/x/1.htm'].join('\n'),
  votes: ['法律ID,投票ID,日付,賛成,反対,URL', '衆法-1-1,1,2018-01-01,3,1,https://www.sangiin.go.jp/v/1.htm'].join('\n'),
  opposing: ['法律ID,投票ID,氏名,人物ID,証拠URL,算入,除外理由', '衆法-1-1,1,丁,丁,https://www.sangiin.go.jp/v/1.htm,はい,'].join('\n'),
});

it('提出者の重みを0にすると、提出だけの人は0円になる', () => {
  const small = fixture();
  const members = adjustMembers(small, { ...DEFAULT_KNOBS, proposer: 0 });
  const proposerOnly = small.members.find(m => m.laws.every(l => Object.keys(l.roles).join() === 'proposer'));
  expect(proposerOnly).toBeDefined();
  expect(members.find(m => m.id === proposerOnly!.id).net.median).toBe(0);
});

it('つまみを変えても、反対票の割合は賛成1票の割合と同じ', () => {
  const small = fixture();
  const members = adjustMembers(small, { ...DEFAULT_KNOBS, party: 'voters', rate: 0.5 });
  const law = small.laws.find(l => l.game.opposers > 0 && l.game.voters > 0);
  expect(law).toBeDefined();
  const rows = members.flatMap(m => m.laws.filter(l => l.lawId === law!.id));
  const against = rows.find(l => l.direction === 'against');
  const voter = rows.find(l => l.direction === 'with' && Object.keys(l.roles).join() === 'vote');
  expect(against.fraction).toBeCloseTo(voter.roles.vote, 12);
});
