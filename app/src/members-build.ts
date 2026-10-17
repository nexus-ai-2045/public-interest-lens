/**
 * 公開用の議員ページのデータ（public-members/v1）を作る。
 * 按分は allocation-batch.ts（中は loss-rule.ts の allocateLoss）をそのまま使い、ここでは入力の整形と表示用の並べ替えだけをする。
 * 額が出た法律（参考の行を除く）に関与の記録があれば、自動で配分に入る。人物名はデータとして受け取るだけで、このファイルには書かない。
 */
import { allocateAll, BASE_RATE, parseAmount, personTotals, rankSensitivity, RATES, type Law, type Range } from './allocation-batch';
import { parseCsv } from './impact-batch';
import { ACTION_WEIGHT, POSITION_WEIGHT, type Action, type Involvement, type Position } from './loss-rule';

export const ACTION_LABEL: Record<Action, string> = { decide: '提出・決定', amend: '修正案の提出', chair: '委員長として採決を主宰', question: '質疑（法案を支持）', vote: '参議院本会議で賛成' };
export const POSITION_LABEL: Record<Position, string> = { prime_minister: '内閣総理大臣', minister_or_party_exec: '大臣', vice_minister_or_chair: '副大臣・政務官・官房副長官・本件の委員長', other: 'その他' };

/** publish.csv の判定表の行から、法律の額に付ける確かさの印。 */
export function confidenceLabel(row: string, amountText: string): string {
  if (row === 'R3') return 'コロナ期と重なる（損失の窓が新型コロナの時期と重なり、分けて測れない）';
  if (row === 'R4') return '便益を減らしうる項目が未測定（純額は確定していない）';
  if (amountText.startsWith('下限')) return '下限（未測定の便益を0として数えた）';
  return '公開判定どおり';
}

export type MemberEvidence = { action: Action; actionLabel: string; title: string; house: string; date: string; url: string };
export type MemberLaw = {
  lawId: string;
  side: Law['side'];
  action: Action;
  position: Position;
  /** 行動の重み × 立場の重み（その法律で最大の組）。 */
  weight: number;
  /** 損失は国賊側の正の額、便益は国士側の正の額（帰属率0.5の基準）。 */
  share: Range;
  evidence: MemberEvidence[];
};
export type PublicMember = {
  name: string;
  rank: number;
  /** 純額 = 貢献 − 損失。負が国賊側、正が国士側。 */
  net: Range;
  loss: Range;
  credit: Range;
  sensitivity: { actionOnlyRank: number; positionOnlyRank: number; maxMove: number; flagged: boolean; rate03Net: number; rate07Net: number };
  overlappingGroups: string[];
  laws: MemberLaw[];
};
export type PublicMemberLaw = {
  id: string; title: string; side: Law['side']; amount: Range; publishable: boolean; confidence: string; judgement: string; reason: string;
  group: string; persons: number; totalWeight: number; attributed: Range; source: string;
};
export type PublicMembers = {
  schema: 'public-members/v1';
  rules: string[];
  rate: number;
  rates: number[];
  weights: { action: Record<Action, number>; position: Record<Position, number> };
  laws: PublicMemberLaw[];
  members: PublicMember[];
  counts: { members: number; loss: number; benefit: number; involvements: number; excluded: number };
};

const ACTIONS = Object.keys(ACTION_WEIGHT) as Action[];
const POSITIONS = Object.keys(POSITION_WEIGHT) as Position[];

export type MemberInputs = { involvements: string; publish: string; loss: string; enacted: string };

