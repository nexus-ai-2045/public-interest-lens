// 曝露ランキング（案B）の集計結果 data/derived/exposure-v1/exposure-ranking.json を作る。画面には出さない（表示は別の変更）。
// 書き出す JSON は公開用（exposure-ranking.ts の toPublicExposureRanking）：法律1本ぶんの額が読めないよう、階層に入らない人・会派の額と本数の少ない内訳の額を出さない。
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
const USAGE = `使い方: node scripts/build_exposure_ranking.mjs [--out <出力先>] [--no-write] [--sensitivity <出力.md>] [--help]`;
if (argv.includes('--help') || argv.includes('-h')) {
  console.log(`曝露ランキング（案B）の集計結果を作る。

${USAGE}

  --out <path>          出力先（既定：data/derived/exposure-v1/exposure-ranking.json）
  --no-write            検算だけして、ファイルは書かない
  --sensitivity <path>  役割の比率を5通りに変えたときの産業別の人の順位の動きを Markdown の表で書く（人名は書かない）
  --help                この説明を出して終了する

書き出す JSON は公開用：階層に入らない人・会派の額と、本数が下限に満たない内訳の額は出さない（法律1本ぶんの額が読めないように）。
額を出さない人・会派が合わせて1つだけのときは、額を出さない人・会派の合計、totals の全部、未配分の内訳の額も伏せる。
標準出力に counts と totals（公開用）を JSON で1行出す。内部の検算（人＋会派＋未配分＝期待値、相対誤差 1e-9）が合わない、
公開用に額が残っている、または出力に法律の ID が混ざっているときは、書かずに終了コード1で止まる。
未知の引数、値の無い --out・--sensitivity、値が -- で始まる --out・--sensitivity は終了コード2で止まる。`);
  process.exit(0);
}
// 引数：未知の引数と、値の無い（または次の引数 -- で始まる）--out・--sensitivity はエラー（終了コード2）。
const argError = msg => { console.error(`${msg}\n${USAGE}`); process.exit(2); };
let noWrite = false;
let outArg = '';
let sensArg = '';
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--no-write') noWrite = true;
  else if (a === '--out' || a === '--sensitivity') {
    const v = argv[i + 1];
    if (v === undefined || v === '') argError(`${a} に出力先がありません`);
    if (v.startsWith('--')) argError(`${a} の値が -- で始まっています：${v}`);
    if (a === '--out') outArg = v; else sensArg = v;
    i++;
  } else argError(`未知の引数です：${a}`);
}
const sensOut = sensArg ? resolve(sensArg) : '';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'app');
const out = outArg ? resolve(outArg) : join(root, 'data/derived/exposure-v1/exposure-ranking.json');
const ballotsDir = join(root, 'data/acquired/sangiin-votes/ballots');
const inputs = {
  macro: join(root, 'data/derived/macro-v1/macro.csv'),
  industryYear: join(root, 'data/derived/exposure-v1/industry-year.csv'),
  enacted: join(root, 'data/acquired/bill-census-full/enacted.csv'),
  cabinet: join(root, 'data/acquired/office-holders/cabinet.csv'),
  persons: join(root, 'data/derived/person-ids/persons.csv'),
  roster: join(root, 'data/acquired/diet-roster/current.csv'),
  // 台帳に読みが無い人の読みの補い（国会会議録の発言者の読み。scripts/fetch_person_readings.py）。並びだけに使う。
  readingsKokkai: join(root, 'data/acquired/diet-roster/readings-kokkai.csv'),
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

// 公開用の検査：階層に入らない行に額が無い／本数が下限に満たない内訳に額が無い／階層に入った行には額がある。破れたら終了コード1。
// 額を出さない行の数と、額を消した内訳の数を返す。
function checkPublic(label, p, minLaws) {
  const stats = { hiddenPeople: 0, hiddenParties: 0, hiddenCells: 0 };
  const fail = msg => { console.error(`公開用の検査に失敗（${label}）：${msg}`); process.exit(1); };
  for (const [kind, rows] of [['人', p.people], ['会派', p.parties]]) {
    for (const r of rows) {
      if (r.tier === null) {
        if (r.exposureYen !== null) fail(`階層に入らない${kind}の行に額がある`);
        if (kind === '人') stats.hiddenPeople++; else stats.hiddenParties++;
      } else if (r.exposureYen === null) fail(`階層に入った${kind}の行に額が無い`);
      for (const c of r.cells) {
        if (r.tier === null && c.exposureYen !== null) fail(`階層に入らない${kind}の内訳に額がある`);
        if (c.laws < minLaws && c.exposureYen !== null) fail(`本数が下限に満たない内訳に額がある（${c.laws}本）`);
        if (c.exposureYen === null) stats.hiddenCells++;
      }
    }
  }
  const withheld = stats.hiddenPeople + stats.hiddenParties === 1;
  if (withheld && (Object.values(p.totals).some(v => v !== null) || p.unallocated.some(u => u.exposureYen !== null) || p.hidden.people.exposureYen !== null || p.hidden.parties.exposureYen !== null)) fail('額を出さない行が1つだけなのに合計が伏せられていない');
  if (!withheld && (p.totals.people === null || p.totals.parties === null)) fail('額を出さない行が1つだけでないのに合計が伏せられている');
  if (p.hidden.people.count !== stats.hiddenPeople || p.hidden.parties.count !== stats.hiddenParties) fail('額を出さない行の件数が合わない');
  return stats;
}

// 人物ID → 読み。本体に載る人で、読みが分かる人だけ。人物台帳の読みを先に使い、空なら国会会議録の発言者の読み（readings-kokkai.csv）で補う。
function personReadings(personsRows, kokkaiRows, people) {
  const ids = new Set(people.map(p => p.actorId));
  const kokkai = new Map(kokkaiRows.filter(r => r['人物ID'] && r['読み']).map(r => [r['人物ID'], r['読み']]));
  const out = {};
  for (const r of personsRows) {
    if (!ids.has(r['人物ID'])) continue;
    // 台帳の読みは姓と名の間に空白がある（会議録の読みには無い）。混ぜて並べるので空白を除いてそろえる。
    const squash = v => (v || '').replace(/\s+/g, '');
    const reading = squash(r['読み']) || squash(kokkai.get(r['人物ID']));
    if (reading) out[r['人物ID']] = reading;
  }
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b)));
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
  const { buildExposureRanking, toPublicExposureRanking, DEFAULT_ROLE_RATIO } = await server.ssrLoadModule('/src/exposure-ranking.ts');
  const { SCORING_CONSTANTS } = await server.ssrLoadModule('/src/scoring-constants.ts');
  const { parseCsv } = await server.ssrLoadModule('/src/impact-batch.ts');
  const text = Object.fromEntries(Object.entries(inputs).map(([k, p]) => [k, readFileSync(p, 'utf8')]));
  const ballotFiles = readdirSync(ballotsDir).filter(f => f.endsWith('.csv')).sort();
  const ballots = ballotFiles.map(f => readFileSync(join(ballotsDir, f), 'utf8'));
  const built = buildExposureInputs({
    macro: text.macro, industryYear: text.industryYear, enacted: text.enacted, cabinet: text.cabinet, persons: text.persons, roster: text.roster,
    votesIndex: text.votesIndex, sangiinMembers: text.sangiinMembers, ballots,
  });
  const paramsOf = roleRatio => ({ roleRatio, minLaws: SCORING_CONSTANTS.minContributingLaws, topThreeShareCap: SCORING_CONSTANTS.topThreeShareCap });
  // 内訳（cells）は産業×役割に束ねる（産業×年のままだと出力が数十MBになる）。row の groups は産業×年の数のまま。
  const rank = (bucket, roleRatio) => {
    const industryOf = new Map(bucket.groups.map(g => [g.id, g.group]));
    return buildExposureRanking(bucket.groups, bucket.involvements, paramsOf(roleRatio), { cellGroupOf: id => industryOf.get(id) ?? id });
  };
  // 産業別（本体）と全産業（別欄）。全産業は産業別と同じ額を重ねて数えるので足さない。
  const industryRanking = rank(built.industry, DEFAULT_ROLE_RATIO);
  const whole = rank(built.wholeEconomy, DEFAULT_ROLE_RATIO);
  // 人物台帳の全員を本体に1回ずつ載せる（点あり＝tier が数、点なし＝tier が null で unrankedReason に理由）。
  const { ranking, coverage } = withLedgerPeople(industryRanking, text.persons, whole);
  checkTotals('産業別', ranking.totals);
  checkTotals('全産業', whole.totals);

  // 公開用に変える（内部の検算は変える前の ranking・whole で済ませた）。階層に入らない行の額と、本数が下限に満たない内訳の額を出さない。
  const minLaws = SCORING_CONSTANTS.minContributingLaws;
  const pub = toPublicExposureRanking(ranking, minLaws);
  const pubWhole = toPublicExposureRanking(whole, minLaws);
  const publicStats = checkPublic('産業別', pub, minLaws);
  const publicStatsWhole = checkPublic('全産業', pubWhole, minLaws);

  const groupRow = bucket => {
    const lawsWithRecord = new Map();
    for (const i of bucket.involvements) lawsWithRecord.set(i.groupId, (lawsWithRecord.get(i.groupId) ?? new Set()).add(i.lawId));
    return bucket.groups.map(g => ({ id: g.id, group: g.group, window: g.window, diff: g.diff, benchmark: g.benchmark, lawCount: g.lawCount, lawsWithInvolvement: lawsWithRecord.get(g.id)?.size ?? 0 }));
  };
  const payload = {
    ...pub,
    wholeEconomy: { groups: groupRow(built.wholeEconomy), people: pubWhole.people, parties: pubWhole.parties, hidden: pubWhole.hidden, unallocated: pubWhole.unallocated, totals: pubWhole.totals },
    groups: groupRow(built.industry),
    counts: built.counts,
    coverage,
    // 階層の中の並び（五十音）に使う読み。人物台帳（persons.csv）の「読み」、空なら会議録の発言者の読み（readings-kokkai.csv）を、本体に載る人のうち読みの分かる人だけ出す。
    personReadings: personReadings(parseCsv(text.persons), parseCsv(text.readingsKokkai), pub.people),
  };
  payload.generatedFrom = await generationMetadata(server, root, ['app/src/exposure-inputs.ts', 'app/src/exposure-ranking.ts', 'app/src/scoring-constants.ts'], ['scripts/build_exposure_ranking.mjs']);
  payload.inputs = Object.fromEntries(Object.entries(text).map(([k, v]) => [k, createHash('sha256').update(v).digest('hex')]));
  // 個人別の賛否（ballots_*.csv）は、ファイル名と中身を順に並べた1つの照合値にする。
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
  console.log(JSON.stringify({ counts: built.counts, coverage, totals: pub.totals, wholeEconomyTotals: pubWhole.totals, publicStats: { ...publicStats, wholeEconomy: publicStatsWhole, hidden: pub.hidden } }));
} finally {
  await server.close();
}
