// benefit-v1：loss-v1 の法律に benefit-rule-v1.1 をかけ、data/derived/benefit-v1/ と data/derived/publish-v1/ に書き出す。
// 実行：cd app && node scripts/run-benefit-v1.mjs --triage v1|v2（既定v2。v2出力は -triage-v2 接尾辞で分離）
// 判定は app/src/benefit-rule.ts・impact-rule.ts・loss-rule.ts だけにあり、ここでは読み書きだけをする。人物・採決・役職のデータは読まない。
import { triagePaths } from './triage-paths.mjs';
import { register } from 'node:module';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';

register('./ts-extension-hook.mjs', import.meta.url);
const impact = await import('../src/impact-batch.ts');
const benefit = await import('../src/benefit-batch.ts');
const agreement = await import('../src/line-agreement.ts');

const { version, derived } = triagePaths();
const root = new URL('../../', import.meta.url);
const read = rel => readFileSync(new URL(rel, root), 'utf8');

const tables = new Map();
for (const dir of ['domestic-stats', 'intl-stats', 'more-stats', 'gap-stats', 'oecd-industry', 'benefit-data']) {
  for (const name of readdirSync(new URL(`data/acquired/${dir}/`, root)).filter(n => n.endsWith('.csv') && n !== 'manifest.csv' && n !== 'status.csv' && !n.endsWith('_status.csv'))) {
    tables.set(`${dir}/${name}`, impact.parseCsv(read(`data/acquired/${dir}/${name}`)));
  }
}

const impactRows = impact.parseCsv(read(`${derived('impact')}impact.csv`));
const purposes = impact.parseCsv(read('data/acquired/law-purposes/purposes.csv'));
// 設計決定0007：系統2（系統1を見ずに別のセッションが付けた分類）と一致したものだけ採用する。
const line2 = agreement.parseBenefitLine2(impact.parseCsv(read('data/derived/benefit-v1-line2/labels.csv')));
const results = benefit.evaluateBenefits(tables, impactRows, purposes, line2, { includeStage1: version === 'v2' });
const groups = benefit.benefitGroups(results);

const outB = new URL(derived('benefit'), root);
const outP = new URL(derived('publish'), root);
mkdirSync(outB, { recursive: true });
mkdirSync(outP, { recursive: true });
writeFileSync(new URL('classification.csv', outB), impact.toCsv(benefit.CLASSIFICATION_HEADER, results.map(benefit.classificationRow)));
writeFileSync(new URL('agreement.csv', outB), impact.toCsv(agreement.AGREEMENT_HEADER, results.map(r => agreement.agreementRow(r.row.law.id, r.row.law.title, r.agreement))));
writeFileSync(new URL('benefit.csv', outB), impact.toCsv(benefit.BENEFIT_HEADER, results.flatMap(r => benefit.benefitRows(r, groups))));
writeFileSync(new URL('publish.csv', outP), impact.toCsv(benefit.PUBLISH_HEADER, results.map(benefit.publishRow)));

const agreed = results.filter(r => r.line1.agreed).length;
const count = s => results.filter(r => r.agreement.status === s).length;
console.log(`振り分け ${version}：loss-v1 ${results.length} 本。系統1の中（A・B）の一致 ${agreed}/${results.length}。系統1と系統2：一致 ${count('一致')}、不一致 ${count('不一致')}、系統1が保留 ${count('系統1が保留')}、系統2なし ${count('系統2なし')}`);
for (const r of results) {
  const full = benefit.rejudgeImpact(tables, r.row.law.indicator, r.row.law.start, false);
  const n = r.decision.net;
  console.log([r.row.law.id, r.row.law.direction ?? '-', r.decision.row, r.decision.publishable ? (r.decision.lowerBound ? '公開可（下限）' : '公開可') : '公開不可',
    n ? `${(n.median / 1e12).toFixed(2)}兆円（${(n.low / 1e12).toFixed(2)}〜${(n.high / 1e12).toFixed(2)}）` : '',
    `元の窓の再判定=${full ? `${full.stage}/${full.direction}` : 'なし'}（impact.csv=${r.row.law.stage}/${r.row.law.direction}）`,
    r.decision.reason.slice(0, 120)].join(' | '));
}
