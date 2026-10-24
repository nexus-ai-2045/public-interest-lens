// docs/計算式.md を app/src/method-spec.ts（計算方法の仕様の式の正本）から作る。
// 使い方: cd app && node scripts/build_formula_doc.mjs [--check]
// --check は書き込まず、ファイルが正本と一致しなければ終了コード1で止まる（テストと毎朝の更新で使う）。
import { register } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

register('./ts-extension-hook.mjs', import.meta.url);
const { specMarkdown } = await import('../src/method-spec.ts');
const out = join(import.meta.dirname, '..', '..', 'docs', '計算式.md');
const text = specMarkdown() + '\n';
if (process.argv.includes('--check')) {
  let current = '';
  try { current = readFileSync(out, 'utf8'); } catch { /* 無ければ不一致 */ }
  if (current !== text) { console.error('docs/計算式.md が app/src/method-spec.ts と一致しません。node scripts/build_formula_doc.mjs で作り直してください'); process.exit(1); }
  console.log('docs/計算式.md は正本と一致');
} else {
  writeFileSync(out, text);
  console.log(`書きました: docs/計算式.md（${text.length}文字）`);
}
