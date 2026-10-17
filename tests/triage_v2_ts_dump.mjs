// tests/test_triage_v2.py が使う補助：標準入力の JSON（[題名, 種類, 分野] の配列）に app/src/indicator-pick.ts の triageV2 を当てて、結果を JSON で返す。
import { readFileSync } from 'node:fs';

const pick = await import(new URL('../app/src/indicator-pick.ts', import.meta.url).href);
const inputs = JSON.parse(readFileSync(0, 'utf8'));
const out = inputs.map(([title, kind, field]) => {
  const t = pick.triageV2({ title, kind, field });
  return [t.verdict, t.kind, t.field, t.indicator, t.rules.join('／'), t.reason];
});
process.stdout.write(JSON.stringify(out));
