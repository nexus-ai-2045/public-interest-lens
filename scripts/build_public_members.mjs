// 公開用の議員ページのデータ app/public/distribution/members.json を作る。
// 入力はリポジトリ内の派生データだけ（関与の一覧・publish.csv・loss.csv・成立法の一覧・参議院の投票・反対票）。
// 計算は app/src/members-build.ts（中は causal-allocation.ts）をそのまま使う。
// 使い方: node scripts/build_public_members.mjs
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generationMetadata } from './generation_provenance.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'app');
const inputs = {
  ranking: join(app, 'public/distribution/ranking.json'),
  involvements: join(root, 'data/derived/allocation-v1/involvements.csv'),
  publish: join(root, 'data/derived/publish-v1-triage-v2/publish.csv'),
  loss: join(root, 'data/derived/loss-v1-triage-v2/loss.csv'),
  enacted: join(root, 'data/acquired/bill-census-full/enacted.csv'),
  votes: join(root, 'data/derived/allocation-v1/votes.csv'),
  // 参議院本会議で反対した議員（scripts/build_opposing_votes.py が作る）。向きを逆にして配る（設計決定0014）。
  opposing: join(root, 'data/derived/allocation-v1/opposing.csv'),
  // 関与の一覧がまだ無い法律の、提出者の欄と参議院の賛成票から機械的に作った関与（scripts/build_auto_involvements.py）。
  autoInvolvements: join(root, 'data/derived/allocation-v1/involvements-auto.csv'),
  autoVotes: join(root, 'data/derived/allocation-v1/votes-auto.csv'),
  // 採決ごとの投票した議員の会派（scripts/build_vote_parties.py）。政党ランキングで採決した時の会派を決める。
  voteParties: join(root, 'data/derived/allocation-v1/vote-parties.csv'),
  // 閣法の所管の省庁（scripts/build_ministry_bills.py）。役職の帳簿を省庁の帳簿として見せる。
  ministries: join(root, 'data/derived/ministry-v1/cabinet-bills.csv'),
  // 税の帳簿（scripts/build_tax_ledger.py）。消費税率を変えた法律の額を政府のモデルの乗数で出した別の帳簿。
  taxLedger: join(root, 'data/derived/tax-v1/consumption-tax.csv'),
  taxRevenueForecasts: join(root, 'data/acquired/tax-revenue-estimates/estimates.csv'),
  // 省庁の抵抗の件数と団体の立場（scripts/build_org_ledger.py）。原本照合済みの記録の件数だけで、額は付けない。
  resistance: join(root, 'data/derived/org-ledger-v1/ministry-resistance.csv'),
  orgStances: join(root, 'data/derived/org-ledger-v1/org-stances.csv'),
  // 背後の力を議員の因果の鎖の結び目（法律）に結んだ表（scripts/build_backing_forces.py、設計決定0017）。点数には影響しない。
  backing: join(root, 'data/derived/backing-forces-v1/law-links.csv'),
};
const { createServer } = await import(join(app, 'node_modules/vite/dist/node/index.js'));
const server = await createServer({ root: app, logLevel: 'silent', server: { middlewareMode: true }, appType: 'custom' });
try {
  const { buildMembers } = await server.ssrLoadModule('/src/members-build.ts');
  const text = Object.fromEntries(Object.entries(inputs).map(([k, p]) => [k, readFileSync(p, 'utf8')]));
  // 同じ観測を共有する本数は、公開ランキングに残った法律だけで数える（出典チェックで外した法律は数えない）。
  const ranking = JSON.parse(text.ranking);
  const certainty = Object.fromEntries(ranking.laws.map(l => [l.id, l.certainty]));
  // 検証で参考に降格した法律（demotedReason あり）は額を残すが、順位と同じく議員の額には配らない。
  // 向きと額の符号が逆・関与の出典なしで額を付けないとした法律（outcomes.csv の判断。ranking.json の parameters.noAmount）は議員の額に配らない。
  const noAmount = new Set(ranking.generatedFrom.parameters.noAmount ?? []);
  const payload = buildMembers({ ...text, listed: ranking.laws.filter(l => !l.demotedReason).map(l => l.id).filter(id => !noAmount.has(id)), certainty });
  // 公開ランキングで確かさ高・中なのに、関わった議員の記録（提出・参議院の賛否）がまだ無く、ここに入っていない法律。
  // 議員ページに「集めている途中」として出し、全部のページで同じ法律の組が見えるようにする。
  const included = new Set(payload.laws.map(l => l.id));
  payload.pending = ranking.laws.filter(l => (l.certainty === '高' || l.certainty === '中') && !included.has(l.id))
    .map(l => ({ id: l.id, title: l.title, side: l.side, certainty: l.certainty, median: l.amountMedianYen }));
  payload.generatedFrom = await generationMetadata(server, root, ['app/src/members-build.ts'], ['scripts/build_public_members.mjs']);
  payload.inputs = Object.fromEntries(Object.entries(text).map(([k, t]) => [k, createHash('sha256').update(t).digest('hex')]));
  writeFileSync(join(app, 'public/distribution/members.json'), JSON.stringify(payload) + '\n');
  console.log(JSON.stringify(payload.counts), payload.laws.map(l => l.id).join(' '), `集めている途中 ${payload.pending.length}本`);
} finally {
  await server.close();
}
