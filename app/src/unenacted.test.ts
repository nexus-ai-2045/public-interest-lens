import { describe, expect, it } from 'vitest';
import { filterUnenacted, parseUnenacted, type UnenactedBill } from './unenacted';

const bill = (id: string, kind: string, field: string, scale: number): UnenactedBill => ({ id, title: id, kind, session: 1, status: '未了', field, indicator: '', scale, certainty: '参考', url: '' });

describe('unenacted', () => {
  it('形が違えば読み込まない', () => {
    expect(() => parseUnenacted('{"schema":"x","bills":[],"notes":[]}')).toThrow();
    expect(() => parseUnenacted(JSON.stringify({ schema: 'public-unenacted/v1', notes: [], counts: { total: 1, scored: 1, excluded: {} }, bills: [{ id: 'a', title: 'a', scale: 1, url: 'http://x' }] }))).toThrow();
  });
  it('種別と分野で絞る', () => {
    const bills = [bill('a', '閣法', '商業', 3), bill('b', '衆法', '商業', 2), bill('c', '衆法', '交通', 1)];
    expect(filterUnenacted(bills, { kind: '衆法', field: '商業' }).map(b => b.id)).toEqual(['b']);
    expect(filterUnenacted(bills, { kind: '', field: '' })).toHaveLength(3);
  });
});
