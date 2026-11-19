// 曝露ランキング（案B）の集計結果 data/derived/exposure-v1/exposure-ranking.json を作る。画面には出さない（表示は別の変更）。
// 入力はリポジトリ内のデータだけ。入力の組み立ては app/src/exposure-inputs.ts、集計は app/src/exposure-ranking.ts。
// 額は群（産業×窓）の OECD 比較国との差を役割の固定比率で配った記述で、因果の推定ではない。出力に法律の ID は入れない。
// 使い方: node scripts/build_exposure_ranking.mjs [--out 出力先.json] [--no-write] [--help]
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generationMetadata } from './generation_provenance.mjs';

const argv = process.argv.slice(2);
if (argv.includes('--help') || argv.includes('-h')) {
  console.log(`曝露ランキング（案B）の集計結果を作る。

使い方: node scripts/build_exposure_ranking.mjs [--out <出力先>] [--no-write] [--help]

  --out <path>  出力先（既定：data/derived/exposure-v1/exposure-ranking.json）
  --no-write    検算だけして、ファイルは書かない
  --help        この説明を出して終了する

標準出力に counts と totals を JSON で1行出す。検算（人＋会派＋未配分＝期待値、相対誤差 1e-9）が合わない、
または出力に法律の ID が混ざっているときは、書かずに終了コード1で止まる。`);
  process.exit(0);
}
const noWrite = argv.includes('--no-write');
const outIdx = argv.indexOf('--out');
if (outIdx >= 0 && !argv[outIdx + 1]) { console.error('--out に出力先がありません'); process.exit(2); }
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'app');
const out = outIdx >= 0 ? resolve(argv[outIdx + 1]) : join(root, 'data/derived/exposure-v1/exposure-ranking.json');
const inputs = {
  macro: join(root, 'data/derived/macro-v1/macro.csv'),
  enacted: join(root, 'data/acquired/bill-census-full/enacted.csv'),
  cabinet: join(root, 'data/acquired/office-holders/cabinet.csv'),
  persons: join(root, 'data/derived/person-ids/persons.csv'),
  roster: join(root, 'data/acquired/diet-roster/current.csv'),
  involvements: join(root, 'data/derived/allocation-v1/involvements.csv'),
  involvementsAuto: join(root, 'data/derived/allocation-v1/involvements-auto.csv'),
  opposing: join(root, 'data/derived/allocation-v1/opposing.csv'),
};
const { createServer } = await import(join(app, 'node_modules/vite/dist/node/index.js'));
const server = await createServer({ root: app, logLevel: 'silent', server: { middlewareMode: true }, appType: 'custom' });

// people を1人1行に並べる。JSON としての中身は1行形と同じ。1人変わっても差分がその行だけになる。
function stringifyOnePerLine(payload) {
  const parts = Object.entries(payload).map(([k, v]) => k === 'people'
    ? `"people":[\n${v.map(m => JSON.stringify(m)).join(',\n')}\n]`
    : `${JSON.stringify(k)}:${JSON.stringify(v)}`);
  return '{' + parts.join(',\n') + '}\n';
}

try {
  const { buildExposureInputs, withLedgerPeople } = await server.ssrLoadModule('/src/exposure-inputs.ts');
  const { buildExposureRanking, DEFAULT_ROLE_RATIO } = await server.ssrLoadModule('/src/exposure-ranking.ts');
  const { SCORING_CONSTANTS } = await server.ssrLoadModule('/src/scoring-constants.ts');
  const text = Object.fromEntries(Object.entries(inputs).map(([k, p]) => [k, readFileSync(p, 'utf8')]));
  const built = buildExposureInputs({
    macro: text.macro, enacted: text.enacted, cabinet: text.cabinet, persons: text.persons, roster: text.roster,
    involvements: [text.involvements, text.involvementsAuto], opposing: text.opposing,
  });
  // 人物台帳の全員を1回ずつ載せる（点あり＝tier が数、点なし＝tier が null で unrankedReason に理由）。
  const { ranking, coverage } = withLedgerPeople(buildExposureRanking(built.groups, built.involvements, { roleRatio: DEFAULT_ROLE_RATIO, minLaws: SCORING_CONSTANTS.minContributingLaws }), text.persons);

  // 検算：人＋会派＋未配分＝期待値（low・median・high とも相対誤差 1e-9 以内）。
  const t = ranking.totals;
  for (const k of ['low', 'median', 'high']) {
    const got = t.people[k] + t.parties[k] + t.unallocated[k];
    const err = Math.abs(got - t.expected[k]) / Math.max(1, Math.abs(t.expected[k]));
    if (!(err <= 1e-9)) { console.error(`検算が合いません：${k} 合計=${got} 期待=${t.expected[k]} 相対誤差=${err}`); process.exit(1); }
  }
  const lawsWithRecord = new Map();
  for (const i of built.involvements) lawsWithRecord.set(i.groupId, (lawsWithRecord.get(i.groupId) ?? new Set()).add(i.lawId));
  const payload = {
    ...ranking,
    groups: built.groups.map(g => ({ id: g.id, group: g.group, window: g.window, diff: g.diff, benchmark: g.benchmark, lawCount: g.lawCount, lawsWithInvolvement: lawsWithRecord.get(g.id)?.size ?? 0 })),
    counts: built.counts,
    coverage,
  };
  payload.generatedFrom = await generationMetadata(server, root, ['app/src/exposure-inputs.ts', 'app/src/exposure-ranking.ts', 'app/src/scoring-constants.ts'], ['scripts/build_exposure_ranking.mjs']);
  payload.inputs = Object.fromEntries(Object.entries(text).map(([k, v]) => [k, createHash('sha256').update(v).digest('hex')]));
  const body = stringifyOnePerLine(payload);
  const leaked = /(閣法|衆法|参法)-\d+-\d+/.exec(body);
  if (leaked) { console.error('出力に法律の ID が混ざっています：書きません'); process.exit(1); }
  if (!noWrite) { mkdirSync(dirname(out), { recursive: true }); writeFileSync(out, body); }
  console.log(JSON.stringify({ counts: built.counts, coverage, totals: ranking.totals }));
} finally {
  await server.close();
}
