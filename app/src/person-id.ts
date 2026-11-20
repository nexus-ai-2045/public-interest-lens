/**
 * 人物ID（scripts/person_ids.py の台帳と同じ決め方）。議員を氏名の文字列ではなく人物IDで結ぶ。
 * canonical は Python 側と同じ正規化（NFKC・空白・敬称・脚注記号の除去と、同一人物の字体ゆれの寄せ）。
 * VARIANTS と結びの理由の文言は scripts/person_ids.py と同じでなければならない（tests/test_person_ids.py が照らす）。
 * 人物への結びは linkPerson だけが行う（Python の link_person と同じ決まり）。
 *
 * キーは氏名と在任期間。在任に院があれば院も見る。その日付に在任している人が1人ならその人。
 * 在任の外と、候補が2人以上で1人に決まらないものは、並びの先頭に寄せず理由つきで未結合。
 * 台帳の「今の院」だけでは決めない（院を移った人がいる）。在任が無い人は氏名が1人でも結ばない。
 * 院を指定したときは、その院の在任がある人だけに結ぶ。院が空の在任は、院を指定した結びには使わない。
 */
import { parseCsv } from './impact-batch';

export const VARIANTS: Record<string, string> = { 髙: '高', 﨑: '崎', 德: '徳', 濵: '浜', 澤: '沢' };
export const UNRESOLVED = '同姓同名で人物を決められない';
export const OUTSIDE_TERM = '未結合：在任期間の外（その日付に在任している人がいない）';
export const OUTSIDE_HOUSE = '未結合：その日付の在任は別の院で、この院には結べない';
export const AMBIGUOUS = '未結合：候補が2人以上あり、在任期間で1人に決められない';
export const NOT_IN_LEDGER = '未結合：人物台帳に無い';
export const NO_TERM = '未結合：在任期間が分からない';
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

export type OfficeTerm = { start: string; end: string; house: string };
export type PersonRow = { id: string; name: string; reading: string; house: string; district: string; terms: OfficeTerm[] };
export type PersonLink = { id: string; reason: string };

const dedupe = (candidates: readonly PersonRow[]): PersonRow[] => {
  const seen = new Set<string>();
  const out: PersonRow[] = [];
  for (const person of candidates) {
    if (seen.has(person.id)) continue;
    seen.add(person.id);
    out.push(person);
  }
  return out;
};

const covers = (term: OfficeTerm, on: string, house: string): boolean => {
  if (on && (!term.start || on < term.start || (term.end && on > term.end))) return false;
  if (house && term.house !== house) return false;
  return true;
};

/** scripts/person_ids.py の link_person と同じ。候補が空なら id も reason も空。 */
export function linkPerson(candidates: readonly PersonRow[], on = '', house = ''): PersonLink {
  const people = dedupe(candidates);
  if (people.length === 0) return { id: '', reason: '' };
  if (!on && !house) return { id: '', reason: people.length === 1 ? NO_TERM : UNRESOLVED };
  if (!people.some(person => person.terms.length > 0)) return { id: '', reason: people.length === 1 ? NO_TERM : UNRESOLVED };
  if (people.some(person => person.terms.length === 0)) return { id: '', reason: AMBIGUOUS };
  const hits = people.filter(person => person.terms.some(term => covers(term, on, house)));
  if (hits.length === 1) return { id: hits[0].id, reason: '' };
  if (hits.length > 1) return { id: '', reason: AMBIGUOUS };
  const otherHouse = house && people.some(person => person.terms.some(term => covers(term, on, '') && term.house !== '' && term.house !== house));
  if (otherHouse) return { id: '', reason: OUTSIDE_HOUSE };
  if (on) return { id: '', reason: OUTSIDE_TERM };
  return { id: '', reason: people.length === 1 ? NO_TERM : UNRESOLVED };
}

export class PersonLedger {
  private byCanonical = new Map<string, PersonRow[]>();
  readonly byId = new Map<string, PersonRow>();
  /** 名簿の「本名」（通称で載っている参議院議員）。台帳の氏名と重ならないものだけ。 */
  private alias = new Map<string, PersonRow>();

  /** persons.csv（scripts/person_ids.py の出力）と、本名の別名を引くための名簿。 */
  constructor(personsCsv: string, rosterCsv = '') {
    for (const r of parseCsv(personsCsv)) {
      if (!r['人物ID']) continue; // 人物ID が空の行（persons.csv の1行目は全列空）は台帳に入れない。
      const starts = (r['在任開始'] ?? '').split(';');
      const ends = (r['在任終了'] ?? '').split(';');
      const houses = (r['在任の院'] ?? '').split(';');
      const p: PersonRow = {
        id: r['人物ID'], name: r['氏名'], reading: r['読み'], house: r['院'], district: r['選挙区'],
        terms: starts.flatMap((start, index) => start ? [{ start, end: ends[index] ?? '', house: houses[index] ?? '' }] : []),
      };
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

  /** 台帳に無い名前は canonical をそのまま人物IDにする。決まらなければ id が空で、reason に未結合の理由。 */
  resolve(name: string, memberHouse = '', on = ''): { id: string; person?: PersonRow; reason: string } {
    const canon = canonical(name);
    const found = this.byCanonical.get(canon) ?? (this.alias.has(canon) ? [this.alias.get(canon)!] : []);
    if (found.length === 0) return { id: canon, reason: '' };
    const linked = linkPerson(found, on, memberHouse);
    if (!linked.id) return { id: '', reason: linked.reason };
    return { id: linked.id, person: found.find(person => person.id === linked.id), reason: '' };
  }
}
