/**
 * 曝露ランキング（exposure-ranking.ts）の入力を、実データの CSV から作る純関数。ファイルも通信も読まない。
 *
 * 群：産業×窓。額は OECD 表6の同産業の比較国との差の累積（記述であって因果ではない）。COVID は支出の費用便益で OECD の差ではないので除く。
 * 関与：群に属する法律だけ。属さない法律の行は数えて捨てる。
 * - 賛成（vote）→ yes。衆法・参法の提出（decide）→ proposer。反対（opposing.csv）→ no。人は人物IDで結ぶ。
 * - 閣法の提出（decide）は使わず、提出した回次の閣僚（cabinet-members.ts）全員に cabinet と proposer の両方を置く
 *   （閣法は全閣僚へ：閣議決定0.2＋発議0.4。2026-11-19 確定）。involvements に記録があるかどうかに依らない。
 * - chair・amend・question は役割の取り決めに無いので使わない。
 * - 委員会提出（提出者が「○○委員長」など）の衆法・参法は人の提出ではないので、proposer を置かない（全議員の表と同じ決まり）。
 * - 法律が1本だけの群には関与を置かない。群の差がそのままその法律の額になり、群の差を法律へ配ることになるため（設計確定 v2.1）。枠は未配分に積まれる。
 * - 閣僚の1人でも人物台帳に結べない閣法は、cabinet と proposer を置かない（結べた人だけに置くと、結べない人の枠がほかの閣僚へ寄るため）。枠は未配分に積まれる。
 * - 会派（party）への配りは今回作らない。衆議院は会派単位の賛否で、参議院は個人票なので、賛成の枠を会派と人でどう分けるかが未決のため。
 *   parties は空のまま。衆議院の賛成は、記録のある個人（involvements の vote）にだけ置く。
 */
import type { ExposureGroup, ExposureRanking, ExposureRow, Involvement, ExposureRole } from './exposure-ranking';
import { cabinetBySession, normName } from './cabinet-members';
import { COMMITTEE, parseProposer } from './members-reference';
import { parseCsv } from './impact-batch';
import { PersonLedger } from './person-id';

export type ExposureSources = {
  macro: string; enacted: string; cabinet: string; persons: string; roster: string;
  involvements: string[]; opposing: string;
};
export type ExposureCounts = {
  /** 群の数。 */
  groups: number;
  /** 群に属する法律の数。 */
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
  /** 置いた関与の行数（重複を除いたあと）。 */
  yesRows: number;
  noRows: number;
  /** 衆法・参法の提出者の行数。 */
  proposerRows: number;
  /** 閣僚に置いた cabinet の行数（proposer も同じ数だけ置く）。 */
  cabinetRows: number;
  skipped: {
    /** 群に属さない法律の行（算入=はい のもの）。 */
    notInGroup: number;
    /** 算入=はい でない行（群に属する法律のもの）。 */
    notCounted: number;
    /** 閣法の decide（閣僚で置き換える）。 */
    cabinetDecide: number;
    /** 委員会提出の衆法・参法の decide。 */
    committeeProposer: number;
    /** 法律が1本だけの群の法律の行（算入=はい のもの）。 */
    singleLawGroup: number;
    chair: number; amend: number; question: number; otherAction: number;
    noPersonId: number;
    /** 同じ（法律・役割・人）の重複。 */
    duplicates: number;
  };
};
export type ExposureInputs = { groups: ExposureGroup[]; involvements: Involvement[]; counts: ExposureCounts };

const LAW_ID = /^(閣法|衆法|参法)-(\d+)-(\d+)$/;

