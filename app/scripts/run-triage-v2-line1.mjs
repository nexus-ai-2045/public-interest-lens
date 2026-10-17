// bill-triage-v2 の系統1：系統1の AI が付けた種類・分野（bill-triage-v1/triage.csv）に、指標の選び方 indicator-pick-v1 を当てて
// data/derived/bill-triage-v2/labels-line1.csv に書き出す。
// 実行：cd app && node scripts/run-triage-v2-line1.mjs （Node 22.18 以降。型注釈は Node が取り除く）
// 規則は app/src/indicator-pick.ts だけにあり、ここでは読み書きだけをする。範囲は施行日を原文で確定できた法律（bill-triage-v1-line2 と同じ170本）。
import { register } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const batch = await import('../src/impact-batch.ts');
const pick = await import('../src/indicator-pick.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const triage = new Map(batch.parseCsv(read('data/derived/bill-triage-v1/triage.csv')).map(r => [r.id, r]));
const enforcement = batch.parseCsv(read('data/acquired/enforcement-dates/enforcement.csv')).filter(r => r['施行日'].trim() !== '');

const HEADER = ['id', '題名', '系統1_入力種類', '系統1_入力分野', '結果', '種類', '分野', '指標', '規則', '理由'];
const rows = enforcement.map(e => {
  const t = triage.get(e.id);
  if (!t) throw new Error(`triage.csv に ${e.id} が無い`);
  const out = pick.triageV2({ title: e['題名'], kind: t['種類'], field: t['分野'] });
  return [e.id, e['題名'], t['種類'], t['分野'], out.verdict, out.kind, out.field, out.indicator, out.rules.join('／'), out.reason];
});

const dir = new URL('data/derived/bill-triage-v2/', root);
mkdirSync(dir, { recursive: true });
writeFileSync(new URL('labels-line1.csv', dir), batch.toCsv(HEADER, rows));
console.log(`bill-triage-v2 系統1: ${rows.length} 本`);
