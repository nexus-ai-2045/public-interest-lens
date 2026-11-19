// 曝露ランキング（案B）の集計結果 data/derived/exposure-v1/exposure-ranking.json を作る。画面には出さない（表示は別の変更）。
// 入力はリポジトリ内のデータだけ。入力の組み立ては app/src/exposure-inputs.ts、集計は app/src/exposure-ranking.ts。
// 額は群（産業×年。data/derived/exposure-v1/industry-year.csv）の OECD 比較国との伸びの差を役割の固定比率で配った記述で、因果の推定ではない。出力に法律の ID は入れない。
// 本体は産業別。全産業（_T）は産業別と同じ額を重ねて数えるので足さず、wholeEconomy 欄に別に出す。
// 使い方: node scripts/build_exposure_ranking.mjs [--out 出力先.json] [--no-write] [--sensitivity 出力.md] [--help]
import { createHash } from 'node:crypto';
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generationMetadata } from './generation_provenance.mjs';

const argv = process.argv.slice(2);
if (argv.includes('--help') || argv.includes('-h')) {
  console.log(`曝露ランキング（案B）の集計結果を作る。

使い方: node scripts/build_exposure_ranking.mjs [--out <出力先>] [--no-write] [--sensitivity <出力.md>] [--help]

  --out <path>          出力先（既定：data/derived/exposure-v1/exposure-ranking.json）
  --no-write            検算だけして、ファイルは書かない
  --sensitivity <path>  役割の比率を5通りに変えたときの産業別の人の順位の動きを Markdown の表で書く（人名は書かない）
  --help                この説明を出して終了する

標準出力に counts と totals を JSON で1行出す。検算（人＋会派＋未配分＝期待値、相対誤差 1e-9）が合わない、
または出力に法律の ID が混ざっているときは、書かずに終了コード1で止まる。`);
  process.exit(0);
}
const noWrite = argv.includes('--no-write');
const outIdx = argv.indexOf('--out');
if (outIdx >= 0 && !argv[outIdx + 1]) { console.error('--out に出力先がありません'); process.exit(2); }
const sensIdx = argv.indexOf('--sensitivity');
if (sensIdx >= 0 && !argv[sensIdx + 1]) { console.error('--sensitivity に出力先がありません'); process.exit(2); }
const sensOut = sensIdx >= 0 ? resolve(argv[sensIdx + 1]) : '';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'app');
const out = outIdx >= 0 ? resolve(argv[outIdx + 1]) : join(root, 'data/derived/exposure-v1/exposure-ranking.json');
const ballotsDir = join(root, 'data/acquired/sangiin-votes/ballots');
const inputs = {
  macro: join(root, 'data/derived/macro-v1/macro.csv'),
  industryYear: join(root, 'data/derived/exposure-v1/industry-year.csv'),
  enacted: join(root, 'data/acquired/bill-census-full/enacted.csv'),
  cabinet: join(root, 'data/acquired/office-holders/cabinet.csv'),
  persons: join(root, 'data/derived/person-ids/persons.csv'),
  roster: join(root, 'data/acquired/diet-roster/current.csv'),
  involvements: join(root, 'data/derived/allocation-v1/involvements.csv'),
  involvementsAuto: join(root, 'data/derived/allocation-v1/involvements-auto.csv'),
  // 賛成・反対は投票の一次資料から取る（参議院は個人票、衆議院は enacted.csv の会派）。
  votesIndex: join(root, 'data/acquired/sangiin-votes/votes_index.csv'),
  sangiinMembers: join(root, 'data/acquired/sangiin-votes/members.csv'),
};
const { createServer } = await import(join(app, 'node_modules/vite/dist/node/index.js'));
const server = await createServer({ root: app, logLevel: 'silent', server: { middlewareMode: true }, appType: 'custom' });

// people を1人1行に並べる（wholeEconomy の people も）。JSON としての中身は1行形と同じ。1人変わっても差分がその行だけになる。
function stringifyOnePerLine(payload) {
  const peopleLines = v => `"people":[\n${v.map(m => JSON.stringify(m)).join(',\n')}\n]`;
  const parts = Object.entries(payload).map(([k, v]) => {
    if (k === 'people') return peopleLines(v);
    if (k === 'wholeEconomy') return `"wholeEconomy":{${Object.entries(v).map(([kk, vv]) => kk === 'people' ? peopleLines(vv) : `${JSON.stringify(kk)}:${JSON.stringify(vv)}`).join(',\n')}}`;
    return `${JSON.stringify(k)}:${JSON.stringify(v)}`;
  });
  return '{' + parts.join(',\n') + '}\n';
}

