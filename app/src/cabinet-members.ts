/**
 * 閣法の提出者＝閣僚の割り出し（純関数）。members-reference.ts と exposure-inputs.ts が共有する。
 *
 * 閣法は内閣の提出。総理大臣1人に全部付けず（首相だけが突出する原因）、提出した回次の会期の最初から最後まで在任した閣僚
 * （総理大臣を含む）を提出者とする（設計確定 v2.1：閣法は首相1人に付けない）。副長官・法制局長官は閣僚ではないので除く。
 * 総理大臣が会期中に替わる回次は、どの内閣の提出か決められないので空にする。途中で替わった閣僚は含めない。
 * 返すのは正規化した氏名で、人物台帳への解決は呼ぶ側が行う。
 */
import { warekiDate } from './members-build';

type Row = Record<string, string>;

/** 氏名の空白と末尾の敬称「君」を除く（循環 import を避けるため、置き場はここ）。 */
export const normName = (s: string): string => s.replace(/[\s　]/g, '').replace(/君$/, '');

/** 区分が「閣僚」の行には内閣官房副長官・総理府総務副長官・内閣法制局長官も入るが、閣僚ではないので除く。 */
const NOT_MINISTER = /副長官|法制局長官/;

/**
 * 回次 → 提出時の閣僚の氏名（正規化済み）。
 * 閣法の提出日の列が無いので、提出した回次の会期中の衆議院の付託日（継続審査でない閣法のもの）の最初と最後で
 * 同じ総理大臣ならその回次の内閣とみなす。cabinetCsvRows は parseCsv 済みの内閣の名簿。
 */
export function cabinetBySession(enactedRows: readonly Row[], cabinetCsvRows: readonly Row[]): (session: string) => string[] {
  const ministers = cabinetCsvRows.filter(r => r['区分'] === '閣僚' && r['就任日_西暦'] && !NOT_MINISTER.test(r['役職']));
  const servingOn = (date: string, rows: readonly Row[]) => rows.filter(r => r['就任日_西暦'] <= date && (!r['退任日_西暦'] || date < r['退任日_西暦']));
  const pms = ministers.filter(r => r['役職'] === '内閣総理大臣');
  const pmOn = (date: string) => servingOn(date, pms).map(r => normName(r['氏名']))[0] ?? '';
  const span = new Map<string, { first: string; last: string }>();
  for (const r of enactedRows) {
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
  const cache = new Map<string, string[]>();
  return (session: string): string[] => {
    const hit = cache.get(session);
    if (hit) return hit;
    const x = span.get(session);
    let out: string[] = [];
    if (x && submitterPm(session)) {
      const last = new Set(servingOn(x.last, ministers).map(r => normName(r['氏名'])));
      out = [...new Set(servingOn(x.first, ministers).map(r => normName(r['氏名'])).filter(n => last.has(n)))];
    }
    cache.set(session, out);
    return out;
  };
}
