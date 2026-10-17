// allocation-v1：法律ごとの額（publish.csv）を、関与の一覧（involvements.csv）の算入行に allocateLoss で按分する。
// 実行：cd app && node scripts/run-allocation-v1.mjs --involvements <csv> --publish <publish.csv> --loss <loss.csv> --laws <ID,ID,...> --out-dir <dir> [--aggregate <json>]
// 人物名を含む入出力は非公開の作業フォルダに置く。--aggregate には人物名を含まない集計だけを書く（docs/reports/allocation-v1.md の元）。
import { register } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

register('./ts-extension-hook.mjs', import.meta.url);
const { parseCsv, toCsv } = await import('../src/impact-batch.ts');
const A = await import('../src/allocation-batch.ts');

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, x, i, xs) => (x.startsWith('--') ? [...acc, [x.slice(2), xs[i + 1]]] : acc), []));
for (const k of ['involvements', 'publish', 'loss', 'laws', 'out-dir']) if (!args[k]) throw new Error(`--${k} が必要です`);
const read = p => parseCsv(readFileSync(p, 'utf8'));
const csv = (header, objs) => toCsv(header, objs.map(o => header.map(h => String(o[h] ?? ''))));

const wantAll = args.laws.split(',');
const publish = new Map(read(args.publish).map(r => [r.id, r]));
const lossRows = new Map(read(args.loss).map(r => [r.id, r]));
const allLaws = wantAll.map(id => {
  const p = publish.get(id), l = lossRows.get(id);
  if (!p || !l) throw new Error(`${id} が publish.csv か loss.csv にありません`);
  const amount = A.parseAmount(p['損失または便益']);
  if (!amount) throw new Error(`${id} の額を読めません`);
  const side = p['側'].startsWith('国士側') ? 'benefit' : 'loss';
  if ((side === 'benefit') !== (amount.median < 0)) throw new Error(`${id} の側と額の符号が合いません`);
  return { lawId: id, title: p['題名'], side, publishable: p['公開可否'] === '公開可', reference: l['参考フラグ'] === '参考', group: l['観測グループ'] ?? '', amount,
    rule: p['判定表の行'], lossCsvAmount: A.parseAmount(l['損失または便益の額'] ?? '') };
});
// 参考の行（貸出残高・段階1）は配分しない。
const laws = A.allocatable(allLaws);
const want = laws.map(l => l.lawId);
for (const l of allLaws) if (l.reference) console.log(`配分しない（参考）：${l.lawId}`);

const invRows = read(args.involvements);
const byLaw = new Map();
for (const r of invRows) {
  if (r['算入'] !== 'はい' || !want.includes(r['法律ID'])) continue;
  if (!byLaw.has(r['法律ID'])) byLaw.set(r['法律ID'], []);
  byLaw.get(r['法律ID']).push({ personId: r['氏名'], action: r['行動'], position: r['立場区分'], evidenceUrl: r['証拠URL'] });
}

const rows = A.allocateAll(laws, byLaw);
const totals = A.lawTotals(laws, rows);
const persons = A.personTotals(laws, rows);
const sens = new Map(A.rankSensitivity(persons).map(x => [x.personId, x]));
const lawOf = new Map(laws.map(l => [l.lawId, l]));
const sideLabel = s => (s === 'benefit' ? '国士側（貢献）' : '国賊側（悪影響）');