// 検算：人＋会派＋未配分＝期待値（low・median・high とも相対誤差 1e-9 以内）。
function checkTotals(label, t) {
  for (const k of ['low', 'median', 'high']) {
    const got = t.people[k] + t.parties[k] + t.unallocated[k];
    const err = Math.abs(got - t.expected[k]) / Math.max(1, Math.abs(t.expected[k]));
    if (!(err <= 1e-9)) { console.error(`検算が合いません（${label}）：${k} 合計=${got} 期待=${t.expected[k]} 相対誤差=${err}`); process.exit(1); }
  }
}

// 順位相関（同順位は平均順位）。
function ranks(values) {
  const idx = values.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
  const r = new Array(values.length);
  for (let i = 0; i < idx.length;) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
    for (let k = i; k <= j; k++) r[idx[k][1]] = (i + j) / 2 + 1;
    i = j + 1;
  }
  return r;
}
function spearman(a, b) {
  const ra = ranks(a), rb = ranks(b);
  const n = a.length;
  const ma = ra.reduce((x, y) => x + y, 0) / n, mb = rb.reduce((x, y) => x + y, 0) / n;
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < n; i++) { sab += (ra[i] - ma) * (rb[i] - mb); saa += (ra[i] - ma) ** 2; sbb += (rb[i] - mb) ** 2; }
  return sab / Math.sqrt(saa * sbb);
}

