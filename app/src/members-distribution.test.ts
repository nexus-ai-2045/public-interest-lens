// Node の型定義を入れずに、リポジトリ内のファイルだけを読むため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { buildMembers } from './members-build';

const root = join(process.cwd(), '..');
const read = (path: string) => readFileSync(join(root, path), 'utf8');

it('配布している members.json は、いまの派生データから同じ計算で作り直したものと一致する', () => {
  const built = buildMembers({
    involvements: read('data/derived/allocation-v1/involvements.csv'),
    publish: read('data/derived/publish-v1-triage-v2/publish.csv'),
    loss: read('data/derived/loss-v1-triage-v2/loss.csv'),
    enacted: read('data/acquired/bill-census-full/enacted.csv'),
    votes: read('data/derived/allocation-v1/votes.csv'),
    opposing: read('data/derived/allocation-v1/opposing.csv'),
    autoInvolvements: read('data/derived/allocation-v1/involvements-auto.csv'),
    autoVotes: read('data/derived/allocation-v1/votes-auto.csv'),
    voteParties: read('data/derived/allocation-v1/vote-parties.csv'),
    ministries: read('data/derived/ministry-v1/cabinet-bills.csv'),
    taxLedger: read('data/derived/tax-v1/consumption-tax.csv'),
    taxLedgerIncome: read('data/derived/tax-v1/income-corporate-tax.csv'),
    resistance: read('data/derived/org-ledger-v1/ministry-resistance.csv'),
    orgStances: read('data/derived/org-ledger-v1/org-stances.csv'),
    listed: JSON.parse(read('app/public/distribution/ranking.json')).laws.map((l: { id: string }) => l.id),
    certainty: Object.fromEntries(JSON.parse(read('app/public/distribution/ranking.json')).laws.map((l: { id: string; certainty: string }) => [l.id, l.certainty])),
  });
  // pending（配分にまだ入っていない法律の一覧）は公開ランキングから付けるので、計算の一致からは外し、下で別に確かめる。
  const { inputs, pending, ...published } = JSON.parse(read('app/public/distribution/members.json'));
  expect(Object.keys(inputs).sort()).toEqual(['autoInvolvements', 'autoVotes', 'enacted', 'involvements', 'loss', 'ministries', 'opposing', 'orgStances', 'publish', 'resistance', 'taxLedger', 'taxLedgerIncome', 'voteParties', 'votes']);
  expect(published).toEqual(JSON.parse(JSON.stringify(built)));
  const ranking = JSON.parse(read('app/public/distribution/ranking.json'));
  const included = new Set(published.laws.map(l => l.id));
  expect(pending.map(l => l.id)).toEqual(ranking.laws.filter(l => ['高', '中'].includes(l.certainty) && !included.has(l.id)).map(l => l.id));
  for (const member of published.members) for (const law of member.laws) {
    // 額が付く人は、配分に入った行動の一次資料が必ずある。0円の人は配らない行動の記録がある。
    expect(law.fraction > 0 ? law.evidence.length : law.context.length).toBeGreaterThan(0);
    for (const ev of [...law.evidence, ...law.context]) expect(ev.url).toMatch(/^https:\/\/(kokkai\.ndl\.go\.jp|www\.sangiin\.go\.jp|www\.shugiin\.go\.jp)\//);
  }
  // 政党ランキングは議員の額を会派で集めただけ：会派の分と会派が分からなかった分を足すと、全議員の行動の額の合計になる。
  const r = published.partyRanking;
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  const memberNet = sum(published.members.map(m => m.net.median));
  expect(sum(r.blocs.map(b => b.net.median)) + r.unmatched.net.median).toBe(memberNet);
  // 省庁の帳簿は役職の帳簿を置き直しただけ：所管が決まった閣法では、省庁の分の合計が議員の役職の帳簿の合計に一致する。
  const assigned = new Set(published.ministries.flatMap(m => m.laws.map(l => l.lawId)));
  const officeTotal = sum(published.members.flatMap(m => m.laws.filter(l => assigned.has(l.lawId)).map(l => l.office.median)));
  expect(sum(published.ministries.flatMap(m => m.laws.map(l => l.share.median)))).toBe(officeTotal);
  // 支持でない質疑（中立・反対）は記録として context にだけ出し、配分の証拠（evidence）には入れない。
  for (const m of published.members) for (const l of m.laws) {
    for (const e of l.evidence) expect(['質疑（中立）', '質疑（反対）']).not.toContain(e.actionLabel);
    for (const e of l.context.filter(x => x.action === 'question')) expect(['質疑（法案を支持）', '質疑（中立）', '質疑（反対）']).toContain(e.actionLabel);
  }
  // 税の帳簿は別の物差し：消費税の引上げは損失、延期は便益で、年ごとの額を足すと合計になる。毎年の税制改正は増税・減税のどちらもある。
  for (const t of published.taxLedger) {
    expect(sum(t.years.map(y => y.amount))).toBe(t.total);
    if (t.kind !== '税制改正') expect(t.kind === '引上げ' ? t.total < 0 : t.total > 0).toBe(true);
    expect(t.certainty).toBe('低');
  }
}, 60_000); // 自動の関与（約1万2千行）を含めて作り直すので、既定の5秒では足りない
