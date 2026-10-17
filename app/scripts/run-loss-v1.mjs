// loss-v1：impact-v1 で段階2以上になった法律に loss-rule-v1 をかけ、data/derived/loss-v1/loss.csv に書き出す。
// 実行：cd app && node scripts/run-loss-v1.mjs --triage v1|v2（既定v2。v2出力は -triage-v2 接尾辞で分離）
// 損失額の計算は app/src/loss-rule.ts だけにあり、ここでは読み書きだけをする。人物・採決・役職のデータは読まない。
import { triagePaths } from './triage-paths.mjs';
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const impact = await import('../src/impact-batch.ts');
const loss = await import('../src/loss-batch.ts');

const { version, derived } = triagePaths();
const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats', 'gap-stats', 'oecd-industry']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv' && n !== 'status.csv')) {
    tables.set(`${dir}/${name}`, impact.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const impactRows = impact.parseCsv(read(`${derived('impact')}impact.csv`));
const rows = loss.evaluateLosses(tables, impactRows, undefined, { includeStage1: version === 'v2' });
const out = new URL(derived('loss'), root);
mkdirSync(out, { recursive: true });
writeFileSync(new URL('loss.csv', out), impact.toCsv(loss.LOSS_HEADER, rows.map(loss.lossRow)));

console.log(`振り分け ${version}：impact-v1 ${impactRows.length} 本のうち段階2以上と参考の段階1 ${rows.length} 本`);
for (const r of rows) {
  const m = r.result?.lossYen;
  const amount = m ? `${(m.median / 1e12).toFixed(2)}兆円（${(m.low / 1e12).toFixed(2)}〜${(m.high / 1e12).toFixed(2)}）${r.result.years}年` : '保留';
  console.log([r.law.id, r.law.indicator, r.group, r.built?.reference || r.stage1Reference ? '参考' : '', amount, r.result?.reason ?? ''].join(' | '));
}
