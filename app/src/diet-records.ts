/**
 * 国会の記録（議案の経過・参議院の投票・会派名）を読む小さな純関数の置き場。
 * 曝露ランキングの入力（exposure-inputs.ts）・閣僚の割り出し（cabinet-members.ts）・賛否の一覧（votes.ts）が共有する。
 * 点数の計算はここに置かない。
 */

/** 空白と敬称「君」、名簿の脚注の印（*・※ など）を取る。印を残すと、同じ人が印の有無で別人になる。字体は寄せない（出典の表記のまま）。 */
export const normName = (s: string): string => s.replace(/[\s　]/g, '').replace(/君$/, '').replace(/[*＊※†‡]+$/, '');

/** 「平成30年 4月18日」を 2018-04-18 に。 */
export function warekiDate(text: string): string {
  const m = /(平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日/.exec(text);
  if (!m) return '';
  const y = (m[2] === '元' ? 1 : Number(m[2])) + (m[1] === '平成' ? 1988 : 2018);
  return `${y}-${m[3].padStart(2, '0')}-${m[4].padStart(2, '0')}`;
}

/** 参議院の会派名を系統に分ける（会派は合流・改称が多いので、名前の一部で寄せる。上から順に当てる）。 */
const BLOCS: [RegExp, string][] = [
  // 希望の会（自由党・社民党の院内会派、2019年）は社民党の会派ではない。社民には寄せない。
  [/^希望の会/, 'その他'], [/自由民主/, '自民'], [/公明/, '公明'], [/立憲/, '立憲'], [/共産/, '共産'], [/社会民主|社民/, '社民'], [/国民民主/, '国民民主'],
  [/民主党|民進|民友/, '民主系'], [/維新/, '維新'], [/れいわ/, 'れいわ'], [/参政/, '参政'],
  // 2026年の衆院から出る会派。中道改革連合は立憲・公明の衆院会派の後に記録される別の会派なので、立憲・公明には寄せない。
  // 第222回（2026年秋）から、衆議院の議案情報はこの会派を「中道」と書く（衆議院の会派一覧でも会派名「中道」、2026-09-28 現在）。
  // 略称「中道」を中道改革連合と読むのは caucus-label.ts と同じ。名前が「中道」だけのときに限って寄せる。
  [/中道改革|^中道$/, '中道改革連合'], [/チームみらい/, 'チームみらい'], [/日本保守党/, '日本保守党']];
export const blocOf = (party: string): string => BLOCS.find(([re]) => re.test(party))?.[1] ?? 'その他';

/** 委員会・調査会・審査会の提出（人の提出ではない）。 */
export const COMMITTEE = /(委員長|委員会|調査会長|審査会長)$/;

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
