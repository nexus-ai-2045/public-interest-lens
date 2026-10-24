/**
 * 人物ID（scripts/person_ids.py の台帳と同じ決め方）。議員を氏名の文字列ではなく人物IDで結ぶ。
 * canonical は Python 側と同じ正規化（NFKC・空白・敬称・脚注記号の除去と、同一人物の字体ゆれの寄せ）。
 * VARIANTS は scripts/person_ids.py の表と同じでなければならない（tests/test_person_ids.py が照らす）。
 *
 * 方針：同姓同名の可能性がある名前は、一次資料で所属が決まる場合だけ人物IDに結び、それ以外は決めない（null）。
 * memberHouse は呼び出し側の院（議案の種別や参議院の投票記録）。台帳は今の院しか持たず、院を移った人がいるので、
 * 同姓同名を院で決めることはしない（overrides で結ぶまで配らない）。
 */
import { parseCsv } from './impact-batch';

export const VARIANTS: Record<string, string> = { 髙: '高', 﨑: '崎', 德: '徳', 濵: '浜', 澤: '沢' };
const HONORIFICS = ['君', '議員', '先生', 'さん', '氏', '殿', '様'];
const FOOTNOTE_MARKS = /[*※†‡]+$/;

const length = (s: string): number => [...s].length;

export function normalizeName(name: string): string {
  let s = (name ?? '').normalize('NFKC').replace(/\s+/g, '');
  let changed = true;
  while (changed) {
    changed = false;
    for (const h of HONORIFICS) {
      if (length(s) > length(h) + 1 && s.endsWith(h)) { s = s.slice(0, s.length - h.length); changed = true; }
    }
  }
  return s;
}
export const cleanName = (name: string): string => normalizeName(normalizeName(name).replace(FOOTNOTE_MARKS, ''));
export const canonical = (name: string): string => [...cleanName(name)].map(c => VARIANTS[c] ?? c).join('');

export type PersonRow = { id: string; name: string; reading: string; house: string; district: string };

export class PersonLedger {
  private byCanonical = new Map<string, PersonRow[]>();
  readonly byId = new Map<string, PersonRow>();
  /** 名簿の「本名」（通称で載っている参議院議員）。台帳の氏名と重ならないものだけ。 */
  private alias = new Map<string, PersonRow>();

  /** persons.csv（scripts/person_ids.py の出力）と、本名の別名を引くための名簿。 */
  constructor(personsCsv: string, rosterCsv = '') {
    for (const r of parseCsv(personsCsv)) {
      const p = { id: r['人物ID'], name: r['氏名'], reading: r['読み'], house: r['院'], district: r['選挙区'] };
      this.byId.set(p.id, p);
      const key = canonical(p.name);
      this.byCanonical.set(key, [...(this.byCanonical.get(key) ?? []), p]);
    }
    for (const r of rosterCsv ? parseCsv(rosterCsv) : []) {
      const hon = r['本名'] ? canonical(r['本名']) : '';
      const p = hon ? this.rosterPerson(r) : undefined;
      if (hon && p && !this.byCanonical.has(hon)) this.alias.set(hon, p);
    }
  }

  isSplit(name: string): boolean { return (this.byCanonical.get(canonical(name))?.length ?? 0) > 1; }

  /** 名簿の1行に当たる人物（院・選挙区・読みが同じ、無ければ院と読みが同じ）。候補が1人に絞れなければ undefined（並び順で決めない）。 */
  rosterPerson(row: Record<string, string>): PersonRow | undefined {
    const found = this.byCanonical.get(canonical(row['氏名'])) ?? [];
    const sameReading = (p: PersonRow) => !p.reading || !row['読み'] || p.reading === row['読み'];
    for (const match of [
      (p: PersonRow) => p.house === row['院'] && p.district === row['選挙区'] && sameReading(p),
      (p: PersonRow) => p.house === row['院'] && !!p.reading && p.reading === row['読み'],
    ]) {
      const hits = found.filter(match);
      if (hits.length === 1) return hits[0];
    }
    return undefined;
  }

  /** 台帳に無い名前は canonical をそのまま人物IDにする。同姓同名で所属が決まらなければ null（配らない）。 */
  resolve(name: string, memberHouse = ''): { id: string; person?: PersonRow } | null {
    const canon = canonical(name);
    const found = this.byCanonical.get(canon) ?? (this.alias.has(canon) ? [this.alias.get(canon)!] : []);
    if (found.length === 0) return { id: canon };
    if (found.length === 1) return { id: found[0].id, person: found[0] };
    // 台帳の院は今の院だけで、所属の履歴は持たない（院を移った人がいる）ので、同姓同名は院では決めない。
    void memberHouse;
    return null;
  }
}
