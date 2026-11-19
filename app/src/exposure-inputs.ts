/**
 * 曝露ランキング（exposure-ranking.ts）の入力を、実データの CSV から作る純関数。ファイルも通信も読まない。
 *
 * 群：産業×年。額は OECD 表6の同産業・その年の、比較国との伸びの差×前年の名目付加価値（data/derived/exposure-v1/industry-year.csv、
 * scripts/build_industry_year_gap.py。記述であって因果ではない）。窓は1年ずつずれた累積で同じ年を何度も数えるので、足す単位は産業×年にする。
 * 法律は macro.csv の（結果=額・産業≠COVID）の窓「1998〜2007年」を年に展開し、その産業の各年の群に属する。COVID は支出の費用便益で OECD の差ではないので除く。
 * industry-year.csv に行が無い産業×年は群を作らず、counts に数える。
 * 全産業（_T）は産業別と同じ額を重ねて数えるので、足さずに別欄（wholeEconomy）にする。
 *
 * 関与：群に属する法律だけを、法律×年ごとに置く（groupId が産業×年、lawId は法律 ID のまま）。属さない法律の行は数えて捨てる。
 * - 衆法・参法の提出者 → proposer。enacted.csv から members-reference.ts と同じ読み方で取る（involvements*.csv は使わない）：
 *   委員会提出（COMMITTEE）は置かない／「提出者一覧」があれば全員（normName）を weight 1／無ければ parseProposer(提出者) の代表者を weight 1、
 *   名前の分からない「外N名」は actorKind 'none'・weight N（その分は未配分。理由「名前の分からない提出者（外N名）」）。
 *   人は ledger.resolve(名前, 衆法なら 衆議院・参法なら 参議院)。同姓同名で結べなければ 'none'（理由「同姓同名で人物台帳に結べない提出者」）。
 * - 賛成・反対は投票の一次資料から取る。
 *   参議院：votes_index.csv の、議決日（enacted.csv の 議決日_参）の投票から pickVote（members-reference.ts と同じ）で1つに決まったものの
 *   ballots の賛否（Y → yes、N → no。棄権など Y・N 以外は置かない）。人は 議員ID → members.csv の氏名 → PersonLedger.resolve(氏名, '参議院')。
 *   同姓同名で結べない人は actorKind: 'none'（重みだけ枠に入れ、その分は未配分に積む。ほかの人へ寄せない）。
 *   衆議院：enacted.csv の 賛成会派_衆・反対会派_衆（「; 」区切り）を会派（party）に、weight 1 で均等に置く。
 *   議席数の表が無いための取り決めで、会派の大きさを無視する限界がある。会派名は記録の表記のまま。
 *   参議院で個人票が決まらない法律は、参議院の会派賛否のデータが無いので未配分のまま（counts に数える）。
 * - 閣法の提出（decide）は使わず、提出時の閣僚（cabinet-members.ts。総理大臣が会期中に替わる回次は付託日で決め、決められない法律は置かない）全員に cabinet と proposer の両方を置く
 *   （閣法は全閣僚へ：閣議決定0.2＋発議0.4。2026-11-19 確定）。involvements に記録があるかどうかに依らない。
 * - 法律が1本だけの産業×年の群には置かない。群の差がそのままその法律の額になり、群の差を法律へ配ることになるため（設計確定 v2.1）。枠は未配分に積まれる。
 * - 閣僚の1人でも人物台帳に結べない閣法は、cabinet と proposer を置かない（結べた人だけに置くと、結べない人の枠がほかの閣僚へ寄るため）。枠は未配分に積まれる。
 * - 同じ（法律・役割・院・配り先）の重複は1つにする（年ごとに増やさない）。
 */
import type { ExposureGroup, ExposureRanking, ExposureRow, House, Involvement, ExposureRole } from './exposure-ranking';
import { cabinetForBill, normName } from './cabinet-members';
import { COMMITTEE, parseProposer, pickVote } from './members-reference';
import { warekiDate } from './members-build';
import { parseCsv } from './impact-batch';
import { PersonLedger } from './person-id';

