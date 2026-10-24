// bill-triage-v2 の系統1：系統1の AI が付けた種類・分野（bill-triage-v1/triage.csv）に、指標の選び方 indicator-pick-v1 を当てて
// data/derived/bill-triage-v2/labels-line1.csv に書き出す。
// 実行：cd app && node scripts/run-triage-v2-line1.mjs （Node 22.18 以降。型注釈は Node が取り除く）
// A と B が割れて種類・分野が空の行は、第3の判定者（Haiku 2系統→Sonnet→Opus、bill-triage-v1/tiebreak.csv）の値で埋め、規則に TB を残す。
// 規則は app/src/indicator-pick.ts だけにあり、ここでは読み書きだけをする。範囲は施行日台帳（enforcement.csv）で施行日が入っている全ての行。台帳に後から行が足されても、triage.csv にある id なら自動で載る（日付の無い行は載らない）。
import { register } from 'node:module';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const batch = await import('../src/impact-batch.ts');
const pick = await import('../src/indicator-pick.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const triage = new Map(batch.parseCsv(read('data/derived/bill-triage-v1/triage.csv')).map(r => [r.id, r]));
const TIEBREAK = 'data/derived/bill-triage-v1/tiebreak.csv';
const tiebreak = new Map(existsSync(new URL(TIEBREAK, root)) ? batch.parseCsv(read(TIEBREAK)).map(r => [r.id, r]) : []);
const decided = value => value && value !== '保留';
const enforcement = batch.parseCsv(read('data/acquired/enforcement-dates/enforcement.csv')).filter(r => r['施行日'].trim() !== '');

const HEADER = ['id', '題名', '系統1_入力種類', '系統1_入力分野', '結果', '種類', '分野', '指標', '規則', '理由'];
const rows = enforcement.map(e => {
  const t = triage.get(e.id);
  if (!t) throw new Error(`triage.csv に ${e.id} が無い`);
  const tb = tiebreak.get(e.id);
  const kind = t['種類'] || (decided(tb?.['種類']) ? tb['種類'] : '');
  const field = t['分野'] || (decided(tb?.['分野']) ? tb['分野'] : '');
  const used = kind !== t['種類'] || field !== t['分野'];
  const out = pick.triageV2({ title: e['題名'], kind, field });
  const rules = used ? [...out.rules, 'TB'] : out.rules;
  // R2（2026-10-18、額の大きい法律の点検）：第3の判定者が決めた分野を D1 が別の分野に決め直したときは、その印を理由に残す（分野は D1 のまま）。
  const overridden = used && decided(tb?.['分野']) && out.field && out.field !== tb['分野'] ? `（R2：D1 が第3の判定者の分野「${tb['分野']}」を「${out.field}」に決め直した）` : '';
  const reason = used ? `${out.reason}／TB：A・B が割れた項目を第3の判定者が決定（${tb['決め方']}：${tb['理由']}）${overridden}` : out.reason;
  return [e.id, e['題名'], kind, field, out.verdict, out.kind, out.field, out.indicator, rules.join('／'), reason];
});

const dir = new URL('data/derived/bill-triage-v2/', root);
mkdirSync(dir, { recursive: true });
writeFileSync(new URL('labels-line1.csv', dir), batch.toCsv(HEADER, rows));
console.log(`bill-triage-v2 系統1: ${rows.length} 本`);
