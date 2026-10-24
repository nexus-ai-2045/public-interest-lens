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
  /**
   * 点数に入る額（行動の帳簿）。正の額で、向きは effect（悪い向き＝国賊側、良い向き＝国士側）。
   * 損失の法律を推した・便益の法律に反対した → bad。便益の法律を推した・損失の法律に反対した → good。
   */
  share: Range;
  /** with：成立させた側（提出・賛成）、against：参議院本会議で反対した（向きを逆にして配る）。 */
  direction: 'with' | 'against';
  /** 点数に入る額の向き。 */
  effect: 'bad' | 'good';
  /** 役職の帳簿：閣法の提出者（閣議決定に関わった大臣）として担当しただけの分。点数に入れない（つまみで入れられる）。 */
  office: Range;
  /** 配分に入った行動（一次資料つき）。 */
  evidence: MemberEvidence[];
  /** 成立を左右しないため配らない行動（質疑・修正案・基準での委員長）。 */
  context: MemberEvidence[];
};
export type PublicMember = {
  /** 人物ID。同じ氏名の別人は院と選挙区を付けて分ける（scripts/person_ids.py）。集計・つまみ・URL はこれで結ぶ。 */
  id: string;
  /** 表示用の氏名。 */
  name: string;
  rank: number;
  /** 純額 = 生んだ額 − 失わせた額。負が国賊側、正が国士側。 */
  net: Range;
  loss: Range;
  credit: Range;
  /** 役職の帳簿の合計（点数に入れない）。loss は損失の法律、credit は便益の法律の担当分。 */
  office: { loss: Range; credit: Range };
  sensitivity: { chairVetoRank: number; chairVetoNet: number; maxMove: number; flagged: boolean };
  overlappingGroups: string[];
  laws: MemberLaw[];
};
/** 同じ観測を共有する法律の本数で額を割る（円未満は 0 の方向へ切り捨て）。 */
export const splitRange = (r: Range, n: number): Range => ({ low: Math.trunc(r.low / n), median: Math.trunc(r.median / n), high: Math.trunc(r.high / n) });
/** この法律の分として人に配る額（同じ観測を共有する法律の本数で割ったもの）。 */
export const allocatedAmount = (law: PublicMemberLaw): Range => splitRange(law.amount, law.observationLaws);
export type PublicMemberLaw = {
  id: string; title: string; side: Law['side']; amount: Range;
  /** 同じ観測を共有する法律の本数（自分を含む）。配る額は amount をこの本数で割ったもの。 */
  observationLaws: number;
  publishable: boolean; confidence: string; judgement: string; reason: string;
  group: string; persons: number; attributed: Range; source: string; enactedOn: string;
  game: {
    proposers: number; proposerKind: string; vetoShare: number; voteShare: number; yes: number; no: number; quota: number; voters: number;
    voteUrl: string; voteDate: string; chairs: number;
    /** つまみで画面側が計算し直すための人物IDの一覧。 */
    names: { proposers: string[]; voters: string[]; chairs: string[]; opposers: string[] };
    /** 閣法か（提出者の組は内閣で、担当の大臣の分は役職の帳簿に置く）。 */
    cabinet: boolean;
    /** 参議院本会議で反対した人数（人物を決められた人）。 */
    opposers: number;
    /** 衆議院の賛成会派（起立採決で個人の賛否が残らないので党に置く）。 */
    parties: string[]; party: Range; unidentified: Range;
    /** 衆議院の反対会派（議案の経過の表記）。 */
    opposingParties: string[];
  };
};
export type PartyLedger = { name: string; bad: Range; good: Range; net: Range; laws: { lawId: string; side: Law['side']; direction: 'with' | 'against'; effect: 'bad' | 'good'; share: Range }[] };
export type PartyBloc = {
  bloc: string; parties: string[]; people: number; laws: number; yesLaws: number; noLaws: number;
  /** 賛成した法律のうち損失の法律の割合（会派で中身が違うかを見る）。 */
  lossShareOfYes: number;
  certainty: Record<string, number>;
  bad: Range; good: Range; net: Range;
  /** 賛否の数（議員 × 法律）。 */
  votes: number;
  /** 純額の中央値を人数・賛否を示した法律の本数・賛否の数（1人の1本の賛否）で割ったもの。 */
  perPerson: number; perLaw: number; perVote: number;
};
export type PartyRanking = {
  blocs: PartyBloc[];
  /** 参議院の投票の期間（会派が分かるのはこの範囲の採決だけ）。 */
  from: string; to: string;
  /** 会派が分からなかった分（衆議院だけの行動・名簿と名前が合わない人）。 */
  unmatched: { people: number; net: Range };
};
/** 税の帳簿の1本（年ごとの額は2020年の円。マイナスが損失）。 */
export interface TaxLedgerLaw {
  lawId: string; title: string; kind: string; changes: string[]; years: { year: number; nth: number; amount: number }[];
  total: number; certainty: string; marks: string[]; notes: string[]; sources: string[] }

