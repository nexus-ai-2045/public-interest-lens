// impact-v1：評価対象で施行日のある法律を impact-rule-v1 にかけ、data/derived/impact-v1/ に書き出す。
// 実行：cd app && node scripts/run-impact-v1.mjs --triage v1|v2（既定v2。v2出力は -triage-v2 接尾辞で分離）
// 判定ロジックは app/src/impact-rule.ts だけにあり、ここでは読み書きだけをする。
import { triagePaths } from './triage-paths.mjs';
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

const { version, derived } = triagePaths();
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
  // 施行日台帳を母集団とし、明示的に両系統が評価対象外で一致した行だけ除く。
  // 欠落・保留・食い違いは、指標が空でも影響表と一致表に残す。
  laws = [...enforcement.values()].filter(e => {
    const ag = agreement.compareTriage(e.id, line1ById.get(e.id), line2ById.get(e.id));
    return !(ag.agreed && ag.line1.verdict === '評価対象外');
  }).map(e => {
    const a = line1ById.get(e.id), b = line2ById.get(e.id);
    const use = a?.['結果'] === '評価対象' ? { field: a['分野'], indicator: a['指標'] }
      : b?.['系統2_判定'] === '評価対象' ? { field: b['系統2_分野'], indicator: b['系統2_指標'] }
      : { field: a?.['分野'] ?? b?.['系統2_分野'] ?? '', indicator: a?.['指標'] ?? b?.['系統2_指標'] ?? '' };
    const referenceSource = a?.['結果'] === '評価対象' ? '系統1'
      : b?.['系統2_判定'] === '評価対象' ? '系統2' : a ? '系統1' : b ? '系統2' : '入力';
    return { id: e.id, title: e['題名'], ...use, referenceSource, start: e['施行日'].trim() };
  });
  agreementPath = 'data/derived/bill-triage-v2/agreement.csv';
}
const triage = laws;
const lawIds = l => l.map(x => x.id);

const unknown = [...new Set(triage.filter(r => agreement.compareTriage(r.id, line1ById.get(r.id), line2ById.get(r.id)).agreed).map(r => r.indicator))].filter(i => !batch.INDICATOR_MAP.some(m => m.indicator === i));
if (unknown.length) throw new Error(`対応表にない指標: ${unknown.join(', ')}`);

// 一致の表は、v2 では施行日のある全行（両系統が評価対象外で一致した行も含む）。影響の判定に回るのは laws だけ。
const agreementIds = version === 'v2' ? [...enforcement.keys()] : lawIds(laws);
const agreementAll = new Map(agreementIds.map(id => [id, agreement.compareTriage(id, line1ById.get(id), line2ById.get(id))]));
const agreements = agreementAll;
const results = laws.map(law => agreement.holdByTriage(batch.evaluateLaw(tables, law), agreements.get(law.id), law.referenceSource));
const out = new URL(derived('impact'), root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('indicator-map.csv', out), batch.toCsv(batch.MAP_HEADER, batch.INDICATOR_MAP.map(batch.mapRow)));
writeFileSync(new URL('impact.csv', out), batch.toCsv(batch.IMPACT_HEADER, results.map(batch.impactRow)));
writeFileSync(new URL(agreementPath, root), batch.toCsv(agreement.TRIAGE_AGREEMENT_HEADER, agreementIds.map(id => agreement.triageAgreementRow(enforcement.get(id)['題名'], agreementAll.get(id)))));

const count = (key, f = v => v) => results.reduce((m, r) => m.set(f(r[key]), (m.get(f(r[key])) ?? 0) + 1), new Map());
console.log(`振り分け ${version}：影響の判定に回す ${laws.length} 本。振り分けの2系統の一致 ${[...agreements.values()].filter(a => a.agreed).length}/${agreementIds.length}`);
console.log('判定:', Object.fromEntries(count('verdict')));
console.log('国際比較:', Object.fromEntries(count('cross', v => v.replace(/（.*$/, ''))));
