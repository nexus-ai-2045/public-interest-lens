// 政党ごとの比較（画面に依存しない部分）。議員の確かな額（members.json の純額）を、現職の所属政党で足し合わせる。
import type { PublicMember } from './members-build';
import type { ReferenceMember } from './members-reference';

export type PartyRow = {
  party: string; people: number; loss: number; benefit: number; zero: number;
  /** 所属議員の純額（中央値）の合計。マイナスが国賊側。 */
  total: number;
  /** total ÷ 人数。 */
  perPerson: number;
};
export type PartySortKey = 'perPerson' | 'total' | 'people';

/** 人物ID → 現職の所属政党。元職・当時だけの人は入らない。 */
export function partyById(reference: ReferenceMember[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const r of reference) if (r.current?.party) map.set(r.id, r.current.party);
  return map;
}

/** 所属政党ごとに集める。政党が分からない人（元職など）は rows に入れず excluded に数える。 */
export function partyComparison(members: PublicMember[], parties: ReadonlyMap<string, string>): { rows: PartyRow[]; excluded: number } {
  const book = new Map<string, PartyRow>();
  let excluded = 0;
  for (const m of members) {
    const party = parties.get(m.id);
    if (!party) { excluded += 1; continue; }
    const row = book.get(party) ?? { party, people: 0, loss: 0, benefit: 0, zero: 0, total: 0, perPerson: 0 };
    row.people += 1;
    row.total += m.net.median;
    if (m.net.median < 0) row.loss += 1; else if (m.net.median > 0) row.benefit += 1; else row.zero += 1;
    book.set(party, row);
  }
  const rows = [...book.values()].map(r => ({ ...r, perPerson: Math.trunc(r.total / r.people) }));
  return { rows, excluded };
}

/** 小さい順（国賊側が上）。人数だけは多い順。 */
export function sortPartyRows(rows: PartyRow[], by: PartySortKey): PartyRow[] {
  const key = (r: PartyRow) => by === 'people' ? -r.people : r[by];
  return [...rows].sort((a, b) => key(a) - key(b) || a.party.localeCompare(b.party, 'ja'));
}