// 最大の行動と立場（基準の重みで最大の組）を法律・人ごとに残す。
const AW = { decide: 5, amend: 4, chair: 3, question: 2, vote: 1 }, PW = { prime_minister: 3, minister_or_party_exec: 2, vice_minister_or_chair: 1.5, other: 1 };
const best = new Map();
for (const [law, inv] of byLaw) for (const v of inv) {
  if (!/^https?:\/\//.test(v.evidenceUrl)) continue;
  const k = `${law}|${v.personId}`, w = AW[v.action] * PW[v.position];
  if (!best.has(k) || best.get(k).w < w) best.set(k, { w, action: v.action, position: v.position });
}

const out = args['out-dir'];
mkdirSync(out, { recursive: true });
const BY_LAW = ['法律ID', '題名', '側', '公開可否', '判定表の行', '観測グループ', '変種', '帰属率', '氏名', '最大の行動', '立場区分', '重み',
  '配分_中央値', '配分_第1四分位', '配分_第3四分位', '符号'];
writeFileSync(join(out, 'by-law.csv'), csv(BY_LAW, rows.map(r => {
  const l = lawOf.get(r.lawId), b = best.get(`${r.lawId}|${r.personId}`);
  return { 法律ID: r.lawId, 題名: l.title, 側: sideLabel(l.side), 公開可否: l.publishable ? '公開可' : '公開不可', 判定表の行: l.rule, 観測グループ: l.group,
    変種: A.VARIANT_LABEL[r.variant], 帰属率: String(r.rate), 氏名: r.personId, 最大の行動: b?.action ?? '', 立場区分: b?.position ?? '', 重み: String(r.weight),
    配分_中央値: String(r.share.median), 配分_第1四分位: String(r.share.low), 配分_第3四分位: String(r.share.high), 符号: l.side === 'benefit' ? '負は便益（貢献）' : '正は損失' };
})));

const TOT = ['法律ID', '題名', '側', '公開可否', '観測グループ', '変種', '帰属率', '人数', '額_中央値', '額_第1四分位', '額_第3四分位',
  '帰属_中央値', '帰属_第1四分位', '帰属_第3四分位', '未帰属_中央値', '未帰属_第1四分位', '未帰属_第3四分位'];
writeFileSync(join(out, 'by-law-totals.csv'), csv(TOT, totals.map(t => {
  const l = lawOf.get(t.lawId);
  return { 法律ID: t.lawId, 題名: l.title, 側: sideLabel(l.side), 公開可否: l.publishable ? '公開可' : '公開不可', 観測グループ: l.group, 変種: A.VARIANT_LABEL[t.variant],
    帰属率: String(t.rate), 人数: String(t.persons), 額_中央値: String(l.amount.median), 額_第1四分位: String(l.amount.low), 額_第3四分位: String(l.amount.high),
    帰属_中央値: String(t.attributed.median), 帰属_第1四分位: String(t.attributed.low), 帰属_第3四分位: String(t.attributed.high),
    未帰属_中央値: String(t.unattributed.median), 未帰属_第1四分位: String(t.unattributed.low), 未帰属_第3四分位: String(t.unattributed.high) };
})));

// 人ごと：基準の重みで帰属率0.3/0.5/0.7、行動重視・立場重視は0.5。
const pick = (v, rate) => new Map(persons.filter(p => p.variant === v && p.rate === rate).map(p => [p.personId, p]));
const cols = [['base', 0.3, '基準0.3'], ['base', 0.5, '基準0.5'], ['base', 0.7, '基準0.7'], ['action_only', 0.5, '行動重視0.5'], ['position_only', 0.5, '立場重視0.5']];
const maps = cols.map(([v, r]) => pick(v, r));
const BY_PERSON = ['氏名', '関与した法律', '最大の行動（法律別）', '公開不可の法律', '公開不可への依存', '同一観測グループの重複',
  ...cols.flatMap(([, , n]) => [`${n}_損失_中央値`, `${n}_損失_第1四分位`, `${n}_損失_第3四分位`, `${n}_貢献_中央値`, `${n}_貢献_低`, `${n}_貢献_高`, `${n}_純額_中央値`, `${n}_純額_低`, `${n}_純額_高`]),
  '基準0.5_公開可の法律のみの純額', '順位_基準0.5', '順位_行動重視0.5', '順位_立場重視0.5', '順位の最大変動', '順位変動5以上'];
const base = maps[1];
const personRows = [...base.values()].sort((a, b) => a.net.median - b.net.median || a.personId.localeCompare(b.personId)).map(p => {
  const s = sens.get(p.personId);
  const row = { 氏名: p.personId, 関与した法律: [...p.laws].sort().join('／'),
    '最大の行動（法律別）': [...p.laws].sort().map(id => `${id}:${best.get(`${id}|${p.personId}`)?.action}×${best.get(`${id}|${p.personId}`)?.position}`).join('／'),
    公開不可の法律: [...p.nonPublishableLaws].sort().join('／'), 公開不可への依存: p.nonPublishableLaws.length ? (p.nonPublishableLaws.length === p.laws.length ? 'すべて公開不可' : '一部公開不可') : 'なし',
    同一観測グループの重複: p.overlappingGroups.join('／'),
    '基準0.5_公開可の法律のみの純額': String(p.netPublishableMedian), '順位_基準0.5': String(s.base), '順位_行動重視0.5': String(s.actionOnly), '順位_立場重視0.5': String(s.positionOnly),
    順位の最大変動: String(s.maxMove), 順位変動5以上: s.flagged ? '印' : '' };
  cols.forEach(([, , n], i) => {
    const q = maps[i].get(p.personId);
    Object.assign(row, { [`${n}_損失_中央値`]: q.loss.median, [`${n}_損失_第1四分位`]: q.loss.low, [`${n}_損失_第3四分位`]: q.loss.high,
      [`${n}_貢献_中央値`]: q.credit.median, [`${n}_貢献_低`]: q.credit.low, [`${n}_貢献_高`]: q.credit.high,
      [`${n}_純額_中央値`]: q.net.median, [`${n}_純額_低`]: q.net.low, [`${n}_純額_高`]: q.net.high });
  });
  for (const k of Object.keys(row)) row[k] = String(row[k]);
  return row;
});
writeFileSync(join(out, 'by-person.csv'), csv(BY_PERSON, personRows));

// 人物名を含まない集計。
if (args.aggregate) {
  const agg = { ruleVersion: 'allocation-v1', laws: laws.map(l => {
    const inv = invRows.filter(r => r['法律ID'] === l.lawId);
    const counted = byLaw.get(l.lawId) ?? [];
    const maxAction = {}, maxPosition = {};
    for (const [k, b] of best) if (k.startsWith(`${l.lawId}|`)) { maxAction[b.action] = (maxAction[b.action] ?? 0) + 1; maxPosition[b.position] = (maxPosition[b.position] ?? 0) + 1; }
    const excluded = {};
    for (const r of inv) if (r['算入'] !== 'はい') { const k = `${r['行動']}：${r['除外理由'].replace(/（A:.*$/, '（不一致）')}`; excluded[k] = (excluded[k] ?? 0) + 1; }
    return { lawId: l.lawId, title: l.title, side: l.side, publishable: l.publishable, group: l.group, amount: l.amount, lossCsvAmount: l.lossCsvAmount,
      involvementRows: inv.length, countedRows: counted.length, persons: new Set(counted.map(v => v.personId)).size, maxAction, maxPosition, excluded,
      totals: totals.filter(t => t.lawId === l.lawId).map(t => ({ variant: t.variant, rate: t.rate, persons: t.persons, attributed: t.attributed, unattributed: t.unattributed })) };
  }), persons: base.size, flaggedRankMoves: [...sens.values()].filter(s => s.flagged).length,
    personsBySide: { lossOnly: [...base.values()].filter(p => p.credit.median === 0).length, creditOnly: [...base.values()].filter(p => p.loss.median === 0).length,
      both: [...base.values()].filter(p => p.credit.median !== 0 && p.loss.median !== 0).length },
    dependence: { allNonPublishable: personRows.filter(r => r.公開不可への依存 === 'すべて公開不可').length, partlyNonPublishable: personRows.filter(r => r.公開不可への依存 === '一部公開不可').length,
      none: personRows.filter(r => r.公開不可への依存 === 'なし').length },
    overlappingGroupPersons: personRows.filter(r => r.同一観測グループの重複).length };
  writeFileSync(args.aggregate, JSON.stringify(agg, null, 1));
}
console.log(`allocation-v1：${laws.length} 本、配分 ${rows.length} 行、人数 ${base.size}`);