export function taxLedgerOf(csv: string): TaxLedgerLaw[] {
  const book = new Map<string, TaxLedgerLaw>();
  for (const r of parseCsv(csv)) {
    const t = book.get(r['法律ID']) ?? { lawId: r['法律ID'], title: r['題名'], kind: r['種類'], changes: [], years: [], total: 0, certainty: r['確かさ'], marks: r['印'].split('／'), notes: [], sources: [] };
    if (!t.changes.includes(r['内容'])) t.changes.push(r['内容']);
    if (r['注'] && !t.notes.includes(r['注'])) t.notes.push(r['注']);
    for (const u of [r['出典URL'], r['乗数の出典']]) if (u && !t.sources.includes(u)) t.sources.push(u);
    const amount = Number(r['額_円']);
    t.years.push({ year: Number(r['年']), nth: Number(r['何年目']), amount });
    t.total += amount;
    book.set(t.lawId, t);
  }
  return [...book.values()].sort((a, b) => a.total - b.total || a.lawId.localeCompare(b.lawId));
}

export type PublicMembers = {
  schema: 'public-members/v2';
  rules: string[];
  laws: PublicMemberLaw[];
  members: PublicMember[];
  counts: { members: number; loss: number; benefit: number; zero: number; involvements: number; context: number; excluded: number };
  /**
   * 会派の帳簿（衆議院の会派別の賛否。起立採決で個人の賛否が残らないので会派に置く）。点数（議員の順位）には足さない。
   * 賛成会派：成立させた側として、衆議院の賛成会派の組の分を会派の数で等分。反対会派：賛成会派1つと同じ額を、向きを逆にして置く。
   * 会派別の賛否が議案の経過に載るのは第186回国会ごろから（それより前の法律は載らない）。
   */
  parties?: PartyLedger[];
  /**
   * 省庁の帳簿（閣法の所管の省庁）。閣法の提出者の組の分（役職の帳簿と同じ額）を、提案理由を説明した大臣の省庁に置く。
   * 閣法の原案は所管の省庁が書き、大臣は内閣の一員として署名する。内閣と所管の省庁の組の分で、どちらか一方のせいではない。議員の点数には足さない。
   */
  ministries?: PartyLedger[];
  /**
   * 税の帳簿（scripts/build_tax_ledger.py）：消費税率を変えた法律の額を、政府のマクロモデルの乗数で出したもの。
   * 法律の額（allocation-v1）とは別の物差しで、議員の点数にも足さない。確かさは「低」、需要の短期効果だけ。
   */
  taxLedger?: TaxLedgerLaw[];
  /**
   * 省庁の抵抗の件数と団体の立場（scripts/build_org_ledger.py）。原本照合済みの記録だけを数え、額は付けない。
   * 個人（学者・委員・官僚）は名指しせず、区分でまとめる。出典URL は CSV に残す（画面は件数だけ）。
   */
  resistance?: { ministry: string; total: number; refusals: number; answers: number; hearings: number; followups: number }[];
  orgStances?: { name: string; kind: string; against: number; careful: number; conditional: number; support: number; technologies: string[] }[];
  /**
   * 政党ランキング：参議院本会議の賛否を、採決した時の会派の系統ごとに足したもの（議員の点数を会派で集めただけで、別の額ではない）。
   * 主に1人あたり・1本あたりで並べる（与党は人数も賛成した本数も多く、総額は規模で大きくなる）。総額は参考。
   */
  partyRanking?: PartyRanking;
  /** 公開ランキングで確かさ高・中なのに、関わった議員の記録がまだそろわず配分に入っていない法律（scripts/build_public_members.mjs が付ける）。 */
  pending?: { id: string; title: string; side: 'loss' | 'benefit'; certainty: string; median: number }[];
};

