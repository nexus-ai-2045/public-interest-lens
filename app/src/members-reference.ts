import type { GenerationMetadata } from './generation-metadata';
/**
 * 議員ページの「全議員」の表（public-members-reference/v2）を作る。
 * ユーザーの選択（2026-10-18）：参考の額も、確かな額とは別の欄に「参考」の印つきで全員に配る。確かな額の順位は変えない。
 *
 * 決まり（1本ごとの人の判断は入れない）：
 * 1. 対象は公開ランキングで確かさ「参考」の法律。同じ観測（指標の組 group と窓 window が同じ）を共有する N 本は、
 *    観測の額を N 本で等分してから配る（足し合わせで同じ差を N 回数えないため）。
 * 2. 配り方は確かな額と同じ Shapley 値（causal-allocation.ts）。提出者の組と衆議院の賛成会派が拒否権者、参議院の賛成票が多数決。
 *    提出者：閣法は提出時の内閣総理大臣（閣議決定の長）。衆法・参法は議案の提出者の欄。「○○君外N名」で名前の一覧が無いときは、
 *    代表者に 1/(N+1) を置き、残りは「名前不明の提出者」とする。委員会提出（○○委員長）は人に配らない。
 *    参議院：本会議の押しボタン投票の個人別の賛否（成立した日の、題名が一致する投票）。
 * 3. 参議院の個人別の賛否が見つからない法律は、提出者の組・衆議院の賛成会派・参議院の賛成会派の3者で 1/3 ずつとし、会派の分は人に配らない。
 * 4. 人物台帳（persons.csv）の全員と名簿（現職の衆参全議員）は、配る額が無くても0円で載せ、理由を付ける（全員公開の方針）。
 *    額も確かな額も無い人は画面で「評価なし」の印を付ける（0円と区別する）。
 * 5. 人は人物ID（person-id.ts、scripts/person_ids.py の台帳）で結ぶ。同姓同名の可能性がある名前は、一次資料で所属が決まる場合
 *    （衆法・参法の提出者は議案の種別、参議院の賛成は投票記録）だけ人物IDに結び、それ以外は配らない。
 */
import { allocateLaw, PARTY_ID, UNIDENTIFIED_ID, type LawGame } from './causal-allocation';
import { parseCsv } from './impact-batch';
import { warekiDate } from './members-build';
import { affiliationOf } from './caucus-label';
import { canonical, PersonLedger } from './person-id';

export type Range = { low: number; median: number; high: number };
export type ReferenceRole = 'proposer' | 'vote';
export type ReferenceLawShare = { lawId: string; title: string; side: 'loss' | 'benefit'; role: ReferenceRole; share: number };
export type ReferenceMember = {
  /** 人物ID（scripts/person_ids.py）。ふつうは寄せた氏名。同姓同名の別人は「名前（衆・福岡2）」のように院と選挙区が付く。 */
  id: string;
  name: string;
  /** 現職なら院・所属（党名。名簿の会派の略称から caucus-label.ts で直したもの）・会派（名簿の略称）・選挙区。元職・当時だけの人は null。 */
  current: { house: string; party: string; caucus: string; district: string } | null;
  /** 参議院の投票記録に出てくる会派（最後に記録されたもの）。 */
  lastSangiinParty: string;
  /** 国会会議録の発言者所属会派から取った、記録のある最後の日付の会派（scripts/fetch_affiliation_at_time.py）。無ければ空。 */
  lastKnownCaucus: { name: string; date: string } | null;
  loss: Range;
  credit: Range;
  net: Range;
  laws: number;
  /** 額の大きい順に最大5本。 */
  top: ReferenceLawShare[];
  reason: string;
};
export type PublicMembersReference = {
  schema: 'public-members-reference/v2';
  generatedFrom?: GenerationMetadata;
  rules: string[];
  members: ReferenceMember[];
  counts: { members: number; current: number; withAmount: number; ledger: number; laws: number; lawsWithVotes: number; lawsPartyOnly: number; observations: number; unresolved: number };
};
/** 1人・1本・1役割ごとの配り先（公開ファイルには入れず、scripts/check_reference_members.py が全件を一次資料と照らす）。member は人物ID、name は出典の表記。 */
export type ReferenceAttribution = { member: string; name: string; house: string; lawId: string; role: ReferenceRole; side: 'loss' | 'benefit'; median: number };
export type ReferenceInputs = {
  ranking: { laws: { id: string; title: string; side: string; certainty: string; notes?: string[]; group: string; window: string; amountLowYen: number; amountMedianYen: number; amountHighYen: number; demotedReason?: string }[] };
  enacted: string; votesIndex: string; ballots: string[]; sangiinMembers: string; cabinet: string; roster: string;
  /** 人物台帳 data/derived/person-ids/persons.csv。 */
  persons: string;
  /** 当時の会派の表 data/acquired/member-affiliation/at-time.csv（任意）。 */
  affiliationAtTime?: string;
};

