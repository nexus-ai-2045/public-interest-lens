/** 法律ごとの会派・議員の賛否（/votes）。配布ファイル votes.json は scripts/build_public_votes.py が作る。 */
import { blocOf } from './members-build';

export const distributionVotesUrl = '/distribution/votes.json';
/** 議員ページの配布データ（MembersPage.tsx の distributionMembersUrl と同じ場所）。人物IDだけ読む。 */
export const distributionMembersIdsUrl = '/distribution/members.json';

export type VoteLaw = {
  id: string; title: string; kind: string; session: number; proposer: string; promulgated: string | null; url: string;
  shu: { date: string | null; yes: string[]; no: string[] } | null;
  san: { url: string; method: 'ballot' | 'standing'; date: string | null; groups?: Record<string, [number, number, number]>; no?: number[] } | null;
};
export type VoteMember = { name: string; group: string; yes: number; no: number; absent: number; last: string };
export type PublicVotes = { schema: 'public-votes/v1'; notes: string[]; counts: Record<string, number>; laws: VoteLaw[]; members: VoteMember[] };

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/** 形式が不正なら全体を読み込みません。 */
export function parseVotes(text: string): PublicVotes {
  if (text.length > 12_000_000) throw new Error('賛否データが大きすぎます。');
  const v = JSON.parse(text) as unknown;
  if (!isRecord(v) || v.schema !== 'public-votes/v1' || !Array.isArray(v.laws) || !Array.isArray(v.members) || !Array.isArray(v.notes) || !isRecord(v.counts)) throw new Error('賛否データの形式が不正です。');
  const members = v.members as VoteMember[];
  for (const law of v.laws as VoteLaw[]) {
    if (!isRecord(law) || typeof law.id !== 'string' || typeof law.title !== 'string') throw new Error('法律の項目が不正です。');
    if (!law.shu && !law.san) throw new Error('賛否の無い法律が混ざっています。');
    for (const index of law.san?.no ?? []) if (!Number.isInteger(index) || index < 0 || index >= members.length) throw new Error('議員の番号が不正です。');
    for (const url of [law.url, law.san?.url]) if (url && !/^https:\/\//.test(url)) throw new Error('出典の URL が不正です。');
  }
  return v as unknown as PublicVotes;
}

export const lawYear = (law: VoteLaw): number => Number((law.promulgated ?? law.shu?.date ?? law.san?.date ?? '0000').slice(0, 4));

export const START_YEARS = ['recent4', 'all', '2015', '2020', '2023', '2025'] as const;
export type StartYear = typeof START_YEARS[number];
export const startLabel = (s: StartYear) => s === 'all' ? '全期間' : s === 'recent4' ? 'データ最新日から4年' : `${s}年以降`;
const dayOf = (law: VoteLaw): string => law.promulgated ?? law.shu?.date ?? law.san?.date ?? '';
/** 公布日（なければ衆院、次に参院の採決日）の最新日が基準。4年前の同日は除き、最新日は含む。 */
export function recentCutoff(laws: VoteLaw[]): string {
  const latest = laws.map(dayOf).reduce((a, b) => (b > a ? b : a), '');
  return latest ? `${Number(latest.slice(0, 4)) - 4}${latest.slice(4)}` : '';
}
export const fromYear = (laws: VoteLaw[], start: StartYear): VoteLaw[] => {
  if (start === 'all') return laws;
  if (start === 'recent4') { const cut = recentCutoff(laws); return laws.filter(l => dayOf(l) > cut); }
  return laws.filter(l => lawYear(l) >= Number(start));
};

/** 系統（自民・公明・立憲…）。会派名は合流・改称が多いので名前の一部で寄せる（議員ページの政党ランキングと同じ分け方）。 */
export const BLOCS = ['自民', '公明', '立憲', '共産', '国民民主', '維新', 'れいわ', '社民', '参政', '中道改革連合', 'チームみらい', '日本保守党', '民主系', 'その他'] as const;
export type Bloc = typeof BLOCS[number];

/** 衆院でその系統の会派が賛否に載った最初と最後の採決日（載っていなければ空）。合流・改称で記録が切れる系統の注記に使う。 */
export function shuSpan(laws: VoteLaw[], bloc: Bloc): { first: string; last: string } {
  let first = '', last = '';
  for (const law of laws) {
    const day = law.shu?.date;
    if (!day || !law.shu || ![...law.shu.yes, ...law.shu.no].some(p => blocOf(p) === bloc)) continue;
    if (!first || day < first) first = day;
    if (day > last) last = day;
  }
  return { first, last };
}

/** 議員ページの配布データ（members.json）から人物IDだけを取る。/votes の議員から /members へのリンクを、人物IDが一致するときだけ張るために使う。 */
export function memberIdsOf(text: string): Set<string> {
  const v = JSON.parse(text) as unknown;
  const list = isRecord(v) && Array.isArray(v.members) ? v.members : [];
  return new Set(list.map(m => isRecord(m) ? m.id : null).filter((id): id is string => typeof id === 'string'));
}

/** 議員ページ（/members）への道。人物IDと名前が一致するときだけ返す（同姓同名は人物IDに院と選挙区が付くので、一致しない）。 */
export const memberPageHref = (name: string, ids: ReadonlySet<string> | undefined): string | null => ids?.has(name) ? `/members?name=${encodeURIComponent(name)}` : null;

export type Stance = 'yes' | 'no' | 'split' | 'none';
export type BlocStance = { shu: Stance; san: { yes: number; no: number; absent: number } | null; sanMethod: 'ballot' | 'standing' | null };

/** 衆議院：その系統の会派が賛成側にあれば賛成、反対側にあれば反対、両方なら割れ。載っていなければ「なし」。 */
export function blocStance(law: VoteLaw, bloc: Bloc): BlocStance {
  let shu: Stance = 'none';
  if (law.shu) {
    const yes = law.shu.yes.some(p => blocOf(p) === bloc), no = law.shu.no.some(p => blocOf(p) === bloc);
    shu = yes && no ? 'split' : yes ? 'yes' : no ? 'no' : 'none';
  }
  let san: BlocStance['san'] = null;
  if (law.san?.groups) {
    const total = { yes: 0, no: 0, absent: 0 };
    for (const [group, [y, n, a]] of Object.entries(law.san.groups)) if (blocOf(group) === bloc) { total.yes += y; total.no += n; total.absent += a; }
    if (total.yes + total.no + total.absent > 0) san = total;
  }
  return { shu, san, sanMethod: law.san?.method ?? null };
}

export type BlocSummary = { bloc: Bloc; shuYes: number; shuNo: number; shuLaws: number; sanYes: number; sanNo: number; sanLaws: number; withLdpSame: number; withLdpLaws: number; withLdpExcluded: number };
export function blocSummary(laws: VoteLaw[], bloc: Bloc): BlocSummary {
  const out: BlocSummary = { bloc, shuYes: 0, shuNo: 0, shuLaws: 0, sanYes: 0, sanNo: 0, sanLaws: 0, withLdpSame: 0, withLdpLaws: 0, withLdpExcluded: 0 };
  for (const law of laws) {
    const s = blocStance(law, bloc);
    if (law.shu) {
      if (s.shu !== 'none') out.shuLaws += 1;
      const ldp = blocStance(law, '自民').shu;
      if ((ldp === 'yes' || ldp === 'no') && (s.shu === 'yes' || s.shu === 'no')) {
        out.withLdpLaws += 1;
        if (s.shu === ldp) out.withLdpSame += 1;
      } else {
        out.withLdpExcluded += 1;
      }
      if (s.shu === 'yes' || s.shu === 'split') out.shuYes += 1;
      if (s.shu === 'no' || s.shu === 'split') out.shuNo += 1;
    }
    if (s.san) { out.sanLaws += 1; out.sanYes += s.san.yes; out.sanNo += s.san.no; }
  }
  return out;
}

/** 議員ごとの、参議院で反対した法律（新しい順の配列の位置）。 */
export function noLawsByMember(laws: VoteLaw[], memberCount: number): number[][] {
  const out: number[][] = Array.from({ length: memberCount }, () => []);
  laws.forEach((law, i) => { for (const m of law.san?.no ?? []) out[m].push(i); });
  return out;
}