const ACTIONS = Object.keys(ACTION_WEIGHT) as Action[];
const POSITIONS = Object.keys(POSITION_WEIGHT) as Position[];
const ROLE_OF: Partial<Record<Action, CausalRole>> = { decide: 'proposer', vote: 'vote', chair: 'chair' };
export const RANK_MOVE_FLAG = 5;

/** listed：公開ランキングに載った法律の id（出典チェックで外した法律を共有本数に数えないため）。省略時は publish.csv の全部。 */
/**
 * autoInvolvements・autoVotes：関与の一覧がまだ無い法律について、議案の提出者の欄と参議院の個人別の投票から機械的に作ったもの
 * （scripts/build_auto_involvements.py。質疑・委員長・修正案は入らない）。手で集めた一覧と同じ形で、同じ決まりで配る。
 */
/**
 * voteParties：採決ごとの投票した議員の会派（投票ID・議員名・会派、scripts/build_vote_parties.py）。政党ランキングで採決した時の会派を決める。
 *   回次の途中で会派が変わった議員がいるので、回次ではなく採決ごとに引く。
 * certainty：公開ランキングの確かさ（法律ID → 高・中・低）。政党ランキングに印として出す。
 */
export type MemberInputs = { involvements: string; publish: string; loss: string; enacted: string; votes: string; opposing?: string; autoInvolvements?: string; autoVotes?: string; listed?: string[];
  voteParties?: string; certainty?: Record<string, string>;
  /** 閣法の所管の省庁（scripts/build_ministry_bills.py の data/derived/ministry-v1/cabinet-bills.csv）。役職の帳簿を省庁の帳簿として見せる。 */
  ministries?: string;
  /** 税の帳簿（scripts/build_tax_ledger.py の data/derived/tax-v1/consumption-tax.csv）。 */
  taxLedger?: string;
  /** 省庁の抵抗の件数（data/derived/org-ledger-v1/ministry-resistance.csv）。 */
  resistance?: string;
  /** 団体の立場（data/derived/org-ledger-v1/org-stances.csv）。 */
  orgStances?: string };

/** 参議院の会派名を系統に分ける（会派は合流・改称が多いので、名前の一部で寄せる。上から順に当てる）。 */
const BLOCS: [RegExp, string][] = [[/自由民主/, '自民'], [/公明/, '公明'], [/立憲/, '立憲'], [/共産/, '共産'], [/社会民主|社民/, '社民'], [/国民民主/, '国民民主'],
  [/民主党|民進|民友/, '民主系'], [/維新/, '維新'], [/れいわ/, 'れいわ'], [/参政/, '参政']];
export const blocOf = (party: string): string => BLOCS.find(([re]) => re.test(party))?.[1] ?? 'その他';
const normName = (s: string): string => s.replace(/[\s　]/g, '');

/** 人物ID（無い古い一覧では氏名）。集計のキーはこれで、表示の氏名とは別に持つ。 */
const personKey = (r: Record<string, string>): string => r['人物ID'] || r['氏名'];

const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const sub = (a: Range, b: Range): Range => ({ low: a.low - b.low, median: a.median - b.median, high: a.high - b.high });
/** 割合を掛けて円に丸める（役職の帳簿は行動の分との差で作るので、合計は配った額のまま）。 */
const scaleRange = (r: Range, x: number): Range => ({ low: Math.round(r.low * x), median: Math.round(r.median * x), high: Math.round(r.high * x) });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });
const ordered = (r: Range): Range => ({ low: Math.min(r.low, r.high), median: r.median, high: Math.max(r.low, r.high) });
// 便益は負で入っているので、向きをそろえる（中央値が負なら幅ごと符号を返す）。幅が0をまたぐ額でも下限と上限が入れ替わらない。
const magnitude = (r: Range): Range => r.median < 0 ? ordered({ low: -r.high, median: -r.median, high: -r.low }) : ordered(r);