export function buildMembers(input: MemberInputs): PublicMembers {
  const publish = parseCsv(input.publish);
  const loss = new Map(parseCsv(input.loss).map(r => [r.id, r]));
  const enacted = new Map(parseCsv(input.enacted).map(r => [`${r['種別']}-${r['提出回次']}-${r['番号']}`, r]));
  const rows = parseCsv(input.involvements);
  for (const r of rows) {
    if (!ACTIONS.includes(r['行動'] as Action) || !POSITIONS.includes(r['立場区分'] as Position)) throw new Error(`行動または立場が不明です: ${r['法律ID']} ${r['行動']} ${r['立場区分']}`);
    if (r['算入'] === 'はい' && !/^https:\/\/(kokkai\.ndl\.go\.jp|www\.sangiin\.go\.jp|www\.shugiin\.go\.jp)\//.test(r['証拠URL'])) throw new Error(`算入の行に一次資料の URL がありません: ${r['法律ID']}`);
  }
  const counted = rows.filter(r => r['算入'] === 'はい');
  const involvedLaws = new Set(counted.map(r => r['法律ID']));
  const laws: Law[] = [];
  const meta = new Map<string, { row: Record<string, string>; text: string }>();
  for (const p of publish) {
    const l = loss.get(p.id);
    const amount = parseAmount(p['損失または便益']);
    if (!l || !l['損失または便益の額'] || l['参考フラグ'] === '参考' || !amount || !involvedLaws.has(p.id)) continue;
    laws.push({ lawId: p.id, title: p['題名'], side: p['側'].startsWith('国士側') ? 'benefit' : 'loss', publishable: p['公開可否'] === '公開可', group: l['観測グループ'], amount });
    meta.set(p.id, { row: p, text: p['損失または便益'] });
  }
  const byLaw = new Map<string, Involvement[]>();
  for (const r of counted) {
    if (!meta.has(r['法律ID'])) continue;
    byLaw.set(r['法律ID'], [...(byLaw.get(r['法律ID']) ?? []), { personId: r['氏名'], action: r['行動'] as Action, position: r['立場区分'] as Position, evidenceUrl: r['証拠URL'] }]);
  }
  const allocation = allocateAll(laws, byLaw);
  const totals = personTotals(laws, allocation);
  const sens = new Map(rankSensitivity(totals).map(s => [s.personId, s]));
  const total = (variant: string, rate: number) => new Map(totals.filter(t => t.variant === variant && t.rate === rate).map(t => [t.personId, t]));
  const base = total('base', BASE_RATE), low = total('base', 0.3), high = total('base', 0.7);
  const baseRows = allocation.filter(r => r.variant === 'base' && r.rate === BASE_RATE);
  const lawOut: PublicMemberLaw[] = laws.map(law => {
    const { row, text } = meta.get(law.lawId)!;
    const mine = baseRows.filter(r => r.lawId === law.lawId);
    const sum = (k: keyof Range) => Math.abs(mine.reduce((s, r) => s + r.share[k], 0));
    const attributed = { low: Math.min(sum('low'), sum('high')), median: sum('median'), high: Math.max(sum('low'), sum('high')) };
    const amount = law.side === 'benefit' ? { low: -law.amount.high, median: -law.amount.median, high: -law.amount.low } : law.amount;
    const source = enacted.get(law.lawId)?.['経過URL'] ?? '';
    if (!source.startsWith('https://www.shugiin.go.jp/')) throw new Error(`議案の経過 URL がありません: ${law.lawId}`);
    return { id: law.lawId, title: law.title, side: law.side, amount: { low: Math.min(amount.low, amount.high), median: amount.median, high: Math.max(amount.low, amount.high) },
      publishable: law.publishable, confidence: confidenceLabel(row['判定表の行'], text), judgement: row['判定表の行'], reason: row['理由'], group: law.group,
      persons: mine.length, totalWeight: mine.reduce((s, r) => s + r.weight, 0), attributed, source };
  });
  const sideOf = new Map(laws.map(l => [l.lawId, l.side]));
  const members: PublicMember[] = [...base.values()].map(t => {
    const s = sens.get(t.personId)!;
    const mine = baseRows.filter(r => r.personId === t.personId).map(r => {
      const evidence = counted.filter(v => v['法律ID'] === r.lawId && v['氏名'] === t.personId)
        .map(v => ({ action: v['行動'] as Action, actionLabel: ACTION_LABEL[v['行動'] as Action], title: v['当時の肩書'], house: v['院'], date: v['日付'], url: v['証拠URL'] }))
        .sort((a, b) => ACTION_WEIGHT[b.action] - ACTION_WEIGHT[a.action] || a.date.localeCompare(b.date));
      const best = byLaw.get(r.lawId)!.filter(v => v.personId === t.personId)
        .reduce((a, b) => ACTION_WEIGHT[b.action] * POSITION_WEIGHT[b.position] > ACTION_WEIGHT[a.action] * POSITION_WEIGHT[a.position] ? b : a);
      const side = sideOf.get(r.lawId)!;
      const mag = [Math.abs(r.share.low), Math.abs(r.share.high)].sort((a, b) => a - b);
      return { lawId: r.lawId, side, action: best.action, position: best.position, weight: r.weight, share: { low: mag[0], median: Math.abs(r.share.median), high: mag[1] }, evidence };
    }).sort((a, b) => b.share.median - a.share.median);
    return { name: t.personId, rank: s.base, net: t.net, loss: t.loss, credit: t.credit,
      sensitivity: { actionOnlyRank: s.actionOnly, positionOnlyRank: s.positionOnly, maxMove: s.maxMove, flagged: s.flagged, rate03Net: low.get(t.personId)!.net.median, rate07Net: high.get(t.personId)!.net.median },
      overlappingGroups: t.overlappingGroups, laws: mine };
  }).sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
  return {
    schema: 'public-members/v1',
    rules: ['allocation-v1', 'loss-rule-v1', 'benefit-rule-v1.2'],
    rate: BASE_RATE,
    rates: RATES,
    weights: { action: ACTION_WEIGHT, position: POSITION_WEIGHT },
    laws: lawOut,
    members,
    counts: { members: members.length, loss: members.filter(m => m.net.median < 0).length, benefit: members.filter(m => m.net.median > 0).length,
      involvements: counted.filter(r => meta.has(r['法律ID'])).length, excluded: rows.filter(r => r['算入'] !== 'はい' && meta.has(r['法律ID'])).length },
  };
}