export function buildExposureInputs(src: ExposureSources): ExposureInputs {
  // 群：(産業, 窓)。
  const groupMap = new Map<string, ExposureGroup & { key: string; sig: string }>();
  const lawGroup = new Map<string, string>();
  for (const r of parseCsv(src.macro)) {
    if (r['結果'] !== '額' || r['産業'] === 'COVID') continue;
    const num = (k: string) => {
      const v = Number(r[k]);
      if (r[k] === '' || !Number.isFinite(v)) throw new Error(`額が数でない：${r['id']} ${k}`);
      return v;
    };
    const diff = { low: num('第1四分位'), median: num('中央値'), high: num('第3四分位') };
    if (!(diff.low <= diff.median && diff.median <= diff.high)) throw new Error(`額の幅が low≤median≤high でない：${r['id']}`);
    const id = `${r['産業']}|${r['窓']}`;
    const industryName = /JPN\s+(.+?)（/.exec(r['計算式の要素'])?.[1] ?? r['産業'];
    const sig = JSON.stringify([diff, r['比較国'], industryName]);
    const hit = groupMap.get(id);
    if (hit) {
      if (hit.sig !== sig) throw new Error(`同じ群で額か比較国が食い違う：${id}（${r['id']}）`);
      hit.lawCount++;
    } else {
      groupMap.set(id, {
        kind: 'group-diff', id, key: id, sig, group: r['産業'], window: r['窓'], diff, lawCount: 1,
        benchmark: `OECD 表6 同産業（${industryName}）の比較国（${r['比較国']}）の中央値。開始前の伸びの差を織り込んだ反実仮想との差の累積`,
      });
    }
    if (lawGroup.has(r['id']) && lawGroup.get(r['id']) !== id) throw new Error(`同じ法律が別の群にある：${r['id']}`);
    lawGroup.set(r['id'], id);
  }
  // lawCount は行数ではなく法律の本数（同じ法律の重複行があっても二重に数えない）。
  const lawsOf = new Map<string, Set<string>>();
  for (const [lawId, gid] of lawGroup) { const s = lawsOf.get(gid) ?? new Set<string>(); s.add(lawId); lawsOf.set(gid, s); }
  const groups: ExposureGroup[] = [...groupMap.values()]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map(({ key: _k, sig: _s, ...g }) => ({ ...g, lawCount: lawsOf.get(g.id)!.size }));

  const counts: ExposureCounts = {
    groups: groups.length, laws: lawGroup.size, lawsWithAnyInvolvement: 0,
    cabinetLaws: 0, cabinetLawsUndetermined: 0, cabinetLawsUnresolved: 0, cabinetUnresolvedMinisters: 0, singleLawGroups: 0,
    yesRows: 0, noRows: 0, proposerRows: 0, cabinetRows: 0,
    skipped: { notInGroup: 0, notCounted: 0, cabinetDecide: 0, committeeProposer: 0, singleLawGroup: 0, chair: 0, amend: 0, question: 0, otherAction: 0, noPersonId: 0, duplicates: 0 },
  };
  // 法律が1本だけの群：群の差がその法律の額になるので、関与を置かない。
  const single = new Set(groups.filter(g => g.lawCount === 1).map(g => g.id));
  counts.singleLawGroups = single.size;
  const inSingle = (lawId: string) => single.has(lawGroup.get(lawId)!);
  // 委員会提出の法律（提出者の欄が「○○委員長」など）。
  const enactedRows = parseCsv(src.enacted);
  const committeeLaws = new Set(enactedRows.filter(r => COMMITTEE.test(parseProposer(r['提出者'] ?? '').lead)).map(r => `${r['種別']}-${r['提出回次']}-${r['番号']}`));
  const involvements: Involvement[] = [];
  const seen = new Set<string>();
  const withInvolvement = new Set<string>();
  const place = (lawId: string, role: ExposureRole, personId: string): boolean => {
    const key = `${lawId}\u0000${role}\u0000${personId}`;
    if (seen.has(key)) { counts.skipped.duplicates++; return false; }
    seen.add(key);
    involvements.push({ actorKind: 'person', actorId: personId, groupId: lawGroup.get(lawId)!, lawId, role, weight: 1 });
    withInvolvement.add(lawId);
    return true;
  };

  for (const text of src.involvements) {
    for (const r of parseCsv(text)) {
      const lawId = r['法律ID'];
      if (!lawGroup.has(lawId)) { if (r['算入'] === 'はい') counts.skipped.notInGroup++; continue; }
      if (r['算入'] !== 'はい') { counts.skipped.notCounted++; continue; }
      if (inSingle(lawId)) { counts.skipped.singleLawGroup++; continue; }
      const action = r['行動'];
      if (action === 'decide' && lawId.startsWith('閣法')) { counts.skipped.cabinetDecide++; continue; }
      const role: ExposureRole | null = action === 'vote' ? 'yes' : action === 'decide' ? 'proposer' : null;
      if (!role) {
        if (action === 'chair') counts.skipped.chair++;
        else if (action === 'amend') counts.skipped.amend++;
        else if (action === 'question') counts.skipped.question++;
        else counts.skipped.otherAction++;
        continue;
      }
      if (role === 'proposer' && committeeLaws.has(lawId)) { counts.skipped.committeeProposer++; continue; }
      if (!r['人物ID']) { counts.skipped.noPersonId++; continue; }
      if (place(lawId, role, r['人物ID'])) { if (role === 'yes') counts.yesRows++; else counts.proposerRows++; }
    }
  }
  for (const r of parseCsv(src.opposing)) {
    const lawId = r['法律ID'];
    if (!lawGroup.has(lawId)) { if (r['算入'] === 'はい') counts.skipped.notInGroup++; continue; }
    if (r['算入'] !== 'はい') { counts.skipped.notCounted++; continue; }
    if (inSingle(lawId)) { counts.skipped.singleLawGroup++; continue; }
    if (!r['人物ID']) { counts.skipped.noPersonId++; continue; }
    if (place(lawId, 'no', r['人物ID'])) counts.noRows++;
  }

  // 閣法：群に属する閣法すべてに、提出した回次の閣僚全員へ cabinet と proposer を置く。
  const ledger = new PersonLedger(src.persons, src.roster);
  const cabinetOf = cabinetBySession(enactedRows, parseCsv(src.cabinet));
  const cabinetLawIds = [...lawGroup.keys()].filter(id => id.startsWith('閣法')).sort();
  for (const lawId of cabinetLawIds) {
    counts.cabinetLaws++;
    const m = LAW_ID.exec(lawId);
    if (!m) throw new Error(`法律 ID の形が不正：${lawId}`);
    const all = cabinetOf(m[2]);
    if (all.length === 0) { counts.cabinetLawsUndetermined++; continue; }
    const resolved = all.map(n => ledger.resolve(normName(n), '')?.id ?? '');
    const missing = resolved.filter(x => !x).length;
    if (missing > 0) { counts.cabinetUnresolvedMinisters += missing; counts.cabinetLawsUnresolved++; continue; }
    if (inSingle(lawId)) continue;
    const ids = [...new Set(resolved)];
    for (const id of ids) {
      if (place(lawId, 'cabinet', id)) counts.cabinetRows++;
      place(lawId, 'proposer', id);
    }
  }
  counts.lawsWithAnyInvolvement = withInvolvement.size;
  return { groups, involvements, counts };
}