try {
  const { buildExposureInputs, withLedgerPeople } = await server.ssrLoadModule('/src/exposure-inputs.ts');
  const { buildExposureRanking, DEFAULT_ROLE_RATIO } = await server.ssrLoadModule('/src/exposure-ranking.ts');
  const { SCORING_CONSTANTS } = await server.ssrLoadModule('/src/scoring-constants.ts');
  const text = Object.fromEntries(Object.entries(inputs).map(([k, p]) => [k, readFileSync(p, 'utf8')]));
  const ballotFiles = readdirSync(ballotsDir).filter(f => f.endsWith('.csv')).sort();
  const ballots = ballotFiles.map(f => readFileSync(join(ballotsDir, f), 'utf8'));
  const built = buildExposureInputs({
    macro: text.macro, industryYear: text.industryYear, enacted: text.enacted, cabinet: text.cabinet, persons: text.persons, roster: text.roster,
    involvements: [text.involvements, text.involvementsAuto],
    votesIndex: text.votesIndex, sangiinMembers: text.sangiinMembers, ballots,
  });
  const paramsOf = roleRatio => ({ roleRatio, minLaws: SCORING_CONSTANTS.minContributingLaws, topThreeShareCap: SCORING_CONSTANTS.topThreeShareCap });
  const rank = (bucket, roleRatio) => buildExposureRanking(bucket.groups, bucket.involvements, paramsOf(roleRatio));
  // 産業別（本体）と全産業（別欄）。全産業は産業別と同じ額を重ねて数えるので足さない。
  const industryRanking = rank(built.industry, DEFAULT_ROLE_RATIO);
  const whole = rank(built.wholeEconomy, DEFAULT_ROLE_RATIO);
  // 人物台帳の全員を本体に1回ずつ載せる（点あり＝tier が数、点なし＝tier が null で unrankedReason に理由）。
  const { ranking, coverage } = withLedgerPeople(industryRanking, text.persons, whole);
  checkTotals('産業別', ranking.totals);
  checkTotals('全産業', whole.totals);

  const groupRow = bucket => {
    const lawsWithRecord = new Map();
    for (const i of bucket.involvements) lawsWithRecord.set(i.groupId, (lawsWithRecord.get(i.groupId) ?? new Set()).add(i.lawId));
    return bucket.groups.map(g => ({ id: g.id, group: g.group, window: g.window, diff: g.diff, benchmark: g.benchmark, lawCount: g.lawCount, lawsWithInvolvement: lawsWithRecord.get(g.id)?.size ?? 0 }));
  };
  const payload = {
    ...ranking,
    wholeEconomy: { groups: groupRow(built.wholeEconomy), people: whole.people, parties: whole.parties, unallocated: whole.unallocated, totals: whole.totals },
    groups: groupRow(built.industry),
    counts: built.counts,
    coverage,
  };
  payload.generatedFrom = await generationMetadata(server, root, ['app/src/exposure-inputs.ts', 'app/src/exposure-ranking.ts', 'app/src/scoring-constants.ts', 'app/src/members-reference.ts'], ['scripts/build_exposure_ranking.mjs']);
  payload.inputs = Object.fromEntries(Object.entries(text).map(([k, v]) => [k, createHash('sha256').update(v).digest('hex')]));
  // 個人別の賛否（ballots_*.csv）は、ファイル名と中身を順に並べた1つの照合値にする（build_reference_members.mjs と同じ方法）。
  const ballotHash = createHash('sha256');
  ballotFiles.forEach((f, i) => ballotHash.update(f + '\n').update(ballots[i]).update('\n'));
  payload.inputs.ballots = ballotHash.digest('hex');
  const body = stringifyOnePerLine(payload);
  const leaked = /(閣法|衆法|参法)-\d+-\d+/.exec(body);
  if (leaked) { console.error('出力に法律の ID が混ざっています：書きません'); process.exit(1); }
  if (!noWrite) { mkdirSync(dirname(out), { recursive: true }); writeFileSync(out, body); }

  if (sensOut) {
    // 役割の比率（順は proposer / yes / no / cabinet、合計1）を5通りに変えたときの、産業別の人の順位の動き。階層に入った人どうしで比べる。
    const scenarios = [
      ['既定', DEFAULT_ROLE_RATIO],
      ['発議重め', { proposer: 0.5, yes: 0.2, no: 0.2, cabinet: 0.1 }],
      ['閣議重め', { proposer: 0.3, yes: 0.2, no: 0.2, cabinet: 0.3 }],
      ['賛否重め', { proposer: 0.3, yes: 0.3, no: 0.3, cabinet: 0.1 }],
      ['発議軽め', { proposer: 0.2, yes: 0.3, no: 0.3, cabinet: 0.2 }],
    ];
    const rankedOf = r => r.people.filter(p => p.tier !== null).map(p => [p.actorId, p.exposureYen.median]);
    const base = rankedOf(rank(built.industry, scenarios[0][1]));
    const baseMap = new Map(base);
    const edge = (list, n, dir) => new Set([...list].sort((a, b) => dir * (b[1] - a[1]) || a[0].localeCompare(b[0])).slice(0, n).map(x => x[0]));
    const swapped = (a, b) => [...a].filter(x => !b.has(x)).length;
    const lines = [
      '# 役割の比率を変えたときの順位の動き（産業別・曝露ランキング）',
      '',
      '役割の比率の順は proposer / yes / no / cabinet（合計1）。人名は書かない。順位は階層に入った人の額の中央値の大きい順。',
      'Spearman は既定と、その比率でも階層に入った人どうしの順位相関。入れ替わりは、上位10人（額が大きい側）・下位10人（額が小さい側）のうち既定の10人に入らなかった人数。',
      '',
      '| 比率 | 発議 | 賛成 | 反対 | 閣議 | 階層に入る人数 | 既定と共通の人数 | Spearman | 上位10人の入れ替わり | 下位10人の入れ替わり |',
      '|---|---|---|---|---|---|---|---|---|---|',
    ];
    for (const [name, ratio] of scenarios) {
      const cur = rankedOf(rank(built.industry, ratio));
      const both = cur.filter(([id]) => baseMap.has(id));
      const rho = both.length > 1 ? spearman(both.map(x => baseMap.get(x[0])), both.map(x => x[1])) : NaN;
      const top = swapped(edge(base, 10, 1), edge(cur, 10, 1));
      const bottom = swapped(edge(base, 10, -1), edge(cur, 10, -1));
      lines.push(`| ${name} | ${ratio.proposer} | ${ratio.yes} | ${ratio.no} | ${ratio.cabinet} | ${cur.length} | ${both.length} | ${rho.toFixed(4)} | ${top} | ${bottom} |`);
    }
    lines.push('');
    mkdirSync(dirname(sensOut), { recursive: true });
    writeFileSync(sensOut, lines.join('\n'));
  }
  console.log(JSON.stringify({ counts: built.counts, coverage, totals: ranking.totals, wholeEconomyTotals: whole.totals }));
} finally {
  await server.close();
}
