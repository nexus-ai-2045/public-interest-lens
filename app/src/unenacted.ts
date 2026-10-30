/** 未成立の提出法案の暫定規模点（unenacted.json）。円の額・向きは無い。scripts/build_public_unenacted.py が作る。 */
export const unenactedUrl = '/distribution/unenacted.json';

export type UnenactedBill = { id: string; title: string; kind: string; session: number; status: string; field: string; indicator: string; scale: number; certainty: string; url: string };
export type UnenactedData = { schema: 'public-unenacted/v1'; notes: string[]; counts: { total: number; scored: number; excluded: Record<string, number> }; bills: UnenactedBill[] };

export function parseUnenacted(text: string): UnenactedData {
  const v = JSON.parse(text) as UnenactedData;
  if (v.schema !== 'public-unenacted/v1' || !Array.isArray(v.bills) || !Array.isArray(v.notes)) throw new Error('unenacted.json の形が違います');
  for (const b of v.bills) {
    if (typeof b.id !== 'string' || typeof b.title !== 'string' || !(b.scale >= 0)) throw new Error(`行の形が違います: ${String(b.id)}`);
    if (b.url && !/^https:\/\//.test(b.url)) throw new Error(`出典の URL が不正です: ${b.id}`);
  }
  return v;
}

export type UnenactedQuery = { kind: string; field: string; character: ReadonlySet<string> };
export function filterUnenacted(bills: UnenactedBill[], query: { kind: string; field: string }, keep: (bill: UnenactedBill) => boolean = () => true): UnenactedBill[] {
  return bills.filter(b => (!query.kind || b.kind === query.kind) && (!query.field || b.field === query.field) && keep(b));
}
