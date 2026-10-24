// tests/test_triage_v2.py が使う補助：標準入力の JSON（[題名, 系統1, 系統2] の配列。系統は {verdict, field, indicator, kind}）に
// app/src/line-agreement.ts の resolveTriageDiff を当てて、[規則, 判定, 分野, 指標, 理由] の配列を JSON で返す。
import { readFileSync } from 'node:fs';
import { register } from 'node:module';

register('../app/scripts/ts-extension-hook.mjs', import.meta.url);

const mod = await import(new URL('../app/src/line-agreement.ts', import.meta.url).href);
const inputs = JSON.parse(readFileSync(0, 'utf8'));
const out = inputs.map(([title, l1, l2]) => {
  const r = mod.resolveTriageDiff(title, l1, l2);
  return [r.rule, r.line?.verdict ?? '', r.line?.field ?? '', r.line?.indicator ?? '', r.reason];
});
process.stdout.write(JSON.stringify(out));
