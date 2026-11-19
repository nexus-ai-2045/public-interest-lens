import type { GenerationMetadata } from './generation-metadata';
/**
 * 議員ページの「全議員」の表（public-members-reference/v2）を作る。
 * ユーザーの選択（2026-10-18）：参考の額も、確かな額とは別の欄に「参考」の印つきで全員に配る。確かな額の順位は変えない。
 *
 * 決まり（1本ごとの人の判断は入れない）：
 * 1. 対象は公開ランキングで確かさ「参考」の法律。同じ観測（指標の組 group と窓 window が同じ）を共有する N 本は、
 *    観測の額を N 本で等分してから配る（足し合わせで同じ差を N 回数えないため）。
 * 2. 配り方は確かな額と同じ Shapley 値（causal-allocation.ts）。提出者の組と衆議院の賛成会派が拒否権者、参議院の賛成票が多数決。
 *    提出者：閣法は提出した回次の会期の最初から最後まで在任した閣僚（総理大臣を含む）に均等に配る（内閣の提出。副長官・法制局長官は閣僚ではない）。
 *    総理大臣が会期中に替わる回次は、その法律の衆議院の付託日に在任した閣僚に配る（scripts/build_auto_involvements.py と同じ）。衆法・参法は議案の提出者の欄。「○○君外N名」で名前の一覧が無いときは、
 *    代表者に 1/(N+1) を置き、残りは「名前不明の提出者」とする。委員会提出（○○委員長）は人に配らない。
 *    参議院：本会議の押しボタン投票の個人別の賛否（成立した日の、題名が一致する投票）。
 * 3. 参議院の個人別の賛否が見つからない法律は、提出者の組・衆議院の賛成会派・参議院の賛成会派の3者で 1/3 ずつとし、会派の分は人に配らない。
 * 4. 人物台帳（persons.csv）の全員と名簿（現職の衆参全議員）は、配る額が無くても0円で載せ、理由を付ける（全員公開の方針）。
 *    額も確かな額も無い人は画面で「評価なし」の印を付ける（0円と区別する）。
 * 5. 人は人物ID（person-id.ts、scripts/person_ids.py の台帳）で結ぶ。同姓同名の可能性がある名前は、一次資料で所属が決まる場合
 *    （衆法・参法の提出者は議案の種別、参議院の賛成は投票記録）だけ人物IDに結び、それ以外は配らない。
 * 6. 向きが未確定の法律（公開ランキングの印 DIRECTION_UNDETERMINED つき。全体指標の行）は人に配らない（設計確定 v2.1：向きを産業の差の符号で決めない）。
 *    その行の side は日本の産業と比較国の差の符号を写しただけで、法律が損失・便益のどちらを生んだかの証拠ではない。
 *    関わった人には額を付けず、理由（何本を配っていないか）だけを付ける。
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
  /** 額が無い理由、または関わった法律のうち向きが未確定で配っていない本数（額がある人にも付く）。 */
  reason: string;
};
export type PublicMembersReference = {
  schema: 'public-members-reference/v2';
  generatedFrom?: GenerationMetadata;
  rules: string[];
  members: ReferenceMember[];
  counts: { members: number; current: number; withAmount: number; ledger: number; laws: number; lawsWithVotes: number; lawsPartyOnly: number; observations: number; unresolved: number;
    /** 向きが未確定なので人に配らなかった法律の本数（laws には入らない）。 */
    lawsDirectionUndetermined: number };
};
/** 1人・1本・1役割ごとの配り先（公開ファイルには入れず、scripts/check_reference_members.py が全件を一次資料と照らす）。member は人物ID、name は出典の表記。 */
export type ReferenceAttribution = { member: string; name: string; house: string; lawId: string; role: ReferenceRole; side: 'loss' | 'benefit'; median: number };
export type ReferenceInputs = {
  ranking: { laws: { id: string; title: string; side: string; certainty: string; notes?: string[]; group: string; window: string; amountLowYen: number; amountMedianYen: number; amountHighYen: number; demotedReason?: string }[]; sharedReference?: { laws: { id: string }[] };
    /** 公開ランキングの生成条件。parameters.noAmount は「向きと額の符号が逆」などで法律の額を付けない法律（ranking.json と同じ形）。 */
    generatedFrom?: { parameters?: { noAmount?: string[] } } };
  enacted: string; votesIndex: string; ballots: string[]; sangiinMembers: string; cabinet: string; roster: string;
  /** 人物台帳 data/derived/person-ids/persons.csv。 */
  persons: string;
  /** 当時の会派の表 data/acquired/member-affiliation/at-time.csv（任意）。 */
  affiliationAtTime?: string;
};

