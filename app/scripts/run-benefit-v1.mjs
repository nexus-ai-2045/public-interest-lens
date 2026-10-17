// benefit-v1：loss-v1 の法律に benefit-rule-v1.1 をかけ、data/derived/benefit-v1/ と data/derived/publish-v1/ に書き出す。
// 実行：cd app && node scripts/run-benefit-v1.mjs （Node 22.18 以降。型注釈は Node が取り除く）
// 判定は app/src/benefit-rule.ts・impact-rule.ts・loss-rule.ts だけにあり、ここでは読み書きだけをする。人物・採決・役職のデータは読まない。
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const impact = await import('../src/impact-batch.ts');
const benefit = await import('../src/benefit-batch.ts');

const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats', 'oecd-industry', 'benefit-data']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv' && !n.endsWith('_status.csv'))) {
    tables.set(`${dir}/${name}`, impact.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const impactRows = impact.parseCsv(read('data/derived/impact-v1/impact.csv'));
const purposes = impact.parseCsv(read('data/acquired/law-purposes/purposes.csv'));
const results = benefit.evaluateBenefits(tables, impactRows, purposes);
const groups = benefit.benefitGroups(results);

const outB = new URL('data/derived/benefit-v1/', root);
const outP = new URL('data/derived/publish-v1/', root);
mkdirSync(outB, { recursive: true });
mkdirSync(outP, { recursive: true });
writeFileSync(new URL('classification.csv', outB), impact.toCsv(benefit.CLASSIFICATION_HEADER, results.map(benefit.classificationRow)));
writeFileSync(new URL('benefit.csv', outB), impact.toCsv(benefit.BENEFIT_HEADER, results.flatMap(r => benefit.benefitRows(r, groups))));
writeFileSync(new URL('publish.csv', outP), impact.toCsv(benefit.PUBLISH_HEADER, results.map(benefit.publishRow)));

const agreed = results.filter(r => r.classification.agreed).length;
console.log(`loss-v1 ${results.length} 本。目的の分類の2系統の一致 ${agreed}/${results.length}`);
for (const r of results) {
  const full = benefit.rejudgeImpact(tables, r.row.law.indicator, r.row.law.start, false);
  const n = r.decision.net;
  console.log([r.row.law.id, r.row.law.direction ?? '-', r.decision.row, r.decision.publishable ? (r.decision.lowerBound ? '公開可（下限）' : '公開可') : '公開不可',
    n ? `${(n.median / 1e12).toFixed(2)}兆円（${(n.low / 1e12).toFixed(2)}〜${(n.high / 1e12).toFixed(2)}）` : '',
    `元の窓の再判定=${full ? `${full.stage}/${full.direction}` : 'なし'}（impact.csv=${r.row.law.stage}/${r.row.law.direction}）`,
    r.decision.reason.slice(0, 120)].join(' | '));
}
