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
  });
  const { inputs, ...published } = JSON.parse(read('app/public/distribution/members.json'));
  expect(Object.keys(inputs).sort()).toEqual(['enacted', 'involvements', 'loss', 'publish']);
  expect(published).toEqual(JSON.parse(JSON.stringify(built)));
  for (const member of published.members) for (const law of member.laws) {
    expect(law.evidence.length).toBeGreaterThan(0);
    for (const ev of law.evidence) expect(ev.url).toMatch(/^https:\/\/(kokkai\.ndl\.go\.jp|www\.sangiin\.go\.jp|www\.shugiin\.go\.jp)\//);
  }
});