const SANKO = '参考';
/** 公開ランキングの「向きは未確定」の印（scripts/build_public_ranking.py の MACRO_DIRECTION_NOTE）の書き出し。印の文言が機械的な目印を兼ねる。 */
export const DIRECTION_UNDETERMINED = '向きは未確定';
/** 委員会・調査会・審査会の提出（人の提出ではない）。 */
const COMMITTEE = /(委員長|委員会|調査会長|審査会長)$/;
/** 空白と敬称「君」、名簿の脚注の印（*・※ など）を取る。印を残すと、同じ人が印の有無で別人になる。字体は寄せない（出典の表記のまま）。 */
export const normName = (s: string): string => s.replace(/[\s　]/g, '').replace(/君$/, '').replace(/[*＊※†‡]+$/, '');
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
  // 閣僚＝国務大臣（総理大臣・各大臣・官房長官・担当大臣）。区分が「閣僚」の行には内閣官房副長官・総理府総務副長官・内閣法制局長官も入るが、閣僚ではないので除く。
  const NOT_MINISTER = /副長官|法制局長官/;
  const ministers = parseCsv(input.cabinet).filter(r => r['区分'] === '閣僚' && r['就任日_西暦'] && !NOT_MINISTER.test(r['役職']));
  const servingOn = (date: string, rows: Record<string, string>[]) => rows.filter(r => r['就任日_西暦'] <= date && (!r['退任日_西暦'] || date < r['退任日_西暦']));
  // 氏名は字体のゆれも寄せてから比べる（寄せないと、同じ人が別人になり、通して在任した閣僚が落ちる）。出す名前は名簿の表記（印と空白を取ったもの）。
  const servingNames = (date: string) => new Map(servingOn(date, ministers).map(r => [canonical(r['氏名']), normName(r['氏名'])]));
  const pmOn = (date: string) => servingOn(date, ministers).filter(r => r['役職'] === '内閣総理大臣').map(r => canonical(r['氏名']))[0] ?? '';
  // 提出日の列が無いので、提出した回次の会期は、衆議院の付託日（継続審査でない閣法のもの）の最初と最後で代える。
  const span = new Map<string, { first: string; last: string }>();
  const referredOn = (r: Record<string, string>) => r['種別'] === '閣法' && r['回次'] === r['提出回次'] ? warekiDate(r['付託日_衆']) : '';
  for (const r of enacted.values()) {
    const d = referredOn(r);
    if (!d) continue;
    const x = span.get(r['提出回次']);
    span.set(r['提出回次'], { first: !x || d < x.first ? d : x.first, last: !x || d > x.last ? d : x.last });
  }
  // 閣法は内閣の提出。総理大臣1人に全部付けず（首相だけが突出する原因）、提出した回次の会期の最初から最後まで在任した閣僚（総理大臣を含む）に均等に配る
  // （設計確定 v2.1：閣法は首相1人に付けない）。途中で替わった閣僚は含めない。
  // 総理大臣が会期中に替わる回次は、どの内閣の提出かを回次では決められないので、その法律の衆議院の付託日に在任した閣僚にする
  // （提出から付託までは数日。scripts/build_auto_involvements.py の cabinets と同じ決まり）。継続審査で付託日が後の回次のものは配らない。
  // 人物台帳に結べない人は分母に入れない（入れると、配られない分が黙って消える）。回次・付託日ごとに1回だけ計算する。
  let unresolved = 0;
  const cabinetCache = new Map<string, { names: string[]; dropped: number }>();
  const cabinetOf = (bill: Record<string, string>): { names: string[]; dropped: number } => {
    const x = span.get(bill['提出回次']);
    const stable = !!x && !!pmOn(x.first) && pmOn(x.first) === pmOn(x.last);
    const referred = referredOn(bill);
    const key = stable ? `回次:${bill['提出回次']}` : referred && pmOn(referred) ? `付託日:${referred}` : '';
    if (!key) return { names: [], dropped: 0 };
    const hit = cabinetCache.get(key);
    if (hit) return hit;
    const first = servingNames(stable ? x!.first : referred);
    const last = servingNames(stable ? x!.last : referred);
    const all = [...first].filter(([k]) => last.has(k)).map(([, name]) => name);
    const names = all.filter(n => ledger.resolve(n, ''));
    const out = { names, dropped: all.length - names.length };
    cabinetCache.set(key, out);
    return out;
  };

  // コロナ期と重なる・分離できない法律は配らない。額がコロナ期の日本と比較国の落ち込みの差をそのまま含み、その法律の効果ではない（設計決定0014）。
  // 検証で参考に降格した法律（demotedReason あり）の額は、実名の議員には配らない。
  // 共有額の参考（sharedReference。1本ごとの額を持たない）も配らない。
  const sharedIds = new Set((input.ranking.sharedReference?.laws ?? []).map(l => l.id));
  // 額なし（noAmount）の法律には、額が残っていても配らない（設計確定 v2.1：額なしは人の点に入れない）。
  const noAmountIds = new Set(input.ranking.generatedFrom?.parameters?.noAmount ?? []);
  const candidates = input.ranking.laws.filter(l => l.certainty === SANKO && !l.demotedReason && !sharedIds.has(l.id) && !noAmountIds.has(l.id) && !(l.notes ?? []).some(n => n.startsWith('コロナ期と')));
  // 向きが未確定の法律（全体指標の行）は人に配らない。side は産業と比較国の差の符号で、法律の効果の向きの証拠ではない（設計確定 v2.1）。
  // 誰が関わったかは同じ手順で調べ、額の代わりに理由を付ける。
  const isUndetermined = (l: (typeof candidates)[number]) => (l.notes ?? []).some(n => n.startsWith(DIRECTION_UNDETERMINED));
  const laws = candidates.filter(l => !isUndetermined(l));
  const undetermined = candidates.filter(isUndetermined);
  const obs = new Map<string, number>();
  for (const l of laws) obs.set(`${l.group}|${l.window}`, (obs.get(`${l.group}|${l.window}`) ?? 0) + 1);

  // 必要な投票だけ個人別の賛否を読む。
  const games = new Map<string, { game: LawGame | null; proposers: { name: string; weight: number }[]; voteId: string }>();
  const neededVotes = new Set<string>();
  for (const l of [...laws, ...undetermined]) {
    const b = enacted.get(l.id);
    if (!b) continue;
    const day = warekiDate(b['議決日_参']);
    const vote = day ? pickVote(b['題名'], byDay.get(day) ?? []) : null;
    let proposers: { name: string; weight: number }[] = [];
    if (l.id.startsWith('閣法')) {
      const cabinet = cabinetOf(b);
      if (!isUndetermined(l)) unresolved += cabinet.dropped;
      proposers = cabinet.names.map(name => ({ name, weight: 1 / cabinet.names.length }));
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
  // 向きが未確定で配らなかった法律（人物IDごとの法律ID）。額には入れず、理由にだけ使う。
  const withheld = new Map<string, Set<string>>();
  const hold = (name: string, memberHouse: string, lawId: string) => {
    const res = ledger.resolve(name, memberHouse);
    if (!res) return;
    names.set(res.id, res.person?.name ?? names.get(res.id) ?? name);
    withheld.set(res.id, (withheld.get(res.id) ?? new Set()).add(lawId));
  };
  // memberHouse は一次資料で所属院が決まるときだけ渡す（衆法・参法の提出者は議案の種別。閣法の閣僚は決まらないので渡さない）。
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
  const proposerHouse = (lawId: string) => lawId.startsWith('参法') ? '参議院' : lawId.startsWith('衆法') ? '衆議院' : '';
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
    for (const p of g.proposers) give(p.name, proposerHouse(l.id), l, 'proposer', scale(amount, proposerFraction * p.weight));
    for (const v of voters) if (v.resolved) give(v.name, '参議院', l, 'vote', scale(amount, voteFraction));
    else unresolved++;
  }
  // 向きが未確定の法律は、関わった人（提出者・参議院の賛成）に額を付けず、配らなかった記録だけ残す。
  for (const l of undetermined) {
    const g = games.get(l.id);
    if (!g) continue;
    const yes = g.game && g.voteId && g.game.yes > 0 ? [...new Map((yesBy.get(g.voteId) ?? []).map(v => [v.id, v])).values()].slice(0, g.game.yes) : [];
    for (const p of g.proposers) hold(p.name, proposerHouse(l.id), l.id);
    for (const v of yes) if (v.resolved) hold(v.name, '参議院', l.id);
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
  const keys = new Set([...people.keys(), ...withheld.keys(), ...roster.map(rosterId), ...ledgerPeople.map(p => p.id)]);
  const members: ReferenceMember[] = [...keys].map(id => {
    const name = names.get(id) ?? id;
    const t = people.get(id) ?? { loss: zero(), credit: zero(), laws: [] };
    const net = { low: t.credit.low - t.loss.high, median: t.credit.median - t.loss.median, high: t.credit.high - t.loss.low };
    const held = withheld.get(id)?.size ?? 0;
    const reason = held ? `関わった参考の額の法律${held}本は、向きが未確定なので配っていない（損失・便益の区別が産業と比較国の差の符号だけで、法律の効果の向きを示す証拠がない）`
      : t.laws.length ? '' : current.get(id)?.house === '衆議院'
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
      lawsWithVotes: withVotes, lawsPartyOnly: partyOnly, observations: obs.size, unresolved, lawsDirectionUndetermined: undetermined.length },
    attributions,
  };
}
