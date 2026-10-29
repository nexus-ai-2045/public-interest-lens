// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { certaintyLabels, filterMacro, filterOthers, outcomeCounts, pageCount, pageSlice, splitLaws } from './law-ranking-view';

const law = (id, certainty, median, group = 'g') => ({ id, certainty, amountMedianYen: median, group, side: 'loss', title: `題名${id}`, field: '金融' });
const other = (id, title, outcome, reason) => ({ id, title, outcome, reason });

describe('法律ランキングの表示の決まり', () => {
  it('確かさの4つの表示名を持つ', () => {
    expect(certaintyLabels).toEqual({
      高: '高（段階3）', 中: '中（段階2）', 低: '低（段階1：経済全体で未確認）', 参考: '参考（貸出残高を多いほど良いとみなす機械的仮定）',
    });
  });
  it('参考の額は確かな額と別の組に分け、それぞれ額の大きい順に並べる', () => {
    const { confirmed, reference } = splitLaws([law('a', '参考', 9), law('b', '高', 1), law('c', '低', 5), law('d', '参考', 20), law('e', '中', 3)]);
    expect(confirmed.map(item => item.id)).toEqual(['c', 'e', 'b']);
    expect(reference.map(item => item.id)).toEqual(['d', 'a']);
  });
  it('全体指標の額は参考とも別の組にし、側と検索語で絞れる', () => {
    const { reference, macro } = splitLaws([law('a', '参考', 9), law('m1', '参考', 3, '全体指標-_T'), law('m2', '参考', 7, '全体指標-K')]);
    expect(reference.map(item => item.id)).toEqual(['a']);
    expect(macro.map(item => item.id)).toEqual(['m2', 'm1']);
    expect(filterMacro(macro, 'loss', 'm1').map(item => item.id)).toEqual(['m1']);
    expect(filterMacro(macro, 'benefit', '')).toEqual([]);
  });
  const items = [
    other('閣法-1-1', '農業の法律案', '評価対象外', '農業分野で対応表なし'),
    other('閣法-1-2', '預金の法律案', '保留（振り分け）', '2系統が不一致'),
    other('衆法-2-3', '農地の法律案', '評価対象外', '農業分野で対応表なし'),
  ];
  it('結果ごとの本数を多い順に数える', () => {
    expect(outcomeCounts(items)).toEqual([['評価対象外', 2], ['保留（振り分け）', 1]]);
  });
  it('結果と検索語で絞る（空白区切りは全語を含む）', () => {
    expect(filterOthers(items, '', '').length).toBe(3);
    expect(filterOthers(items, '評価対象外', '').map(item => item.id)).toEqual(['閣法-1-1', '衆法-2-3']);
    expect(filterOthers(items, '', '農 法律').length).toBe(2);
    expect(filterOthers(items, '評価対象外', '預金')).toEqual([]);
    expect(filterOthers(items, '', '衆法-2').map(item => item.id)).toEqual(['衆法-2-3']);
  });
  it('3415本でも一度に出す行数を決めたページ分けにする', () => {
    const all = Array.from({ length: 3399 }, (_, index) => index);
    expect(pageCount(all.length)).toBe(68);
    expect(pageSlice(all, 1).length).toBe(50);
    expect(pageSlice(all, 68).length).toBe(49);
    expect(pageSlice(all, 999)[0]).toBe(3350);
    expect(pageSlice([], 1)).toEqual([]);
  });
});
