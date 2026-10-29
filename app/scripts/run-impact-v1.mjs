// impact-v1：評価対象で施行日のある法律を impact-rule-v1 にかけ、指定した版の派生ディレクトリに書き出す。
// 実行：cd app && node scripts/run-impact-v1.mjs --triage v2（既定v2。v2出力は -triage-v2 接尾辞で分離）
// --triage v1 は data/derived/impact-v1/ を書き換えずに終了する。保存済みの対応表は今の INDICATOR_MAP では再現できない。
// 判定ロジックは app/src/impact-rule.ts だけにあり、ここでは読み書きだけをする。
import { triagePaths } from './triage-paths.mjs';
import { register } from 'node:module';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const batch = await import('../src/impact-batch.ts');
const agreement = await import('../src/line-agreement.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');
const { version, derived } = triagePaths();
// 保存済みの impact-v1 は今の対応表で再現できない。版の分離は保ったまま、書く前に終了する。
if (version === 'v1') {
  console.log('data/derived/impact-v1/ は保存済みの表です。今の対応表では再現できないので書き換えません。再計算は --triage v2 です。');
  process.exit(0);
}

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats', 'gap-stats', 'r3-series']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv' && n !== 'status.csv')) {
    tables.set(`${dir}/${name}`, batch.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const enforcement = new Map(batch.parseCsv(read('data/acquired/enforcement-dates/enforcement.csv')).filter(r => r['施行日'].trim() !== '').map(r => [r.id, r]));

// 設計決定0007：系統2（系統1を見ずに別のセッションが付けた振り分け）と判定・分野・指標が一致した法律だけ採用し、一致しなければ保留。
let line1ById, line2ById, laws, agreementPath;
// v2 だけ、食い違いに v2.1 の解消規則（HR3・HR4）を当てる（題名を渡す）。v1 は従来のまま。
// v2 では、2系統の食い違いと片方の保留に、第3の判定者（R2、tiebreak-lines.csv）がどちらの系統を採ったかも当てる（TB2）。
const LINE_TIEBREAK = 'data/derived/bill-triage-v2/tiebreak-lines.csv';
const lineTiebreak = new Map(existsSync(new URL(LINE_TIEBREAK, root)) ? batch.parseCsv(read(LINE_TIEBREAK)).map(r => [r.id, r]) : []);
// 判定したときの入力（系統1・系統2の判定|種類|分野|指標|理由、会議録の要約の指紋）が今と同じときだけ当てる。
// 違えば保留に戻り、翌朝また判定する（式は scripts/eval_loop.py の value1・value2・overview_value と同じ）
const value1 = r => r ? [r['結果'], r['種類'], r['分野'], r['指標'], r['理由']].join('|') : '';
const value2 = r => r ? [r['系統2_判定'], r['系統2_種類'], r['系統2_分野'], r['系統2_指標'], r['系統2_理由']].join('|') : '';
const OVERVIEWS = 'data/derived/law-overviews-v1/overviews.csv';
const overviewById = new Map(existsSync(new URL(OVERVIEWS, root)) ? batch.parseCsv(read(OVERVIEWS)).map(r => [r.id, r]) : []);
const overviewValue = id => {
  const o = overviewById.get(id) ?? {};
  return createHash('sha256').update(`${o['何をする'] ?? ''}\n${o['狙い'] ?? ''}`, 'utf8').digest('hex').slice(0, 16);
};
const currentTiebreak = id => {
  const tb = lineTiebreak.get(id);
  if (!tb || tb['系統1の値'] !== value1(line1ById.get(id)) || tb['系統2の値'] !== value2(line2ById.get(id))
      || tb['概要の値'] !== overviewValue(id)) return undefined;
  // 題名列がある行は、判定した題名と今の台帳の題名が同じときだけ当てる。空は題名を残す前の行。
  const storedTitle = tb['題名'];
  const title = enforcement.get(id)?.['題名'] ?? '';
  if (storedTitle && storedTitle !== title) return undefined;
  return tb;
};
// 点検 R2：D1 が第3の判定者の「対応表なし」を上書きした法律のうち、業種の割り当てを一次情報で確かめて保留に落としたもの（理由つき）。
const R2_HOLDS = 'data/derived/bill-triage-v2/r2-holds.csv';
const r2Holds = new Map(existsSync(new URL(R2_HOLDS, root)) ? batch.parseCsv(read(R2_HOLDS)).map(r => [r.id, r]) : []);
const compare = id => version === 'v2'
  ? agreement.compareTriage(id, line1ById.get(id), line2ById.get(id), enforcement.get(id)['題名'], currentTiebreak(id), r2Holds.get(id))
  : agreement.compareTriage(id, line1ById.get(id), line2ById.get(id));
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
    const ag = compare(e.id);
    return !(ag.agreed && (ag.resolved ?? ag.line1).verdict === '評価対象外');
  }).map(e => {
    const a = line1ById.get(e.id), b = line2ById.get(e.id);
    const res = compare(e.id).resolved;
    const use = res ? { field: res.field, indicator: res.indicator } : a?.['結果'] === '評価対象' ? { field: a['分野'], indicator: a['指標'] }
      : b?.['系統2_判定'] === '評価対象' ? { field: b['系統2_分野'], indicator: b['系統2_指標'] }
      : { field: a?.['分野'] ?? b?.['系統2_分野'] ?? '', indicator: a?.['指標'] ?? b?.['系統2_指標'] ?? '' };
    const referenceSource = res ? (res.field === a?.['分野'] && res.indicator === a?.['指標'] ? '系統1' : '系統2') : a?.['結果'] === '評価対象' ? '系統1'
      : b?.['系統2_判定'] === '評価対象' ? '系統2' : a ? '系統1' : b ? '系統2' : '入力';
    return { id: e.id, title: e['題名'], ...use, referenceSource, start: e['施行日'].trim() };
  });
  agreementPath = 'data/derived/bill-triage-v2/agreement.csv';
}
const triage = laws;
const lawIds = l => l.map(x => x.id);

