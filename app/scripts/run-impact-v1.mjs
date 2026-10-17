// impact-v1：評価対象で施行日のある法律を impact-rule-v1 にかけ、data/derived/impact-v1/ に書き出す。
// 実行：cd app && node scripts/run-impact-v1.mjs （Node 22.18 以降。型注釈は Node が取り除く）
// 判定ロジックは app/src/impact-rule.ts だけにあり、ここでは読み書きだけをする。
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const batch = await import('../src/impact-batch.ts');
const agreement = await import('../src/line-agreement.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats', 'gap-stats']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv' && n !== 'status.csv')) {
    tables.set(`${dir}/${name}`, batch.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

// 振り分けの版：--triage v1 | v2、または環境変数 TRIAGE_VERSION。既定は v2（指標の選び方 indicator-pick-v1 を当てた bill-triage-v2）。
// v1 のときは従来どおり bill-triage-v1 を読み、bill-triage-v1/agreement.csv を書く。v2 のときは bill-triage-v1 には一切書かない。
const argVersion = process.argv.includes('--triage') ? process.argv[process.argv.indexOf('--triage') + 1] : undefined;
const version = argVersion ?? process.env.TRIAGE_VERSION ?? 'v2';
if (version !== 'v1' && version !== 'v2') throw new Error(`振り分けの版は v1 か v2: ${version}`);
const enforcement = new Map(batch.parseCsv(read('data/acquired/enforcement-dates/enforcement.csv')).filter(r => r['施行日'].trim() !== '').map(r => [r.id, r]));

// 設計決定0007：系統2（系統1を見ずに別のセッションが付けた振り分け）と判定・分野・指標が一致した法律だけ採用し、一致しなければ保留。
let line1ById, line2ById, laws, agreementPath;
if (version === 'v1') {
  const triageAll = batch.parseCsv(read('data/derived/bill-triage-v1/triage.csv'));
  line1ById = new Map(triageAll.map(r => [r.id, r]));
  line2ById = new Map(batch.parseCsv(read('data/derived/bill-triage-v1-line2/labels.csv')).map(r => [r.id, r]));
  laws = triageAll.filter(r => r['結果'] === '評価対象' && enforcement.has(r.id)).map(r => ({ id: r.id, title: enforcement.get(r.id)['題名'], field: r['分野'], indicator: r['指標'], start: enforcement.get(r.id)['施行日'].trim() }));
  agreementPath = 'data/derived/bill-triage-v1/agreement.csv';
} else {
  // v2：両系統とも indicator-pick-v1 を当てたあとのラベル（labels-line1.csv は結果・分野・指標、labels-line2.csv は系統2_判定・系統2_分野・系統2_指標）。
  const l1 = batch.parseCsv(read('data/derived/bill-triage-v2/labels-line1.csv'));
  const l2 = batch.parseCsv(read('data/derived/bill-triage-v2/labels-line2.csv'));
  line1ById = new Map(l1.map(r => [r.id, r]));
  line2ById = new Map(l2.map(r => [r.id, r]));
  // どちらかの系統が評価対象とした法律は影響の判定に回す（食い違えば保留）。両系統とも評価対象外なら対象から外れる。系統1が評価対象外なら系統2の分野・指標を参考に使う。
  laws = l1.filter(r => enforcement.has(r.id) && (r['結果'] === '評価対象' || line2ById.get(r.id)?.['系統2_判定'] === '評価対象')).map(r => {
    const use = r['結果'] === '評価対象' ? { field: r['分野'], indicator: r['指標'] } : { field: line2ById.get(r.id)['系統2_分野'], indicator: line2ById.get(r.id)['系統2_指標'] };
    return { id: r.id, title: enforcement.get(r.id)['題名'], field: use.field, indicator: use.indicator, start: enforcement.get(r.id)['施行日'].trim() };
  });
  agreementPath = 'data/derived/bill-triage-v2/agreement.csv';
}
const triage = laws;
const lawIds = l => l.map(x => x.id);

const unknown = [...new Set(triage.map(r => r.indicator))].filter(i => !batch.INDICATOR_MAP.some(m => m.indicator === i));
if (unknown.length) throw new Error(`対応表にない指標: ${unknown.join(', ')}`);

// 一致の表は、v2 では施行日のある全行（両系統が評価対象外で一致した行も含む）。影響の判定に回るのは laws だけ。
const agreementIds = version === 'v2' ? [...enforcement.keys()].filter(id => line1ById.has(id)) : lawIds(laws);
const agreementAll = new Map(agreementIds.map(id => [id, agreement.compareTriage(id, line1ById.get(id), line2ById.get(id))]));
const agreements = agreementAll;
const results = laws.map(law => agreement.holdByTriage(batch.evaluateLaw(tables, law), agreements.get(law.id)));
const out = new URL('data/derived/impact-v1/', root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('indicator-map.csv', out), batch.toCsv(batch.MAP_HEADER, batch.INDICATOR_MAP.map(batch.mapRow)));
writeFileSync(new URL('impact.csv', out), batch.toCsv(batch.IMPACT_HEADER, results.map(batch.impactRow)));
writeFileSync(new URL(agreementPath, root), batch.toCsv(agreement.TRIAGE_AGREEMENT_HEADER, agreementIds.map(id => agreement.triageAgreementRow(enforcement.get(id)['題名'], agreementAll.get(id)))));

const count = (key, f = v => v) => results.reduce((m, r) => m.set(f(r[key]), (m.get(f(r[key])) ?? 0) + 1), new Map());
console.log(`振り分け ${version}：影響の判定に回す ${laws.length} 本。振り分けの2系統の一致 ${[...agreements.values()].filter(a => a.agreed).length}/${agreementIds.length}`);
console.log('判定:', Object.fromEntries(count('verdict')));
console.log('国際比較:', Object.fromEntries(count('cross', v => v.replace(/（.*$/, ''))));
