// loss-v1：impact-v1 で段階2以上になった法律に loss-rule-v1 をかけ、data/derived/loss-v1/loss.csv に書き出す。
// 実行：cd app && node scripts/run-loss-v1.mjs （Node 22.18 以降。型注釈は Node が取り除く）
// 損失額の計算は app/src/loss-rule.ts だけにあり、ここでは読み書きだけをする。人物・採決・役職のデータは読まない。
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const impact = await import('../src/impact-batch.ts');
const loss = await import('../src/loss-batch.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv')) {
    tables.set(`${dir}/${name}`, impact.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const impactRows = impact.parseCsv(read('data/derived/impact-v1/impact.csv'));
const rows = loss.evaluateLosses(tables, impactRows);
const out = new URL('data/derived/loss-v1/', root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('loss.csv', out), impact.toCsv(loss.LOSS_HEADER, rows.map(loss.lossRow)));

console.log(`impact-v1 ${impactRows.length} 本のうち段階2以上 ${rows.length} 本`);
for (const r of rows) {
  const m = r.result?.lossYen;
  const amount = m ? `${(m.median / 1e12).toFixed(2)}兆円（${(m.low / 1e12).toFixed(2)}〜${(m.high / 1e12).toFixed(2)}）${r.result.years}年` : '保留';
  console.log([r.law.id, r.law.indicator, r.group, r.built?.reference ? '参考' : '', amount, r.result?.reason ?? ''].join(' | '));
}
