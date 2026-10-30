import { describe, expect, it } from 'vitest';
import { countByResult, enforcedBetween, groupByResult, isReferenceAmount, parseLawOutcomes, reasonBreakdown, type LawOutcome } from './law-outcomes-view';

const row = (id: string, result: LawOutcome['result'], enforced: string, extra: Partial<LawOutcome> = {}): LawOutcome => ({
  id, title: `法${id}`, field: '分野', indicator: '', certainty: '', result, reason: '理由A：詳細', route: '経路', enforced, kind: '新規', stage: '', direction: '', side: null, median: null, unit: '', publishable: false, ...extra,
});
const items = [
  row('a', '額あり', '2001-04-01', { certainty: '段階3', publishable: true, side: 'benefit', median: 5e11 }),
  row('b', '額あり', '2001-05-01', { certainty: '段階1・参考', side: 'loss', median: -9e12 }),
  row('c', '保留', '2002-01-01', { reason: '施行日が未取得' }),
  row('d', '保留', '1999-12-31'),
  row('e', '測定できない', ''),
  row('f', '効果なし（定例）', '2003-01-01'),
];

describe('全法律の結果一覧', () => {
  it('施行年が期間内のものだけを残し、施行日不明は数えて外す', () => {
    const { inRange, unknownDate } = enforcedBetween(items, 2001, 2002);
    expect(inRange.map(item => item.id)).toEqual(['a', 'b', 'c']);
    expect(unknownDate).toBe(1);
  });
  it('結果別の件数と並び（確かな額が先、参考は後）', () => {
    const { inRange } = enforcedBetween(items, 1999, 2003);
    expect(countByResult(inRange)).toEqual({ 額あり: 2, 保留: 2, 測定できない: 0, 評価対象外: 0, '効果なし（定例）': 1 });
    expect(groupByResult(inRange).額あり.map(item => item.id)).toEqual(['a', 'b']);
    expect(isReferenceAmount(items[0])).toBe(false);
    expect(isReferenceAmount(items[1])).toBe(true);
  });
  it('理由の内訳を多い順に束ねる', () => {
    expect(reasonBreakdown([items[2], items[3], items[4]])).toEqual([{ reason: '理由A', count: 2 }, { reason: '施行日が未取得', count: 1 }]);
  });
  it('形が違うデータは拒否する', () => {
    expect(() => parseLawOutcomes('{"schema":"x","items":[]}')).toThrow();
    expect(() => parseLawOutcomes(JSON.stringify({ schema: 'law-outcomes/v1', counts: {}, items: [{ id: 'z', result: '謎' }] }))).toThrow();
    expect(parseLawOutcomes(JSON.stringify({ schema: 'law-outcomes/v1', counts: {}, items }))).toBeTruthy();
  });
});