export type ExposureSources = {
  macro: string; industryYear: string; enacted: string; cabinet: string; persons: string; roster: string;
  votesIndex: string; sangiinMembers: string; ballots: string[];
};
export type ExposureCounts = {
  /** 産業別の群（産業×年）の数と、全産業（_T）の群の数。 */
  groups: number;
  wholeEconomyGroups: number;
  /** 窓が覆うのに industry-year.csv に行が無く、群を作れなかった産業×年の数。 */
  groupsWithoutGap: number;
  /** 群に属する法律の数（全産業を含む）。 */
  laws: number;
  /** 関与を1つ以上置けた法律の数。 */
  lawsWithAnyInvolvement: number;
  /** 群に属する閣法の数と、うち閣僚が決まらない回次（総理大臣が会期中に替わる等）の閣法・閣僚の全員が台帳に結べない閣法の数。 */
  cabinetLaws: number;
  cabinetLawsUndetermined: number;
  /** 閣僚の1人以上が台帳に結べず、cabinet と proposer を置かなかった閣法の数。 */
  cabinetLawsUnresolved: number;
  /** 台帳に結べなかった閣僚の延べ数（閣法ごと）。 */
  cabinetUnresolvedMinisters: number;
  /** 法律が1本だけの群の数（関与を置かない）。 */
  singleLawGroups: number;
  /** 参議院の投票：議決日（参）が読める法律・投票が1つに決まった法律（votesMatched）・決まらなかった法律（votesNotFound）。「議決日が読める X 本中 votesMatched 本」。 */
  votesLaws: number;
  votesNoDate: number;
  votesMatched: number;
  votesNotFound: number;
  /** 衆議院の賛成会派・反対会派の記録がある法律の数。 */
  lowerYesLaws: number;
  lowerNoLaws: number;
  /** 置いた関与（法律×役割×院×配り先。年に展開する前、重複を除いたあと）の行数。 */
  yesRows: number;
  noRows: number;
  /** うち同姓同名で台帳に結べず、配り先なしで置いた参議院の票。 */
  unresolvedVoteRows: number;
  /** 衆議院の会派の賛成・反対の行数。 */
  lowerYesRows: number;
  lowerNoRows: number;
  /** 衆法・参法の提出者のうち人に置いた行数。 */
  proposerRows: number;
  /** 閣僚に置いた cabinet の行数（proposer も同じ数だけ置く）。 */
  cabinetRows: number;
  /** 衆法・参法のうち提出者を置いた法律の数、委員会提出で置かなかった法律の数、名前の分からない提出者（外N名）の延べ人数、台帳に結べなかった提出者の行数。 */
  proposerLaws: number;
  committeeLaws: number;
  unnamedProposers: number;
  unresolvedProposerRows: number;
  skipped: {
    /** 関与を置こうとして、置き場（法律が2本以上の群）が無かった法律の数。 */
    singleLawGroup: number;
    /** 同じ（法律・役割・院・配り先）の重複。 */
    duplicates: number;
  };
};
export type ExposureBucket = { groups: ExposureGroup[]; involvements: Involvement[] };
/** industry：産業別（本体の順位に使う）。wholeEconomy：全産業（_T。産業別と同じ額を重ねて数えるので足さず、別欄にする）。 */
export type ExposureInputs = { industry: ExposureBucket; wholeEconomy: ExposureBucket; counts: ExposureCounts };

const LAW_ID = /^(閣法|衆法|参法)-(\d+)-(\d+)$/;
const WINDOW = /^(\d{4})〜(\d{4})年$/;
const WHOLE = '_T';