const map = batch.indicatorMapFor('v2');
const unknown = [...new Set(triage.filter(r => compare(r.id).agreed).map(r => r.indicator))].filter(i => !map.some(m => m.indicator === i));
if (unknown.length) throw new Error(`対応表にない指標: ${unknown.join(', ')}`);

// 一致の表は、v2 では施行日のある全行（両系統が評価対象外で一致した行も含む）。影響の判定に回るのは laws だけ。
const agreementIds = version === 'v2' ? [...enforcement.keys()] : lawIds(laws);
const agreementAll = new Map(agreementIds.map(id => [id, compare(id)]));
const agreements = agreementAll;
const results = laws.map(law => agreement.holdByTriage(batch.evaluateLaw(tables, law, map), agreements.get(law.id), law.referenceSource));
const out = new URL(derived('impact'), root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('indicator-map.csv', out), batch.toCsv(batch.MAP_HEADER, map.map(batch.mapRow)));
writeFileSync(new URL('impact.csv', out), batch.toCsv(batch.IMPACT_HEADER, results.map(batch.impactRow)));
writeFileSync(new URL(agreementPath, root), batch.toCsv(agreement.TRIAGE_AGREEMENT_HEADER, agreementIds.map(id => agreement.triageAgreementRow(enforcement.get(id)['題名'], agreementAll.get(id)))));

const count = (key, f = v => v) => results.reduce((m, r) => m.set(f(r[key]), (m.get(f(r[key])) ?? 0) + 1), new Map());
console.log(`振り分け ${version}：影響の判定に回す ${laws.length} 本。振り分けの2系統の一致 ${[...agreements.values()].filter(a => a.agreed).length}/${agreementIds.length}`);
console.log('判定:', Object.fromEntries(count('verdict')));
console.log('国際比較:', Object.fromEntries(count('cross', v => v.replace(/（.*$/, ''))));