const SANKO = '参考';
/** 委員会・調査会・審査会の提出（人の提出ではない）。 */
const COMMITTEE = /(委員長|委員会|調査会長|審査会長)$/;
export const normName = (s: string): string => s.replace(/[\s　]/g, '').replace(/君$/, '');
const KANJI_NUM: Record<string, number> = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
/** 「十二」「二十三」などの漢数字（99まで）。 */
export function kanjiNumber(s: string): number {
  if (/^\d+$/.test(s)) return Number(s);
  const m = /^(?:([一二三四五六七八九])?十)?([一二三四五六七八九])?$/.exec(s);
  if (!m || s === '') return NaN;
  const tens = s.includes('十') ? (m[1] ? KANJI_NUM[m[1]] : 1) : 0;
  return tens * 10 + (m[2] ? KANJI_NUM[m[2]] : 0);
}
/** 「熊代 昭彦君外四名」→ 代表者と、名前の無いほかの人数。 */
export function parseProposer(text: string): { lead: string; others: number } {
  const m = /^(.+?)君(?:外(.+?)名)?$/.exec(text.trim());
  if (!m) return { lead: normName(text), others: 0 };
  return { lead: normName(m[1]), others: m[2] ? kanjiNumber(m[2]) || 0 : 0 };
}
const shortTitle = (t: string) => t.replace(/案$/, '');
const squash = (s: string) => s.replace(/[\s　]/g, '');

/** 成立した日の参議院の投票から、題名が一致するものを1つ選ぶ（無ければ null）。 */
export function pickVote(title: string, candidates: Record<string, string>[]): Record<string, string> | null {
  const t = shortTitle(squash(title));
  // 成立した法律なので、可決した投票（賛成が反対より多い）だけを候補にする。
  let hits = candidates.filter(v => squash(v['議案名']).includes(t + '案') && Number(v['集計_賛成']) > Number(v['集計_反対']));
  if (hits.length > 1) hits = hits.filter(v => squash(v['議案名']).includes(t + '案（') || squash(v['議案名']).includes(t + '案「') || squash(v['議案名']).endsWith(t + '案'));
  if (hits.length > 1) hits = hits.filter(v => !/修正案/.test(v['議案名']) || /原案/.test(v['議案名']));
  if (hits.length > 1) hits = hits.filter(v => /原案|全部/.test(v['議案名']));
  return hits.length === 1 ? hits[0] : null;
}

const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });
const scale = (r: Range, x: number): Range => ({ low: r.low * x, median: r.median * x, high: r.high * x });