export const NO_INVOLVEMENT_REASON = '群に属する法律への関与の記録が無い';
export type LedgerCoverage = { ledger: number; ranked: number; unrankedWithAmount: number; noInvolvement: number; outsideLedger: number };

/**
 * 人物台帳（persons.csv）の全員を people に1回ずつ載せる（完了条件：全員が「点あり」か「点なし＋理由」のどちらか）。
 * 点あり＝tier が数。点なし＝tier が null で unrankedReason に理由。関与の記録が無い人は0円・0本で理由つきの行を足す。
 * 額の合計（totals）は変わらない。台帳に無い人（当時だけの閣僚など）の行はそのまま残し、人数を coverage に出す。
 */
export function withLedgerPeople(ranking: ExposureRanking, personsCsv: string): { ranking: ExposureRanking; coverage: LedgerCoverage } {
  const ledgerIds = [...new Set(parseCsv(personsCsv).map(r => r['人物ID']).filter(Boolean))];
  const ledger = new Set(ledgerIds);
  const have = new Set(ranking.people.map(p => p.actorId));
  if (have.size !== ranking.people.length) throw new Error('people に同じ人が2回いる');
  const added: ExposureRow[] = ledgerIds.filter(id => !have.has(id)).sort((a, b) => a.localeCompare(b)).map(id => ({
    actorKind: 'person', actorId: id, exposureYen: { low: 0, median: 0, high: 0 }, laws: 0, groups: 0, cells: [], tier: null, unrankedReason: NO_INVOLVEMENT_REASON,
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
