// 議員ページの「全議員」の表 app/public/distribution/members-reference.json を作る（参考の額を印つきの別の欄で全員に配る）。
// 入力はリポジトリ内のデータだけ（公開ランキング・成立法の一覧・参議院の投票・内閣の名簿・現職の名簿）。
// 計算は app/src/members-reference.ts。使い方: node scripts/build_reference_members.mjs [--attributions 出力先.csv] [--no-write]
// --attributions：全員・全法律の配り先（公開ファイルには入れない）を CSV に書く。scripts/check_reference_members.py が一次資料と照らす。
// --no-write：公開ファイルを書かない（照合だけのとき）。
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generationMetadata } from './generation_provenance.mjs';

const argv = process.argv.slice(2);
const attributionsOut = argv.includes('--attributions') ? argv[argv.indexOf('--attributions') + 1] : '';
const noWrite = argv.includes('--no-write');
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'app');
const ballotsDir = join(root, 'data/acquired/sangiin-votes/ballots');
const inputs = {
  ranking: join(app, 'public/distribution/ranking.json'),
  enacted: join(root, 'data/acquired/bill-census-full/enacted.csv'),
  votesIndex: join(root, 'data/acquired/sangiin-votes/votes_index.csv'),
  sangiinMembers: join(root, 'data/acquired/sangiin-votes/members.csv'),
  cabinet: join(root, 'data/acquired/office-holders/cabinet.csv'),
  roster: join(root, 'data/acquired/diet-roster/current.csv'),
  persons: join(root, 'data/derived/person-ids/persons.csv'),
  // 当時の会派（scripts/fetch_affiliation_at_time.py）。無ければ元職は参議院の最終会派だけになる。
  affiliationAtTime: join(root, 'data/acquired/member-affiliation/at-time.csv'),
};
const { createServer } = await import(join(app, 'node_modules/vite/dist/node/index.js'));
const server = await createServer({ root: app, logLevel: 'silent', server: { middlewareMode: true }, appType: 'custom' });
// members を1人1行に並べる。JSON としての中身は1行形と同じ。1人変わっても差分がその行だけになり、
// 名義検査の「大きすぎる中身」（1コミットで足す行の上限）に当たらない。
function stringifyOnePerLine(payload) {
  const parts = Object.entries(payload).map(([k, v]) => k === 'members'
    ? `"members":[\n${v.map(m => JSON.stringify(m)).join(',\n')}\n]`
    : `${JSON.stringify(k)}:${JSON.stringify(v)}`);
  return '{' + parts.join(',\n') + '}\n';
}

try {
  const { buildReferenceMembers } = await server.ssrLoadModule('/src/members-reference.ts');
  const text = Object.fromEntries(Object.entries(inputs).map(([k, p]) => [k, readFileSync(p, 'utf8')]));
  const ballotFiles = readdirSync(ballotsDir).filter(f => f.endsWith('.csv')).sort();
  const ballots = ballotFiles.map(f => readFileSync(join(ballotsDir, f), 'utf8'));
  const { attributions, ...payload } = buildReferenceMembers({ ...text, ranking: JSON.parse(text.ranking), ballots });
  if (attributionsOut) {
    const cell = v => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
    const head = ['member', 'name', 'house', 'lawId', 'role', 'side', 'median'];
    writeFileSync(attributionsOut, [head.join(','), ...attributions.map(a => head.map(k => cell(a[k])).join(','))].join('\n') + '\n');
  }
  payload.generatedFrom = await generationMetadata(server, root, ['app/src/members-reference.ts'], ['scripts/build_reference_members.mjs']);
  payload.inputs = Object.fromEntries(Object.entries(text).map(([k, t]) => [k, createHash('sha256').update(t).digest('hex')]));
  // 個人別の賛否（ballots_*.csv）は、ファイル名と中身を順に並べた1つの照合値にする（tests/test_public_sync.py が同じ方法で確かめる）。
  const ballotHash = createHash('sha256');
  ballotFiles.forEach((f, i) => ballotHash.update(f + '\n').update(ballots[i]).update('\n'));
  payload.inputs.ballots = ballotHash.digest('hex');
  if (!noWrite) writeFileSync(join(app, 'public/distribution/members-reference.json'), stringifyOnePerLine(payload));
  console.log(JSON.stringify(payload.counts));
} finally {
  await server.close();
}
