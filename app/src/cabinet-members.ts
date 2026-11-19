/**
 * 閣法の提出者＝閣僚の割り出し（純関数）。members-reference.ts と exposure-inputs.ts が共有する（決まりの置き場はここ1つ）。
 *
 * 閣法は内閣の提出。総理大臣1人に全部付けず（首相だけが突出する原因）、提出した回次の会期の最初から最後まで在任した閣僚
 * （総理大臣を含む）を提出者とする（設計確定 v2.1：閣法は首相1人に付けない）。副長官・法制局長官は閣僚ではないので除く。途中で替わった閣僚は含めない。
 * 総理大臣が会期中に替わる回次は、どの内閣の提出かを回次では決められない。付託日の総理大臣が会期の最初の付託日と同じ法律だけ、
 * その付託日に在任した閣僚にする（提出は付託より前なので、前の内閣の提出と決まる）。交代より後に付託された法律は、前の内閣が出して
 * 付託が遅れたものと後の内閣が出したものが混ざり、付託日では決められないので空にする（第147回・第151回は閣法の約半分が交代後の付託）。
 * 継続審査で付託日が後の回次のものも空にする。
 * 返すのは名簿の表記（印と空白を取った氏名）で、人物台帳への解決は呼ぶ側が行う。
 */
import { warekiDate } from './members-build';
import { canonical } from './person-id';

type Row = Record<string, string>;

/** 空白と敬称「君」、名簿の脚注の印（*・※ など）を取る。印を残すと、同じ人が印の有無で別人になる。字体は寄せない（出典の表記のまま）。 */
export const normName = (s: string): string => s.replace(/[\s　]/g, '').replace(/君$/, '').replace(/[*＊※†‡]+$/, '');

/** 閣僚＝国務大臣（総理大臣・各大臣・官房長官・担当大臣）。区分が「閣僚」の行には内閣官房副長官・総理府総務副長官・内閣法制局長官も入るが、閣僚ではないので除く。 */
const NOT_MINISTER = /副長官|法制局長官/;

/**
 * 成立法の行（enacted.csv の1行）→ 提出時の閣僚の氏名と、同じ答えになる単位の鍵（回次か付託日。呼ぶ側のキャッシュ用）。
 * 決められない法律は key が空で names も空。enactedRows は会期（付託日の最初と最後）を数えるための全行。
 */
export function cabinetForBill(enactedRows: readonly Row[], cabinetCsvRows: readonly Row[]): (bill: Row) => { key: string; names: string[] } {
  const ministers = cabinetCsvRows.filter(r => r['区分'] === '閣僚' && r['就任日_西暦'] && !NOT_MINISTER.test(r['役職']));
  const servingOn = (date: string, rows: readonly Row[]) => rows.filter(r => r['就任日_西暦'] <= date && (!r['退任日_西暦'] || date < r['退任日_西暦']));
  // 氏名は字体のゆれも寄せてから比べる（寄せないと、同じ人が別人になり、通して在任した閣僚が落ちる）。出す名前は名簿の表記（印と空白を取ったもの）。
  const servingNames = (date: string) => new Map(servingOn(date, ministers).map(r => [canonical(r['氏名']), normName(r['氏名'])]));
  const pmOn = (date: string) => servingOn(date, ministers).filter(r => r['役職'] === '内閣総理大臣').map(r => canonical(r['氏名']))[0] ?? '';
  // 提出日の列が無いので、提出した回次の会期は、衆議院の付託日（継続審査でない閣法のもの）の最初と最後で代える。
  const referredOn = (r: Row) => r['種別'] === '閣法' && r['回次'] === r['提出回次'] ? warekiDate(r['付託日_衆']) : '';
  const span = new Map<string, { first: string; last: string }>();
  for (const r of enactedRows) {
    const d = referredOn(r);
    if (!d) continue;
    const x = span.get(r['提出回次']);
    span.set(r['提出回次'], { first: !x || d < x.first ? d : x.first, last: !x || d > x.last ? d : x.last });
  }
  const cache = new Map<string, string[]>();
  return (bill: Row) => {
    const x = span.get(bill['提出回次']);
    const stable = !!x && !!pmOn(x.first) && pmOn(x.first) === pmOn(x.last);
    const referred = referredOn(bill);
    const key = stable ? `回次:${bill['提出回次']}` : x && referred && pmOn(referred) && pmOn(referred) === pmOn(x.first) ? `付託日:${referred}` : '';
    if (!key) return { key, names: [] };
    let names = cache.get(key);
    if (!names) {
      const first = servingNames(stable ? x!.first : referred);
      const last = servingNames(stable ? x!.last : referred);
      names = [...first].filter(([k]) => last.has(k)).map(([, name]) => name);
      cache.set(key, names);
    }
    return { key, names };
  };
}
