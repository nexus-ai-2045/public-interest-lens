/**
 * 公開用の議員ページのデータ（public-members/v2）を作る。
 * 配分は causal-allocation.ts（成立への寄与の Shapley 値）を使う。この人の行動が無ければ法律は成立したか、を投票のしくみで測り、法律の額をその割合で配る。
 * 額が出た法律（参考の行を除く）に関与の記録と参議院の投票の記録があれば、自動で配分に入る。人物名はデータとして受け取るだけで、このファイルには書かない。
 */
import { parseAmount, type Law, type Range } from './allocation-batch';
import { allocateLaw, CAUSAL_VARIANTS, ROLE_LABEL, type CausalRole, type CausalVariant, type LawGame } from './causal-allocation';
import { parseCsv } from './impact-batch';
import { ACTION_WEIGHT, POSITION_WEIGHT, type Action, type Position } from './loss-rule';

export const ACTION_LABEL: Record<Action, string> = { decide: '提出・決定', amend: '修正案の提出', chair: '委員長として採決を主宰', question: '質疑（法案を支持）', vote: '参議院本会議で賛成' };
export const POSITION_LABEL: Record<Position, string> = { prime_minister: '内閣総理大臣', minister_or_party_exec: '大臣', vice_minister_or_chair: '副大臣・政務官・官房副長官・本件の委員長', other: 'その他' };
export { ROLE_LABEL };

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
  /** この人が成立に効いた役割と、その割合（法律の額に対する比）。 */
  roles: Partial<Record<CausalRole, number>>;
  fraction: number;
  /** 損失は国賊側の正の額、便益は国士側の正の額。 */
  share: Range;
  /** 配分に入った行動（一次資料つき）。 */
  evidence: MemberEvidence[];
  /** 成立を左右しないため配らない行動（質疑・修正案・基準での委員長）。 */
  context: MemberEvidence[];
};
export type PublicMember = {
  name: string;
  rank: number;
  /** 純額 = 生んだ額 − 失わせた額。負が国賊側、正が国士側。 */
  net: Range;
  loss: Range;
  credit: Range;
  sensitivity: { chairVetoRank: number; chairVetoNet: number; maxMove: number; flagged: boolean };
  overlappingGroups: string[];
  laws: MemberLaw[];
};
export type PublicMemberLaw = {
  id: string; title: string; side: Law['side']; amount: Range; publishable: boolean; confidence: string; judgement: string; reason: string;
  group: string; persons: number; attributed: Range; source: string; enactedOn: string;
  game: {
    proposers: number; proposerKind: string; vetoShare: number; voteShare: number; yes: number; no: number; quota: number; voters: number;
    voteUrl: string; voteDate: string; chairs: number;
    /** つまみで画面側が計算し直すための名前の一覧。 */
    names: { proposers: string[]; voters: string[]; chairs: string[] };
    /** 衆議院の賛成会派（起立採決で個人の賛否が残らないので党に置く）。 */
    parties: string[]; party: Range; unidentified: Range;
  };
};
export type PublicMembers = {
  schema: 'public-members/v2';
  rules: string[];
  laws: PublicMemberLaw[];
  members: PublicMember[];
  counts: { members: number; loss: number; benefit: number; zero: number; involvements: number; context: number; excluded: number };
};

const ACTIONS = Object.keys(ACTION_WEIGHT) as Action[];
const POSITIONS = Object.keys(POSITION_WEIGHT) as Position[];
const ROLE_OF: Partial<Record<Action, CausalRole>> = { decide: 'proposer', vote: 'vote', chair: 'chair' };
export const RANK_MOVE_FLAG = 5;

export type MemberInputs = { involvements: string; publish: string; loss: string; enacted: string; votes: string };

const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });
const ordered = (r: Range): Range => ({ low: Math.min(r.low, r.high), median: r.median, high: Math.max(r.low, r.high) });
const magnitude = (r: Range): Range => ordered({ low: Math.abs(r.low), median: Math.abs(r.median), high: Math.abs(r.high) });

