// 公開用の議員ページのデータ app/public/distribution/members.json を作る。
// 入力はリポジトリ内の派生データだけ（関与の一覧・publish.csv・loss.csv・成立法の一覧・参議院の投票）。
// 計算は app/src/members-build.ts（中は causal-allocation.ts）をそのまま使う。
// 使い方: node scripts/build_public_members.mjs
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'app');
const inputs = {
  involvements: join(root, 'data/derived/allocation-v1/involvements.csv'),
  publish: join(root, 'data/derived/publish-v1-triage-v2/publish.csv'),
  loss: join(root, 'data/derived/loss-v1-triage-v2/loss.csv'),
  enacted: join(root, 'data/acquired/bill-census-full/enacted.csv'),
  votes: join(root, 'data/derived/allocation-v1/votes.csv'),
};
const { createServer } = await import(join(app, 'node_modules/vite/dist/node/index.js'));
const server = await createServer({ root: app, logLevel: 'silent', server: { middlewareMode: true }, appType: 'custom' });
try {
  const { buildMembers } = await server.ssrLoadModule('/src/members-build.ts');
  const text = Object.fromEntries(Object.entries(inputs).map(([k, p]) => [k, readFileSync(p, 'utf8')]));
  const payload = buildMembers(text);
  payload.inputs = Object.fromEntries(Object.entries(text).map(([k, t]) => [k, createHash('sha256').update(t).digest('hex')]));
  writeFileSync(join(app, 'public/distribution/members.json'), JSON.stringify(payload) + '\n');
  console.log(JSON.stringify(payload.counts), payload.laws.map(l => l.id).join(' '));
} finally {
  await server.close();
}