export function buildExposureInputs(src: ExposureSources): ExposureInputs {
  // 産業×年の額（industry-year.csv）。
  const gap = new Map<string, { diff: { low: number; median: number; high: number }; countries: string; nominal: string }>();
  for (const r of parseCsv(src.industryYear)) {
    const num = (k: string) => {
      const v = Number(r[k]);
      if (r[k] === '' || !Number.isFinite(v)) throw new Error(`額が数でない：${r['産業']} ${r['年']} ${k}`);
      return v;
    };
    const diff = { low: num('low'), median: num('median'), high: num('high') };
    if (!(diff.low <= diff.median && diff.median <= diff.high)) throw new Error(`額の幅が low≤median≤high でない：${r['産業']} ${r['年']}`);
    const id = `${r['産業']}|${r['年']}`;
    if (gap.has(id)) throw new Error(`産業×年が重複：${id}`);
    gap.set(id, { diff, countries: r['比較国'], nominal: r['前年の名目付加価値_百万円'] });
  }
  // 法律 → (産業, 年の一覧)。結果=額・産業≠COVID の行だけ。
  const lawYears = new Map<string, { industry: string; years: number[] }>();
  for (const r of parseCsv(src.macro)) {
    if (r['結果'] !== '額' || r['産業'] === 'COVID') continue;
    const m = WINDOW.exec(r['窓']);
    if (!m) throw new Error(`窓の形が読めない：${r['id']} ${r['窓']}`);
    const prev = lawYears.get(r['id']);
    if (prev && prev.industry !== r['産業']) throw new Error(`同じ法律が別の産業の群にある：${r['id']}`);
    // 同じ法律の窓が複数の行に分かれていても、覆う年の和集合を取る（年を足す単位なので、窓の分け方で合計は変わらない）。
    const years = new Set(prev?.years ?? []);
    for (let y = Number(m[1]); y <= Number(m[2]); y++) years.add(y);
    lawYears.set(r['id'], { industry: r['産業'], years: [...years].sort((a, b) => a - b) });
  }
  // 群：その産業×年を窓が覆う法律の本数（lawCount）。行の無い産業×年は群を作らない。
  const lawsOf = new Map<string, Set<string>>();
  const missingGap = new Set<string>();
  for (const [lawId, v] of lawYears) {
    for (const y of v.years) {
      const id = `${v.industry}|${y}`;
      if (!gap.has(id)) { missingGap.add(id); continue; }
      const set = lawsOf.get(id) ?? new Set<string>();
      set.add(lawId);
      lawsOf.set(id, set);
    }
  }
  const groupOf = new Map<string, ExposureGroup>();
  for (const [id, laws] of [...lawsOf].sort((a, b) => a[0].localeCompare(b[0]))) {
    const [industry, year] = id.split('|');
    const g = gap.get(id)!;
    groupOf.set(id, {
      kind: 'group-diff', id, group: industry, window: `${year}年`, diff: g.diff, lawCount: laws.size,
      benchmark: `OECD 表6 同産業（${industry}）の比較国（${g.countries}）の、その年の実質の伸びの差×前年の名目付加価値（${g.nominal}百万円）。開始前の伸びの差は織り込まない`,
    });
  }
  const industryGroups = [...groupOf.values()].filter(g => g.group !== WHOLE);
  const wholeGroups = [...groupOf.values()].filter(g => g.group === WHOLE);
  // 法律 → 関与を置ける群（法律が1本だけの群を除く）と、群の全体。
  const placeable = new Map<string, string[]>();
  const grouped = new Set<string>();
  let singleGroups = 0;
  for (const g of groupOf.values()) if (g.lawCount === 1) singleGroups++;
  for (const [lawId, v] of lawYears) {
    const all = v.years.map(y => `${v.industry}|${y}`).filter(id => groupOf.has(id));
    if (all.length === 0) continue;
    grouped.add(lawId);
    placeable.set(lawId, all.filter(id => groupOf.get(id)!.lawCount > 1));
  }

  const counts: ExposureCounts = {
    groups: industryGroups.length, wholeEconomyGroups: wholeGroups.length, groupsWithoutGap: missingGap.size, laws: grouped.size, lawsWithAnyInvolvement: 0,
    cabinetLaws: 0, cabinetLawsUndetermined: 0, cabinetLawsUnresolved: 0, cabinetUnresolvedMinisters: 0, singleLawGroups: singleGroups,
    votesLaws: 0, votesNoDate: 0, votesMatched: 0, votesNotFound: 0, lowerYesLaws: 0, lowerNoLaws: 0,
    yesRows: 0, noRows: 0, unresolvedVoteRows: 0, lowerYesRows: 0, lowerNoRows: 0, proposerRows: 0, cabinetRows: 0,
    proposerLaws: 0, committeeLaws: 0, unnamedProposers: 0, unresolvedProposerRows: 0,
    skipped: { singleLawGroup: 0, duplicates: 0 },
  };
  const out = { industry: { groups: industryGroups, involvements: [] as Involvement[] }, wholeEconomy: { groups: wholeGroups, involvements: [] as Involvement[] } };
  const enactedRows = parseCsv(src.enacted);
  const seen = new Set<string>();
  const withInvolvement = new Set<string>();
  const noPlace = new Set<string>();
  /** 法律×役割×院×配り先を1つ置き、群（産業×年）ごとに展開する。置けたら true。 */
  const place = (lawId: string, role: ExposureRole, actorKind: Involvement['actorKind'], actorId: string, dedupeId: string, house?: House, extra: { weight?: number; noneReason?: string } = {}): boolean => {
    const key = `${lawId}\u0000${role}\u0000${house ?? ''}\u0000${actorKind}\u0000${dedupeId}`;
    if (seen.has(key)) { counts.skipped.duplicates++; return false; }
    seen.add(key);
    const ids = placeable.get(lawId)!;
    if (ids.length === 0) { noPlace.add(lawId); return false; }
    const bucket = lawYears.get(lawId)!.industry === WHOLE ? out.wholeEconomy : out.industry;
    for (const groupId of ids) bucket.involvements.push({ actorKind, actorId, groupId, lawId, role, weight: extra.weight ?? 1, ...(house ? { house } : {}), ...(extra.noneReason ? { noneReason: extra.noneReason } : {}) });
    withInvolvement.add(lawId);
    return true;
  };

  // 賛成・反対：参議院は個人票（一次資料）、衆議院は会派。
  const ledger = new PersonLedger(src.persons, src.roster);
  const byDay = new Map<string, Record<string, string>[]>();
  for (const v of parseCsv(src.votesIndex)) { const l = byDay.get(v['投票日']) ?? []; l.push(v); byDay.set(v['投票日'], l); }
  const idName = new Map<string, { name: string; session: number }>();
  for (const r of parseCsv(src.sangiinMembers)) {
    const prev = idName.get(r['議員ID']);
    if (!prev || Number(r['回次']) >= prev.session) idName.set(r['議員ID'], { name: normName(r['議員名']), session: Number(r['回次']) });
  }
  const enactedById = new Map(enactedRows.map(r => [`${r['種別']}-${r['提出回次']}-${r['番号']}`, r]));
  const voteOf = new Map<string, string>();
  for (const lawId of [...grouped].sort()) {
    const b = enactedById.get(lawId);
    if (!b) continue;
    const day = warekiDate(b['議決日_参']);
    if (!day) { counts.votesNoDate++; continue; }
    counts.votesLaws++;
    const vote = pickVote(b['題名'], byDay.get(day) ?? []);
    if (vote) { counts.votesMatched++; voteOf.set(lawId, vote['投票ID']); } else counts.votesNotFound++;
  }
  const needed = new Set(voteOf.values());
  const ballotsOf = new Map<string, { id: string; yes: boolean }[]>();
  for (const text of src.ballots) for (const r of parseCsv(text)) {
    if ((r['賛否'] !== 'Y' && r['賛否'] !== 'N') || !needed.has(r['投票ID'])) continue;
    const l = ballotsOf.get(r['投票ID']) ?? [];
    l.push({ id: r['議員ID'], yes: r['賛否'] === 'Y' });
    ballotsOf.set(r['投票ID'], l);
  }
  const splitParties = (t: string | undefined) => (t ?? '').split(/[;；]/).map(x => x.trim()).filter(Boolean);
  for (const lawId of [...grouped].sort()) {
    const voteId = voteOf.get(lawId);
    for (const b of voteId ? ballotsOf.get(voteId) ?? [] : []) {
      const role: ExposureRole = b.yes ? 'yes' : 'no';
      const who = idName.get(b.id);
      const res = who ? ledger.resolve(who.name, '参議院') : null;
      const placed = res ? place(lawId, role, 'person', res.id, res.id, 'upper') : place(lawId, role, 'none', '', `未特定:${b.id}`, 'upper');
      if (!placed) continue;
      if (role === 'yes') counts.yesRows++; else counts.noRows++;
      if (!res) counts.unresolvedVoteRows++;
    }
    const e = enactedById.get(lawId);
    if (!e) continue;
    const lowerYes = splitParties(e['賛成会派_衆']);
    const lowerNo = splitParties(e['反対会派_衆']);
    if (lowerYes.length) counts.lowerYesLaws++;
    if (lowerNo.length) counts.lowerNoLaws++;
    for (const name of lowerYes) if (place(lawId, 'yes', 'party', name, name, 'lower')) counts.lowerYesRows++;
    for (const name of lowerNo) if (place(lawId, 'no', 'party', name, name, 'lower')) counts.lowerNoRows++;
  }

  // 衆法・参法の提出者（enacted.csv。members-reference.ts と同じ読み方）。
  const splitNames = (t: string) => t.split(/[;；、,]/).map(normName).filter(Boolean);
  for (const lawId of [...grouped].sort()) {
    if (lawId.startsWith('閣法')) continue;
    const e = enactedById.get(lawId);
    if (!e) continue;
    if (COMMITTEE.test(parseProposer(e['提出者'] ?? '').lead)) { counts.committeeLaws++; continue; }
    const house = lawId.startsWith('参法') ? '参議院' : '衆議院';
    const unresolvedReason = '同姓同名で人物台帳に結べない提出者';
    const named: { name: string; weight: number }[] = [];
    let unnamed = 0;
    if (e['提出者一覧']) for (const name of splitNames(e['提出者一覧'])) named.push({ name, weight: 1 });
    else if (e['提出者']) {
      const p = parseProposer(e['提出者']);
      if (p.lead) named.push({ name: p.lead, weight: 1 });
      unnamed = p.others;
    }
    let any = false;
    for (const { name, weight } of named) {
      const res = ledger.resolve(name, house);
      const placed = res ? place(lawId, 'proposer', 'person', res.id, res.id, undefined, { weight }) : place(lawId, 'proposer', 'none', '', `未特定:${name}`, undefined, { weight, noneReason: unresolvedReason });
      if (!placed) continue;
      any = true;
      if (res) counts.proposerRows++; else counts.unresolvedProposerRows++;
    }
    if (unnamed > 0 && place(lawId, 'proposer', 'none', '', `外${unnamed}名`, undefined, { weight: unnamed, noneReason: `名前の分からない提出者（外${unnamed}名）` })) { any = true; counts.unnamedProposers += unnamed; }
    if (any) counts.proposerLaws++;
  }

  // 閣法：群に属する閣法すべてに、提出した回次の閣僚全員へ cabinet と proposer を置く。
  const cabinetOf = cabinetForBill(enactedRows, parseCsv(src.cabinet));
  const cabinetLawIds = [...grouped].filter(id => id.startsWith('閣法')).sort();
  for (const lawId of cabinetLawIds) {
    counts.cabinetLaws++;
    const bill = enactedById.get(lawId);
    const all = bill ? cabinetOf(bill).names : [];
    if (all.length === 0) { counts.cabinetLawsUndetermined++; continue; }
    const resolved = all.map(n => ledger.resolve(normName(n), '')?.id ?? '');
    const missing = resolved.filter(x => !x).length;
    if (missing > 0) { counts.cabinetUnresolvedMinisters += missing; counts.cabinetLawsUnresolved++; continue; }
    const ids = [...new Set(resolved)];
    for (const id of ids) {
      if (place(lawId, 'cabinet', 'person', id, id)) counts.cabinetRows++;
      place(lawId, 'proposer', 'person', id, id);
    }
  }
  counts.lawsWithAnyInvolvement = withInvolvement.size;
  counts.skipped.singleLawGroup = noPlace.size;
  return { ...out, counts };
}