/** 「平成30年 4月18日」を 2018-04-18 に。 */
export function warekiDate(text: string): string {
  const m = /(平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日/.exec(text);
  if (!m) return '';
  const y = (m[2] === '元' ? 1 : Number(m[2])) + (m[1] === '平成' ? 1988 : 2018);
  return `${y}-${m[3].padStart(2, '0')}-${m[4].padStart(2, '0')}`;
}

/**
 * 判定表の R3（コロナ期と分離できない）の法律は配らない。元の窓の額はコロナ期の落ち込みをそのまま含み、その法律の効果ではない
 * （ユーザー 2026-10-24、設計決定0014）。公開ランキングでも確かさを参考にしている。
 */
/** 議案の経過の会派の欄（「自由民主党; 公明党」）を一覧に。 */
const partyList = (text: string | undefined): string[] => (text ?? '').split(/[;；]/).map(x => x.trim()).filter(Boolean);

export const covidHeld = (p: Record<string, string>): boolean => p['判定表の行'] === 'R3';

export function buildMembers(input: MemberInputs): PublicMembers {
  const publish = parseCsv(input.publish);
  const loss = new Map(parseCsv(input.loss).map(r => [r.id, r]));
  const enacted = new Map(parseCsv(input.enacted).map(r => [`${r['種別']}-${r['提出回次']}-${r['番号']}`, r]));
  const votes = new Map([...parseCsv(input.votes), ...(input.autoVotes ? parseCsv(input.autoVotes) : [])].map(r => [r['法律ID'], r]));
  const rows = [...parseCsv(input.involvements), ...(input.autoInvolvements ? parseCsv(input.autoInvolvements) : [])];
  for (const r of rows) {
    if (!ACTIONS.includes(r['行動'] as Action) || !POSITIONS.includes(r['立場区分'] as Position)) throw new Error(`行動または立場が不明です: ${r['法律ID']} ${r['行動']} ${r['立場区分']}`);
    if (r['算入'] === 'はい' && !/^https:\/\/(kokkai\.ndl\.go\.jp|www\.sangiin\.go\.jp|www\.shugiin\.go\.jp)\//.test(r['証拠URL'])) throw new Error(`算入の行に一次資料の URL がありません: ${r['法律ID']}`);
  }
  const counted = rows.filter(r => r['算入'] === 'はい');
  const opposing = input.opposing ? parseCsv(input.opposing).filter(r => r['算入'] === 'はい') : [];
  for (const r of opposing) if (!r['証拠URL'].startsWith('https://www.sangiin.go.jp/')) throw new Error(`反対票の行に参議院の投票の URL がありません: ${r['法律ID']}`);
  const involvedLaws = new Set(counted.map(r => r['法律ID']));

  type Entry = { law: Law; full: Range; observationLaws: number; row: Record<string, string>; text: string; game: LawGame; vote: Record<string, string>; bill: Record<string, string>; opposers: string[] };
  const entries: Entry[] = [];
  // 同じ観測（同じ観測グループ・同じ期間・同じ額の幅＝同じ額の系列・同じ窓の計算）を共有する法律の本数。観測の額を本数で割ってから配り、同じ差を何度も数えない。
  // 期間は公開ランキング（build_public_ranking.py）と同じく、額の文に書かれた窓か、無ければ損失表の単位（開始後N年の累積）から決める。
  const observationKey = (l: Record<string, string>, p: Record<string, string>) => {
    const text = /（円、(?:[^）]*?、)?(\d{4})〜(\d{4})年/.exec(p['損失または便益']);
    const unit = /開始後(\d+)年の累積、名目は開始前最後の年(\d{4})年/.exec(l['単位']);
    const window = text ? `${text[1]}〜${text[2]}` : unit ? `${Number(unit[2]) + 1}〜${Number(unit[2]) + Number(unit[1])}` : l['単位'];
    const a = parseAmount(p['損失または便益'])!;
    return [l['観測グループ'], window, a.low, a.median, a.high].join('|');
  };
  const observationLaws = new Map<string, number>();
  const listed = input.listed ? new Set(input.listed) : null;
  for (const p of publish) {
    const l = loss.get(p.id);
    const amount = parseAmount(p['損失または便益']);
    if (!l || !l['損失または便益の額'] || l['参考フラグ'] === '参考' || !amount || (listed && !listed.has(p.id)) || covidHeld(p)) continue;
    const key = observationKey(l, p);
    observationLaws.set(key, (observationLaws.get(key) ?? 0) + 1);
  }
  for (const p of publish) {
    const l = loss.get(p.id);
    const amount = parseAmount(p['損失または便益']);
    if (!l || !l['損失または便益の額'] || l['参考フラグ'] === '参考' || !amount || !involvedLaws.has(p.id) || covidHeld(p)) continue;
    const vote = votes.get(p.id);
    if (!vote || !vote.URL.startsWith('https://www.sangiin.go.jp/')) throw new Error(`参議院の投票の記録がありません: ${p.id}`);
    const bill = enacted.get(p.id);
    if (!bill?.['経過URL']?.startsWith('https://www.shugiin.go.jp/')) throw new Error(`議案の経過 URL がありません: ${p.id}`);
    const mine = counted.filter(r => r['法律ID'] === p.id);
    const unique = (a: Action) => [...new Set(mine.filter(r => r['行動'] === a).map(personKey))];
    const game: LawGame = { proposers: unique('decide'), voters: unique('vote'), chairs: unique('chair'), yes: Number(vote['賛成']), no: Number(vote['反対']) };
    const side = p['側'].startsWith('国士側') ? 'benefit' : 'loss';
    const n = Math.max(1, observationLaws.get(observationKey(l, p)) ?? 0);
    const split = splitRange(amount, n);
    const opposers = [...new Set(opposing.filter(r => r['法律ID'] === p.id).map(personKey))].filter(id => !game.voters.includes(id));
    entries.push({ law: { lawId: p.id, title: p['題名'], side, publishable: p['公開可否'] === '公開可', group: l['観測グループ'], amount: split }, full: amount, observationLaws: n, row: p, text: p['損失または便益'], game, vote, bill, opposers });
  }

  // 便益は額が負で入っているので、配分の符号をそのまま使い、損失・貢献に分ける。
  type Row = { entry: Entry; fraction: number; roles: Partial<Record<CausalRole, number>>; share: Range; office: Range; direction: 'with' | 'against' };
  type Tot = { loss: Range; credit: Range; office: { loss: Range; credit: Range }; groups: Map<string, number>; laws: Row[] };
  const blank = (): Tot => ({ loss: zero(), credit: zero(), office: { loss: zero(), credit: zero() }, groups: new Map(), laws: [] });
  const totals = new Map<CausalVariant, Map<string, Tot>>();
  const lawOut: PublicMemberLaw[] = [];
  const partyBook = new Map<string, PartyLedger>();
  const ministryOf = new Map(input.ministries ? parseCsv(input.ministries).filter(r => r['所管_今']).map(r => [r['法律ID'], r['所管_今']]) : []);
  const ministryBook = new Map<string, PartyLedger>();
  for (const variant of CAUSAL_VARIANTS) {
    const byPerson = new Map<string, Tot>();
    for (const entry of entries) {
      const out = allocateLaw(entry.law.amount, entry.game, variant);
      const cabinet = entry.law.lawId.startsWith('閣法');
      for (const r of out.rows) {
        const t = byPerson.get(r.personId) ?? blank();
        const mag = magnitude(r.share);
        // 閣法の提出者の分は役職の帳簿へ（担当として出しただけで、本人が推した行動かは分からない。設計決定0014）。
        const officePart = cabinet && r.fraction > 0 ? (r.roles.proposer ?? 0) / r.fraction : 0;
        const office = scaleRange(mag, officePart), action = sub(mag, office);
        if (entry.law.side === 'loss') { t.loss = add(t.loss, action); t.office.loss = add(t.office.loss, office); }
        else { t.credit = add(t.credit, action); t.office.credit = add(t.office.credit, office); }
        if (r.fraction > 0) t.groups.set(entry.law.group, (t.groups.get(entry.law.group) ?? 0) + 1);
        t.laws.push({ entry, fraction: r.fraction, roles: r.roles, share: action, office, direction: 'with' });
        byPerson.set(r.personId, t);
      }
      // 参議院本会議で反対した人：賛成1票と同じ割合を、向きを逆にして配る（止めようとした行動。法律の額の合計とは別に数える）。
      for (const id of entry.opposers) {
        const t = byPerson.get(id) ?? blank();
        const mag = magnitude(scaleRange(entry.law.amount, out.shares.vote));
        if (entry.law.side === 'loss') t.credit = add(t.credit, mag); else t.loss = add(t.loss, mag);
        if (out.shares.vote > 0) t.groups.set(entry.law.group, (t.groups.get(entry.law.group) ?? 0) + 1);
        t.laws.push({ entry, fraction: out.shares.vote, roles: { oppose: out.shares.vote }, share: mag, office: zero(), direction: 'against' });
        byPerson.set(id, t);
      }
      if (variant === 'base' && cabinet && ministryOf.has(entry.law.lawId)) {
        // 省庁の帳簿：この法律の役職の帳簿の分（閣法の提出者の分）を、所管の省庁に置く。
        const office = out.rows.reduce((s, r) => add(s, r.fraction > 0 ? scaleRange(magnitude(r.share), (r.roles.proposer ?? 0) / r.fraction) : zero()), zero());
        const name = ministryOf.get(entry.law.lawId)!;
        const effect: 'bad' | 'good' = entry.law.side === 'loss' ? 'bad' : 'good';
        const t = ministryBook.get(name) ?? { name, bad: zero(), good: zero(), net: zero(), laws: [] };
        if (effect === 'bad') t.bad = add(t.bad, office); else t.good = add(t.good, office);
        t.laws.push({ lawId: entry.law.lawId, side: entry.law.side, direction: 'with', effect, share: office });
        ministryBook.set(name, t);
      }
      if (variant === 'base') {
        const { law, full, observationLaws: shared, row, text, game, vote, bill } = entry;
        const attributed = magnitude(out.rows.reduce((s, r) => add(s, r.share), zero()));
        lawOut.push({ id: law.lawId, title: law.title, side: law.side, amount: magnitude(full), observationLaws: shared, publishable: law.publishable,
          confidence: confidenceLabel(row['判定表の行'], text), judgement: row['判定表の行'], reason: row['理由'], group: law.group,
          persons: out.rows.length, attributed, source: bill['経過URL'], enactedOn: warekiDate(bill['公布日']),
          game: { cabinet: law.lawId.startsWith('閣法'), opposers: entry.opposers.length, proposers: game.proposers.length, proposerKind: law.lawId.startsWith('閣法') ? '内閣（閣議決定に関わった大臣）' : '発議者', vetoShare: out.shares.veto, voteShare: out.shares.vote,
            yes: game.yes, no: game.no, quota: out.shares.q, voters: game.voters.length, voteUrl: vote.URL, voteDate: vote['日付'], chairs: game.chairs.length, names: { proposers: game.proposers, voters: game.voters, chairs: game.chairs, opposers: entry.opposers },
            parties: partyList(bill['賛成会派_衆']), opposingParties: partyList(bill['反対会派_衆']), party: magnitude(out.party), unidentified: magnitude(out.unidentified) } });
        // 会派の帳簿：賛成会派の組の分を会派の数で等分し、反対会派には同じ額を向きを逆にして置く。
        const withParties = partyList(bill['賛成会派_衆']);
        if (withParties.length) {
          const each = scaleRange(magnitude(out.party), 1 / withParties.length);
          const put = (name: string, direction: 'with' | 'against') => {
            const effect: 'bad' | 'good' = (law.side === 'loss') === (direction === 'with') ? 'bad' : 'good';
            const t = partyBook.get(name) ?? { name, bad: zero(), good: zero(), net: zero(), laws: [] };
            if (effect === 'bad') t.bad = add(t.bad, each); else t.good = add(t.good, each);
            t.laws.push({ lawId: law.lawId, side: law.side, direction, effect, share: each });
            partyBook.set(name, t);
          };
          for (const name of withParties) put(name, 'with');
          for (const name of partyList(bill['反対会派_衆'])) put(name, 'against');
        }
      }
    }
    // 成立を左右しない行動（質疑・修正案など）だけの人も、0円として載せる。
    for (const entry of entries) for (const name of new Set(counted.filter(r => r['法律ID'] === entry.law.lawId).map(personKey))) {
      const t = byPerson.get(name) ?? blank();
      if (!t.laws.some(l => l.entry === entry)) t.laws.push({ entry, fraction: 0, roles: {}, share: zero(), office: zero(), direction: 'with' });
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
  const evidenceOf = (lawId: string, id: string) => counted.filter(v => v['法律ID'] === lawId && personKey(v) === id)
    .map(v => ({ action: v['行動'] as Action, actionLabel: ACTION_LABEL[v['行動'] as Action], title: v['当時の肩書'], house: v['院'], date: v['日付'], url: v['証拠URL'] }))
    .sort((a, b) => ACTION_WEIGHT[b.action] - ACTION_WEIGHT[a.action] || a.date.localeCompare(b.date));
  const nameOf = new Map(counted.map(r => [personKey(r), r['氏名']]));
  const members: PublicMember[] = [...totals.get('base')!].map(([id, t]) => {
    const r = baseRank.get(id)!, c = chairRank.get(id)!;
    const move = Math.abs(r.rank - c.rank);
    const laws = t.laws.map(({ entry, fraction, roles, share, office, direction }) => {
      const all = evidenceOf(entry.law.lawId, id);
      const counts = (e: MemberEvidence) => { const role = ROLE_OF[e.action]; return role !== undefined && roles[role] !== undefined; };
      const opposed: MemberEvidence[] = direction === 'against' ? [{ action: 'vote', actionLabel: '参議院本会議で反対', title: '', house: '参議院', date: entry.vote['日付'], url: entry.vote.URL }] : [];
      const effect: MemberLaw['effect'] = (entry.law.side === 'loss') === (direction === 'with') ? 'bad' : 'good';
      return { lawId: entry.law.lawId, side: entry.law.side, roles, fraction, share, direction, effect, office, evidence: [...opposed, ...all.filter(counts)], context: all.filter(e => !counts(e)) };
    }).sort((a, b) => b.share.median + b.office.median - a.share.median - a.office.median);
    return { id, name: nameOf.get(id) ?? id, rank: r.rank, net: netOf(t), loss: t.loss, credit: t.credit, office: t.office,
      sensitivity: { chairVetoRank: c.rank, chairVetoNet: c.net, maxMove: move, flagged: move >= RANK_MOVE_FLAG },
      overlappingGroups: [...t.groups].filter(([, n]) => n > 1).map(([g]) => g), laws };
  }).sort((a, b) => a.rank - b.rank);
  const partyRanking = input.voteParties ? rankParties(members, entries, parseCsv(input.voteParties), input.certainty ?? {}) : undefined;
  const lawIds = new Set(entries.map(e => e.law.lawId));
  const inLaws = counted.filter(r => lawIds.has(r['法律ID']));
  const roleRows = inLaws.filter(r => r['行動'] === 'decide' || r['行動'] === 'vote');
  return {
    schema: 'public-members/v2',
    rules: ['allocation-v1', 'causal-shapley-v1', 'loss-rule-v1', 'benefit-rule-v1.2'],
    laws: lawOut,
    members,
    parties: [...partyBook.values()].map(t => ({ ...t, net: ordered({ low: t.good.low - t.bad.high, median: t.good.median - t.bad.median, high: t.good.high - t.bad.low }) }))
      .sort((a, b) => a.net.median - b.net.median || a.name.localeCompare(b.name)),
    ...(partyRanking ? { partyRanking } : {}),
    ...(input.ministries ? { ministries: [...ministryBook.values()].map(t => ({ ...t, net: ordered({ low: t.good.low - t.bad.high, median: t.good.median - t.bad.median, high: t.good.high - t.bad.low }) }))
      .sort((a, b) => a.net.median / a.laws.length - b.net.median / b.laws.length || a.name.localeCompare(b.name)) } : {}),
    ...(input.taxLedger ? { taxLedger: taxLedgerOf(input.taxLedger) } : {}),
    ...(input.resistance ? { resistance: parseCsv(input.resistance).map(r => ({ ministry: r['省庁'], total: Number(r['抵抗の件数']), refusals: Number(r['対応不可']),
      answers: Number(r['ホットラインの回答']), hearings: Number(r['ヒアリングで反対・慎重']), followups: Number(r['フォローアップで反対・慎重・未措置']) })) } : {}),
    ...(input.orgStances ? { orgStances: parseCsv(input.orgStances).map(r => ({ name: r['団体'], kind: r['区分'], against: Number(r['反対']), careful: Number(r['慎重']),
      conditional: Number(r['条件付き賛成']), support: Number(r['賛成']), technologies: r['関連技術'] ? r['関連技術'].split('、') : [] })) } : {}),
    counts: { members: members.length, loss: members.filter(m => m.net.median < 0).length, benefit: members.filter(m => m.net.median > 0).length, zero: members.filter(m => m.net.median === 0).length,
      involvements: roleRows.length, context: inLaws.length - roleRows.length, excluded: rows.filter(r => r['算入'] !== 'はい' && lawIds.has(r['法律ID'])).length },
  };
}

/** 政党ランキング：議員ごとの行動の額（役職の帳簿は入れない）を、その法律の参議院の採決の時の会派の系統で足す。 */
function rankParties(members: PublicMember[], entries: { law: { lawId: string; side: Law['side'] }; vote: Record<string, string> }[], roster: Record<string, string>[], certainty: Record<string, string>): PartyRanking {
  const partyAt = new Map(roster.map(r => [`${r['投票ID']}|${normName(r['議員名'])}`, r['会派']]));
  const lawOf = new Map(entries.map(e => [e.law.lawId, e]));
  type Acc = { parties: Set<string>; people: Set<string>; laws: Set<string>; yes: Set<string>; yesLoss: Set<string>; no: Set<string>; bad: Range; good: Range; votes: number };
  const acc = new Map<string, Acc>();
  const lost = { people: new Set<string>(), bad: zero(), good: zero() };
  for (const m of members) for (const l of m.laws) {
    if (l.fraction === 0 && l.direction === 'with' && l.share.median === 0) continue;
    const e = lawOf.get(l.lawId);
    const party = e ? partyAt.get(`${e.vote['投票ID']}|${normName(m.name)}`) : undefined;
    if (!party) {
      lost.people.add(m.id);
      if (l.effect === 'bad') lost.bad = add(lost.bad, l.share); else lost.good = add(lost.good, l.share);
      continue;
    }
    const bloc = blocOf(party);
    const a = acc.get(bloc) ?? { parties: new Set(), people: new Set(), laws: new Set(), yes: new Set(), yesLoss: new Set(), no: new Set(), bad: zero(), good: zero(), votes: 0 };
    a.parties.add(party); a.people.add(m.id); a.laws.add(l.lawId); a.votes += 1;
    if (l.direction === 'with') { a.yes.add(l.lawId); if (l.side === 'loss') a.yesLoss.add(l.lawId); } else a.no.add(l.lawId);
    if (l.effect === 'bad') a.bad = add(a.bad, l.share); else a.good = add(a.good, l.share);
    acc.set(bloc, a);
  }
  const net = (bad: Range, good: Range): Range => ordered({ low: good.low - bad.high, median: good.median - bad.median, high: good.high - bad.low });
  const blocs = [...acc].map(([bloc, a]): PartyBloc => {
    const n = net(a.bad, a.good);
    const cert: Record<string, number> = {};
    for (const id of a.laws) { const c = certainty[id] ?? '不明'; cert[c] = (cert[c] ?? 0) + 1; }
    return { bloc, parties: [...a.parties].sort(), people: a.people.size, laws: a.laws.size, yesLaws: a.yes.size, noLaws: a.no.size,
      lossShareOfYes: a.yes.size ? a.yesLoss.size / a.yes.size : 0, certainty: cert, bad: a.bad, good: a.good, net: n,
      votes: a.votes, perPerson: Math.round(n.median / a.people.size), perLaw: Math.round(n.median / a.laws.size), perVote: Math.round(n.median / a.votes) };
  }).sort((a, b) => a.perPerson - b.perPerson || a.bloc.localeCompare(b.bloc));
  const dates = entries.map(e => e.vote['日付']).filter(Boolean).sort();
  return { blocs, from: dates[0] ?? '', to: dates[dates.length - 1] ?? '', unmatched: { people: lost.people.size, net: net(lost.bad, lost.good) } };
}