export function buildReferenceMembers(input: ReferenceInputs): PublicMembersReference & { attributions: ReferenceAttribution[] } {
  const ledger = new PersonLedger(input.persons ?? '', input.roster);
  const enacted = new Map(parseCsv(input.enacted).map(r => [`${r['種別']}-${r['提出回次']}-${r['番号']}`, r]));
  const byDay = new Map<string, Record<string, string>[]>();
  for (const v of parseCsv(input.votesIndex)) { const l = byDay.get(v['投票日']) ?? []; l.push(v); byDay.set(v['投票日'], l); }
  const idName = new Map<string, { name: string; party: string; session: number }>();
  for (const r of parseCsv(input.sangiinMembers)) {
    const prev = idName.get(r['議員ID']);
    if (!prev || Number(r['回次']) >= prev.session) idName.set(r['議員ID'], { name: normName(r['議員名']), party: r['会派'], session: Number(r['回次']) });
  }
  const pms = parseCsv(input.cabinet).filter(r => r['役職'] === '内閣総理大臣' && r['就任日_西暦']);
  const pmOn = (date: string) => pms.filter(r => r['就任日_西暦'] <= date && (!r['退任日_西暦'] || date < r['退任日_西暦'])).map(r => normName(r['氏名']))[0] ?? '';
  // 閣法の提出者は提出した時の内閣総理大臣。提出日の列が無いので、提出した回次の会期中の衆議院の付託日（継続審査でない閣法のもの）の
  // 最初と最後で同じ総理大臣ならその人にする。会期中に総理大臣が替わった回次は、提出時の総理大臣を決められないので配らない。
  const span = new Map<string, { first: string; last: string }>();
  for (const r of enacted.values()) {
    const d = r['種別'] === '閣法' && r['回次'] === r['提出回次'] ? warekiDate(r['付託日_衆']) : '';
    if (!d) continue;
    const x = span.get(r['提出回次']);
    span.set(r['提出回次'], { first: !x || d < x.first ? d : x.first, last: !x || d > x.last ? d : x.last });
  }
  const submitterPm = (session: string) => {
    const x = span.get(session);
    if (!x) return '';
    const a = pmOn(x.first);
    return a && a === pmOn(x.last) ? a : '';
  };

  // コロナ期と重なる・分離できない法律は配らない。額がコロナ期の日本と比較国の落ち込みの差をそのまま含み、その法律の効果ではない（設計決定0014）。
  // 検証で参考に降格した法律（demotedReason あり）の額は、実名の議員には配らない。
  const laws = input.ranking.laws.filter(l => l.certainty === SANKO && !l.demotedReason && !(l.notes ?? []).some(n => n.startsWith('コロナ期と')));
  const obs = new Map<string, number>();
  for (const l of laws) obs.set(`${l.group}|${l.window}`, (obs.get(`${l.group}|${l.window}`) ?? 0) + 1);

  // 必要な投票だけ個人別の賛否を読む。
  const games = new Map<string, { game: LawGame | null; proposers: { name: string; weight: number }[]; voteId: string }>();
  const neededVotes = new Set<string>();
  for (const l of laws) {
    const b = enacted.get(l.id);
    if (!b) continue;
    const day = warekiDate(b['議決日_参']);
    const vote = day ? pickVote(b['題名'], byDay.get(day) ?? []) : null;
    let proposers: { name: string; weight: number }[] = [];
    if (l.id.startsWith('閣法')) {
      const pm = submitterPm(b['提出回次']);
      if (pm) proposers = [{ name: pm, weight: 1 }];
    } else if (COMMITTEE.test(parseProposer(b['提出者']).lead)) {
      // 委員会提出（「建設委員長」など）は人の提出ではないので、提出者一覧に委員長の名前があっても人には配らない。
    } else if (b['提出者一覧']) {
      const names = b['提出者一覧'].split(/[;；、,]/).map(normName).filter(Boolean);
      proposers = names.map(name => ({ name, weight: 1 / names.length }));
    } else if (b['提出者']) {
      const p = parseProposer(b['提出者']);
      proposers = [{ name: p.lead, weight: 1 / (p.others + 1) }];
    }
    if (vote) neededVotes.add(vote['投票ID']);
    games.set(l.id, { game: vote ? { proposers: ['提出者の組'], voters: [], chairs: [], yes: Number(vote['集計_賛成']), no: Number(vote['集計_反対']) } : null, proposers, voteId: vote?.['投票ID'] ?? '' });
  }
  // 参議院の賛成は、押しボタン投票の議員ID→名前なので参議院議員と確定できる。同じ氏名の参議院議員が複数いて決まらない人は、
  // 賛成票の数には入れる（配る割合を変えない）が、人には配らない（「未特定」の印の識別子にする）。
  type Voter = { id: string; name: string; resolved: boolean };
  const yesBy = new Map<string, Voter[]>();
  for (const text of input.ballots) for (const r of parseCsv(text)) {
    if (r['賛否'] !== 'Y' || !neededVotes.has(r['投票ID'])) continue;
    const who = idName.get(r['議員ID']);
    if (!who) continue;
    const res = ledger.resolve(who.name, '参議院');
    const l = yesBy.get(r['投票ID']) ?? []; l.push(res ? { id: res.id, name: who.name, resolved: true } : { id: `未特定:${r['議員ID']}`, name: who.name, resolved: false }); yesBy.set(r['投票ID'], l);
  }

  // 同姓同名で台帳の人に結べない名簿の行（person_ids.py が undecided.csv に出したもの）は、別人のIDに混ぜないよう使わない。
  const roster = parseCsv(input.roster).filter(r => ledger.rosterPerson(r) || !ledger.isSplit(r['氏名']));

  type Tot = { loss: Range; credit: Range; laws: ReferenceLawShare[] };
  const people = new Map<string, Tot>();
  const names = new Map<string, string>();
  const attributions: ReferenceAttribution[] = [];
  let unresolved = 0;
  // memberHouse は一次資料で所属院が決まるときだけ渡す（衆法・参法の提出者は議案の種別。閣法の総理大臣は決まらないので渡さない）。
  const give = (name: string, memberHouse: string, law: (typeof laws)[number], role: ReferenceRole, amount: Range) => {
    const res = ledger.resolve(name, memberHouse);
    if (!res) { unresolved++; return; }
    const key = res.id;
    names.set(key, res.person?.name ?? names.get(key) ?? name);
    const t = people.get(key) ?? { loss: zero(), credit: zero(), laws: [] };
    // 額は側（損失・便益）の向きにそろえた大きさ。中央値の符号で向きを決め、幅は符号つきのまま並べ直す（幅が0をまたいでも low ≤ median ≤ high）。
    const s = amount.median < 0 ? -1 : 1;
    const mag = { low: Math.min(s * amount.low, s * amount.high), median: s * amount.median, high: Math.max(s * amount.low, s * amount.high) };
    if (law.side === 'loss') t.loss = add(t.loss, mag); else t.credit = add(t.credit, mag);
    t.laws.push({ lawId: law.id, title: law.title, side: law.side === 'loss' ? 'loss' : 'benefit', role, share: mag.median });
    attributions.push({ member: key, name, house: res.person?.house ?? memberHouse, lawId: law.id, role, side: law.side === 'loss' ? 'loss' : 'benefit', median: mag.median });
    people.set(key, t);
  };
  let withVotes = 0, partyOnly = 0;
  for (const l of laws) {
    const g = games.get(l.id);
    if (!g) continue;
    const per = 1 / (obs.get(`${l.group}|${l.window}`) ?? 1);
    const amount = scale({ low: l.amountLowYen, median: l.amountMedianYen, high: l.amountHighYen }, per);
    const { voteId } = g;
    let proposerFraction: number, voters: Voter[] = [], voteFraction = 0;
    if (g.game && voteId && g.game.yes > 0) {
      withVotes++;
      const yes = [...new Map((yesBy.get(voteId) ?? []).map(v => [v.id, v])).values()].slice(0, g.game.yes);
      const out = allocateLaw(amount, { ...g.game, voters: yes.map(v => v.id) }, 'base');
      const proposerRow = out.rows.find(r => r.personId === '提出者の組');
      proposerFraction = proposerRow?.fraction ?? 0;
      voters = yes;
      voteFraction = out.rows.find(r => r.personId !== '提出者の組' && r.personId !== PARTY_ID && r.personId !== UNIDENTIFIED_ID)?.fraction ?? 0;
    } else {
      partyOnly++;
      proposerFraction = 1 / 3;
    }
    const proposerHouse = l.id.startsWith('参法') ? '参議院' : l.id.startsWith('衆法') ? '衆議院' : '';
    for (const p of g.proposers) give(p.name, proposerHouse, l, 'proposer', scale(amount, proposerFraction * p.weight));
    for (const v of voters) if (v.resolved) give(v.name, '参議院', l, 'vote', scale(amount, voteFraction));
    else unresolved++;
  }

  // 名簿の1行は台帳の1人（院と選挙区が同じ人）。本名で載る参議院議員も、台帳の別名で同じ人になる。
  const rosterId = (r: Record<string, string>) => ledger.rosterPerson(r)?.id ?? canonical(r['氏名']);
  const current = new Map(roster.map(r => [rosterId(r), { house: r['院'], party: affiliationOf(r['院'], r['会派']), caucus: r['会派'], district: r['選挙区'] }]));
  for (const r of roster) names.set(rosterId(r), ledger.rosterPerson(r)?.name ?? names.get(rosterId(r)) ?? r['氏名'].replace(/[\s\u3000]/g, ''));
  const lastKnown = new Map<string, { name: string; date: string }>();
  for (const r of input.affiliationAtTime ? parseCsv(input.affiliationAtTime) : []) {
    if (!r['当時の会派']) continue;
    const cur = lastKnown.get(r['人物ID']);
    if (!cur || r['日付'] > cur.date) lastKnown.set(r['人物ID'], { name: r['当時の会派'], date: r['日付'] });
  }
  const lastParty = new Map<string, string>();
  for (const v of idName.values()) { const res = ledger.resolve(v.name, '参議院'); if (res) lastParty.set(res.id, v.party); }
  // 台帳の全員（元職を含む）・現職の名簿・額のある人。台帳の空行（ヘッダー直後の空 ID）は除く。
  const ledgerPeople = [...ledger.byId.values()].filter(p => p.id);
  for (const p of ledgerPeople) if (!names.has(p.id)) names.set(p.id, p.name);
  const keys = new Set([...people.keys(), ...roster.map(rosterId), ...ledgerPeople.map(p => p.id)]);
  const members: ReferenceMember[] = [...keys].map(id => {
    const name = names.get(id) ?? id;
    const t = people.get(id) ?? { loss: zero(), credit: zero(), laws: [] };
    const net = { low: t.credit.low - t.loss.high, median: t.credit.median - t.loss.median, high: t.credit.high - t.loss.low };
    const reason = t.laws.length ? '' : current.get(id)?.house === '衆議院'
      ? '参考の額の法律で、提出者としての記録がない（衆議院は起立採決で個人の賛否が残らず、会派に置いている）'
      : '参考の額の法律で、提出者・参議院の賛成としての記録がない';
    return { id, name, current: current.get(id) ?? null, lastSangiinParty: lastParty.get(id) ?? '', lastKnownCaucus: lastKnown.get(id) ?? null, loss: t.loss, credit: t.credit, net, laws: new Set(t.laws.map(x => x.lawId)).size,
      top: [...t.laws].sort((a, b) => b.share - a.share).slice(0, 5), reason };
  }).sort((a, b) => a.net.median - b.net.median || a.id.localeCompare(b.id));
  return {
    schema: 'public-members-reference/v2',
    rules: ['reference-split-by-observation-v1', 'causal-shapley-v1', 'reference-party-fallback-v1'],
    members,
    counts: { members: members.length, current: members.filter(m => m.current).length, withAmount: members.filter(m => m.laws > 0).length, ledger: ledgerPeople.length, laws: laws.length,
      lawsWithVotes: withVotes, lawsPartyOnly: partyOnly, observations: obs.size, unresolved },
    attributions,
  };
}