export const NO_INVOLVEMENT_REASON = '群に属する法律への関与の記録が無い';
export const WHOLE_ECONOMY_ONLY_REASON = '産業別の群への関与の記録が無い（全産業の別欄にある）';
export type LedgerCoverage = { ledger: number; ranked: number; unrankedWithAmount: number; noInvolvement: number; outsideLedger: number };

/**
 * 人物台帳（persons.csv）の全員を people に1回ずつ載せる（完了条件：全員が「点あり」か「点なし＋理由」のどちらか）。
 * 点あり＝tier が数。点なし＝tier が null で unrankedReason に理由。関与の記録が無い人は0円・0本で理由つきの行を足す。
 * 全産業の別欄（wholeEconomy）にだけ関与がある人は、理由を「産業別の群への関与の記録が無い（全産業の別欄にある）」にする。
 * 額の合計（totals）は変わらない。台帳に無い人（当時だけの閣僚など）の行はそのまま残し、人数を coverage に出す。
 */
export function withLedgerPeople(ranking: ExposureRanking, personsCsv: string, wholeEconomy?: ExposureRanking): { ranking: ExposureRanking; coverage: LedgerCoverage } {
  const ledgerIds = [...new Set(parseCsv(personsCsv).map(r => r['人物ID']).filter(Boolean))];
  const ledger = new Set(ledgerIds);
  const have = new Set(ranking.people.map(p => p.actorId));
  if (have.size !== ranking.people.length) throw new Error('people に同じ人が2回いる');
  const onlyWhole = new Set((wholeEconomy?.people ?? []).filter(p => p.laws > 0).map(p => p.actorId));
  const added: ExposureRow[] = ledgerIds.filter(id => !have.has(id)).sort((a, b) => a.localeCompare(b)).map(id => ({
    actorKind: 'person', actorId: id, exposureYen: { low: 0, median: 0, high: 0 }, laws: 0, groups: 0, topThreeShare: 0, cells: [], tier: null,
    unrankedReason: onlyWhole.has(id) ? WHOLE_ECONOMY_ONLY_REASON : NO_INVOLVEMENT_REASON,
  }));
  const inLedger = ranking.people.filter(p => ledger.has(p.actorId));
  const coverage: LedgerCoverage = {
    ledger: ledgerIds.length,
    ranked: inLedger.filter(p => p.tier !== null).length,
    unrankedWithAmount: inLedger.filter(p => p.tier === null).length,
    noInvolvement: added.length,
    outsideLedger: ranking.people.length - inLedger.length,
  };
  return { ranking: { ...ranking, people: [...ranking.people, ...added] }, coverage };
}
