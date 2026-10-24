// 旧法（第77〜141回）の影響の判定：施行日があり、振り分けが「一致」で、分野が8分野のどれかの法律だけを impact-rule-v1 にかけ、
// data/derived/impact-old/impact.csv に書き出す。判定ロジックは app/src/impact-batch.ts と indicator-pick.ts にだけあり、ここでは読み書きだけをする。
// 実行：cd app && node scripts/run-impact-old.mjs
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const batch = await import('../src/impact-batch.ts');
const pick = await import('../src/indicator-pick.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats', 'gap-stats', 'r3-series']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv' && n !== 'status.csv')) {
    tables.set(`${dir}/${name}`, batch.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const triage = new Map(batch.parseCsv(read('data/derived/bill-triage-old/triage.csv')).map(r => [r.id, r]));
const enforcement = batch.parseCsv(read('data/acquired/enforcement-dates-old/enforcement_old.csv')).filter(r => r['施行日'].trim() !== '');

// 一致（ADR 0007：2系統が一致したものだけ採る。A・B が一致し、系統2の分野も同じ）で、分野が8分野のどれか。分野が対応表なしの法律は市場の経路がなく、影響の判定に回さない。
const laws = enforcement.flatMap(e => {
  const t = triage.get(e['法令番号']);
  if (!t || t['結果'] !== '一致' || t['系統2_分野'] !== t['分野'] || !pick.FIELDS.includes(t['分野'])) return [];
  const p = pick.pickIndicator(t['分野'], e['題名']);
  return [{ id: t.id, title: e['題名'], field: t['分野'], indicator: p.indicator, start: e['施行日'].trim() }];
});

const results = laws.map(law => batch.evaluateLaw(tables, law));
const out = new URL('data/derived/impact-old/', root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('impact.csv', out), batch.toCsv(batch.IMPACT_HEADER, results.map(batch.impactRow)));

const count = {};
for (const r of results) count[r.verdict] = (count[r.verdict] ?? 0) + 1;
console.log(`旧法：影響の判定に回す ${laws.length} 本`, count);