/** 「平成30年 4月18日」を 2018-04-18 に。 */
export function warekiDate(text: string): string {
  const m = /(平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日/.exec(text);
  if (!m) return '';
  const y = (m[2] === '元' ? 1 : Number(m[2])) + (m[1] === '平成' ? 1988 : 2018);
  return `${y}-${m[3].padStart(2, '0')}-${m[4].padStart(2, '0')}`;
}

export function buildMembers(input: MemberInputs): PublicMembers {
  const publish = parseCsv(input.publish);
  const loss = new Map(parseCsv(input.loss).map(r => [r.id, r]));
  const enacted = new Map(parseCsv(input.enacted).map(r => [`${r['種別']}-${r['提出回次']}-${r['番号']}`, r]));
  const votes = new Map(parseCsv(input.votes).map(r => [r['法律ID'], r]));
  const rows = parseCsv(input.involvements);
  for (const r of rows) {
    if (!ACTIONS.includes(r['行動'] as Action) || !POSITIONS.includes(r['立場区分'] as Position)) throw new Error(`行動または立場が不明です: ${r['法律ID']} ${r['行動']} ${r['立場区分']}`);
    if (r['算入'] === 'はい' && !/^https:\/\/(kokkai\.ndl\.go\.jp|www\.sangiin\.go\.jp|www\.shugiin\.go\.jp)\//.test(r['証拠URL'])) throw new Error(`算入の行に一次資料の URL がありません: ${r['法律ID']}`);
  }
  const counted = rows.filter(r => r['算入'] === 'はい');
  const involvedLaws = new Set(counted.map(r => r['法律ID']));

  type Entry = { law: Law; row: Record<string, string>; text: string; game: LawGame; vote: Record<string, string>; bill: Record<string, string> };
  const entries: Entry[] = [];
  for (const p of publish) {
    const l = loss.get(p.id);
    const amount = parseAmount(p['損失または便益']);
    if (!l || !l['損失または便益の額'] || l['参考フラグ'] === '参考' || !amount || !involvedLaws.has(p.id)) continue;
    const vote = votes.get(p.id);
    if (!vote || !vote.URL.startsWith('https://www.sangiin.go.jp/')) throw new Error(`参議院の投票の記録がありません: ${p.id}`);
    const bill = enacted.get(p.id);
    if (!bill?.['経過URL']?.startsWith('https://www.shugiin.go.jp/')) throw new Error(`議案の経過 URL がありません: ${p.id}`);
    const mine = counted.filter(r => r['法律ID'] === p.id);
    const unique = (a: Action) => [...new Set(mine.filter(r => r['行動'] === a).map(r => r['氏名']))];
    const game: LawGame = { proposers: unique('decide'), voters: unique('vote'), chairs: unique('chair'), yes: Number(vote['賛成']), no: Number(vote['反対']) };
    const side = p['側'].startsWith('国士側') ? 'benefit' : 'loss';
    entries.push({ law: { lawId: p.id, title: p['題名'], side, publishable: p['公開可否'] === '公開可', group: l['観測グループ'], amount }, row: p, text: p['損失または便益'], game, vote, bill });
  }

  // 便益は額が負で入っているので、配分の符号をそのまま使い、損失・貢献に分ける。
  type Tot = { loss: Range; credit: Range; groups: Map<string, number>; laws: { entry: Entry; fraction: number; roles: Partial<Record<CausalRole, number>>; share: Range }[] };
  const blank = (): Tot => ({ loss: zero(), credit: zero(), groups: new Map(), laws: [] });
  const totals = new Map<CausalVariant, Map<string, Tot>>();
  const lawOut: PublicMemberLaw[] = [];
  for (const variant of CAUSAL_VARIANTS) {
    const byPerson = new Map<string, Tot>();
    for (const entry of entries) {
      const out = allocateLaw(entry.law.amount, entry.game, variant);
      for (const r of out.rows) {
        const t = byPerson.get(r.personId) ?? blank();
        const mag = magnitude(r.share);
        if (entry.law.side === 'loss') t.loss = add(t.loss, mag); else t.credit = add(t.credit, mag);
        if (r.fraction > 0) t.groups.set(entry.law.group, (t.groups.get(entry.law.group) ?? 0) + 1);
        t.laws.push({ entry, fraction: r.fraction, roles: r.roles, share: mag });
        byPerson.set(r.personId, t);
      }
      if (variant === 'base') {
        const { law, row, text, game, vote, bill } = entry;
        const attributed = magnitude(out.rows.reduce((s, r) => add(s, r.share), zero()));
        lawOut.push({ id: law.lawId, title: law.title, side: law.side, amount: magnitude(law.amount), publishable: law.publishable,
          confidence: confidenceLabel(row['判定表の行'], text), judgement: row['判定表の行'], reason: row['理由'], group: law.group,
          persons: out.rows.length, attributed, source: bill['経過URL'], enactedOn: warekiDate(bill['公布日']),
          game: { proposers: game.proposers.length, proposerKind: law.lawId.startsWith('閣法') ? '内閣（閣議決定に関わった大臣）' : '発議者', vetoShare: out.shares.veto, voteShare: out.shares.vote,
            yes: game.yes, no: game.no, quota: out.shares.q, voters: game.voters.length, voteUrl: vote.URL, voteDate: vote['日付'], chairs: game.chairs.length, names: { proposers: game.proposers, voters: game.voters, chairs: game.chairs },
            parties: (bill['賛成会派_衆'] ?? '').split(';').map(s => s.trim()).filter(Boolean), party: magnitude(out.party), unidentified: magnitude(out.unidentified) } });
      }
    }
    // 成立を左右しない行動（質疑・修正案など）だけの人も、0円として載せる。
    for (const entry of entries) for (const name of new Set(counted.filter(r => r['法律ID'] === entry.law.lawId).map(r => r['氏名']))) {
      const t = byPerson.get(name) ?? blank();
      if (!t.laws.some(l => l.entry === entry)) t.laws.push({ entry, fraction: 0, roles: {}, share: zero() });
      byPerson.set(name, t);
    }
    totals.set(variant, byPerson);
  }

  const netOf = (t: Tot): Range => ordered({ low: t.credit.low - t.loss.high, median: t.credit.median - t.loss.median, high: t.credit.high - t.loss.low });
  const rankOf = (m: Map<string, Tot>) => {
    const list = [...m].map(([name, t]) => ({ name, net: netOf(t).median })).sort((a, b) => a.net - b.net || a.name.localeCompare(b.name));
    return new Map(list.map((x, i) => [x.name, { rank: i + 1, net: x.net }]));
  };
  const baseRank = rankOf(totals.get('base')!), chairRank = rankOf(totals.get('chair_veto')!);
  const evidenceOf = (lawId: string, name: string) => counted.filter(v => v['法律ID'] === lawId && v['氏名'] === name)
    .map(v => ({ action: v['行動'] as Action, actionLabel: ACTION_LABEL[v['行動'] as Action], title: v['当時の肩書'], house: v['院'], date: v['日付'], url: v['証拠URL'] }))
    .sort((a, b) => ACTION_WEIGHT[b.action] - ACTION_WEIGHT[a.action] || a.date.localeCompare(b.date));
  const members: PublicMember[] = [...totals.get('base')!].map(([name, t]) => {
    const r = baseRank.get(name)!, c = chairRank.get(name)!;
    const move = Math.abs(r.rank - c.rank);
    const laws = t.laws.map(({ entry, fraction, roles, share }) => {
      const all = evidenceOf(entry.law.lawId, name);
      const counts = (e: MemberEvidence) => { const role = ROLE_OF[e.action]; return role !== undefined && roles[role] !== undefined; };
      return { lawId: entry.law.lawId, side: entry.law.side, roles, fraction, share, evidence: all.filter(counts), context: all.filter(e => !counts(e)) };
    }).sort((a, b) => b.share.median - a.share.median);
    return { name, rank: r.rank, net: netOf(t), loss: t.loss, credit: t.credit,
      sensitivity: { chairVetoRank: c.rank, chairVetoNet: c.net, maxMove: move, flagged: move >= RANK_MOVE_FLAG },
      overlappingGroups: [...t.groups].filter(([, n]) => n > 1).map(([g]) => g), laws };
  }).sort((a, b) => a.rank - b.rank);
  const lawIds = new Set(entries.map(e => e.law.lawId));
  const inLaws = counted.filter(r => lawIds.has(r['法律ID']));
  const roleRows = inLaws.filter(r => r['行動'] === 'decide' || r['行動'] === 'vote');
  return {
    schema: 'public-members/v2',
    rules: ['causal-shapley-v1', 'loss-rule-v1', 'benefit-rule-v1.2'],
    laws: lawOut,
    members,
    counts: { members: members.length, loss: members.filter(m => m.net.median < 0).length, benefit: members.filter(m => m.net.median > 0).length, zero: members.filter(m => m.net.median === 0).length,
      involvements: roleRows.length, context: inLaws.length - roleRows.length, excluded: rows.filter(r => r['算入'] !== 'はい' && lawIds.has(r['法律ID'])).length },
  };
}
