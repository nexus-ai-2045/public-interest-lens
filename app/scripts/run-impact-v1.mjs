// impact-v1：評価対象で施行日のある法律を impact-rule-v1 にかけ、data/derived/impact-v1/ に書き出す。
// 実行：cd app && node scripts/run-impact-v1.mjs （Node 22.18 以降。型注釈は Node が取り除く）
// 判定ロジックは app/src/impact-rule.ts だけにあり、ここでは読み書きだけをする。
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const batch = await import('../src/impact-batch.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv')) {
    tables.set(`${dir}/${name}`, batch.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const triage = batch.parseCsv(read('data/derived/bill-triage-v1/triage.csv')).filter(r => r['結果'] === '評価対象');
const enforcement = new Map(batch.parseCsv(read('data/acquired/enforcement-dates/enforcement.csv')).filter(r => r['施行日'].trim() !== '').map(r => [r.id, r]));
const laws = triage.filter(r => enforcement.has(r.id)).map(r => ({ id: r.id, title: enforcement.get(r.id)['題名'], field: r['分野'], indicator: r['指標'], start: enforcement.get(r.id)['施行日'].trim() }));

const unknown = [...new Set(triage.map(r => r['指標']))].filter(i => !batch.INDICATOR_MAP.some(m => m.indicator === i));
if (unknown.length) throw new Error(`対応表にない指標: ${unknown.join(', ')}`);

const results = laws.map(law => batch.evaluateLaw(tables, law));
const out = new URL('data/derived/impact-v1/', root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('indicator-map.csv', out), batch.toCsv(batch.MAP_HEADER, batch.INDICATOR_MAP.map(batch.mapRow)));
writeFileSync(new URL('impact.csv', out), batch.toCsv(batch.IMPACT_HEADER, results.map(batch.impactRow)));

const count = (key, f = v => v) => results.reduce((m, r) => m.set(f(r[key]), (m.get(f(r[key])) ?? 0) + 1), new Map());
console.log(`評価対象 ${triage.length} 本のうち施行日あり ${laws.length} 本`);
console.log('判定:', Object.fromEntries(count('verdict')));
console.log('国際比較:', Object.fromEntries(count('cross', v => v.replace(/（.*$/, ''))));
