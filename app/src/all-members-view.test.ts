// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { breakdownOf, filterRows, joinConfirmed, partiesOf, sortRows } from './all-members-view';

const ref = (name, net, current = null, laws = 1, id = name) => ({ id, name, current, lastSangiinParty: '', loss: {}, credit: {}, net: { low: net, median: net, high: net }, laws, top: [], reason: laws ? '' : '記録なし' });
const rows = joinConfirmed([
  ref('甲野太郎', -5, { house: '衆議院', party: '自民', district: '東京1' }),
  ref('乙川花子', 3, { house: '参議院', party: '立憲', district: '比例' }),
  ref('丙山次郎', 0, { house: '衆議院', party: '自民', district: '大阪2' }, 0),
  ref('丁田三郎', -1),
], [{ id: '甲野太郎', name: '甲野太郎', rank: 2, net: { median: -9 } }, { id: '戊井四郎', name: '戊井四郎', rank: 5, net: { median: 4 } }]);

describe('全議員の表', () => {
  it('確かな額を人物IDで付け、無い人は null', () => {
    expect(rows.map(r => r.confirmed)).toEqual([-9, null, null, null, 4]);
    expect(rows[0].confirmedRank).toBe(2);
  });
  it('同姓同名の別人は人物IDで分け、氏名では結ばない', () => {
    const a = '鬼木誠（衆・福岡2）', b = '鬼木誠（参・比例）';
    const joined = joinConfirmed([ref('鬼木誠', -1, { house: '衆議院', party: '自民', district: '福岡2' }, 1, a), ref('鬼木誠', 2, { house: '参議院', party: '立憲', district: '比例' }, 1, b)],
      [{ id: b, name: '鬼木誠', rank: 7, net: { median: 5 } }]);
    expect(joined.map(r => [r.id, r.confirmed])).toEqual([[a, null], [b, 5]]);
  });
  it('確かな額だけの元職も参考の額0円の行として足す', () => {
    const r = rows.find(x => x.name === '戊井四郎');
    expect(r).toMatchObject({ id: '戊井四郎', current: null, laws: 0, confirmedRank: 5, net: { median: 0 } });
  });
  it('院・元職・会派・検索語・額のある人で絞る', () => {
    const o = { house: 'all', party: '', query: '', withAmount: false };
    expect(filterRows(rows, { ...o, house: '衆議院' }).map(r => r.name)).toEqual(['甲野太郎', '丙山次郎']);
    expect(filterRows(rows, { ...o, house: 'former' }).map(r => r.name)).toEqual(['丁田三郎', '戊井四郎']);
    expect(filterRows(rows, { ...o, party: '立憲' }).map(r => r.name)).toEqual(['乙川花子']);
    expect(filterRows(rows, { ...o, query: '大阪' }).map(r => r.name)).toEqual(['丙山次郎']);
    expect(filterRows(rows, { ...o, withAmount: true }).length).toBe(4);
  });
  it('並べ方：参考の国賊側から・国士側から・確かな額（無い人は後ろ）', () => {
    expect(sortRows(rows, 'reference-loss').map(r => r.net.median)).toEqual([-5, -1, 0, 0, 3]);
    expect(sortRows(rows, 'reference-benefit')[0].name).toBe('乙川花子');
    expect(sortRows(rows, 'confirmed')[0].name).toBe('甲野太郎');
  });
  it('会派は現職の人数の多い順', () => {
    expect(partiesOf(rows)).toEqual(['自民', '立憲']);
  });
  it('内訳：公開人数・現職・額のある現職（院別）・確かな額の人数', () => {
    expect(breakdownOf(rows)).toEqual({ total: 5, current: 3, currentWithAmount: 2, shu: 2, shuWithAmount: 1, san: 1, sanWithAmount: 1, confirmed: 2, withAmount: 4 });
  });
});
