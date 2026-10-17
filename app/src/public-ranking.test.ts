// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parsePublicRanking } from './public-distribution';

const committed = readFileSync(new URL('../public/distribution/ranking.json', import.meta.url), 'utf8');
const law = {
  id: '衆法-186-35', title: 'サイバーセキュリティ基本法案', side: 'benefit', field: '通信・ネット', indicator: '通信業の付加価値', stage: '段階3', enforcedOn: '2014-11-12',
  amountMedianYen: 19, amountLowYen: 9, amountHighYen: 22, lowerBound: true, window: '2014〜2019年', comparisonCountries: ['USA'], benefitStatus: '安全（犯罪）：未測定', group: '通信業の付加価値-1',
  sources: ['https://laws.e-gov.go.jp/law/426AC1000000104'],
};
function approved() {
  const value = JSON.parse(committed);
  value.held = value.held.filter(item => item.id !== law.id);
  value.approval = { approvedAt: '2026-10-17', approvedLaws: [law.id] };
  value.laws = [law];
  value.counts.published = 1;
  return value;
}

describe('公開ランキングの配布データ', () => {
  it('リポジトリの ranking.json を読み、承認前は額を1件も持たない', () => {
    const value = parsePublicRanking(committed);
    expect(value.laws.length).toBe(value.approval.approvedLaws.length);
    expect(value.counts.published).toBe(value.laws.length);
    for (const item of value.held) expect(Object.keys(item).sort()).toEqual(['id', 'reason', 'reasonCode', 'side', 'title']);
  });
  it('承認した法律だけ額を読む', () => {
    expect(parsePublicRanking(JSON.stringify(approved())).laws[0].amountMedianYen).toBe(19);
  });
  it('承認リストに無い法律の額は拒否する', () => {
    const value = approved();
    value.approval.approvedLaws = [];
    value.approval.approvedAt = null;
    expect(() => parsePublicRanking(JSON.stringify(value))).toThrow('承認');
  });
  it('人物の欄や未知のキーは拒否する', () => {
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), people: [] }))).toThrow('形式');
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, members: ['x'] }] }))).toThrow();
    const held = approved();
    held.held[0] = { ...held.held[0], amountMedianYen: 1 };
    expect(() => parsePublicRanking(JSON.stringify(held))).toThrow('保留');
  });
  it('幅の逆転と許可外の出典は拒否する', () => {
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, amountLowYen: 30 }] }))).toThrow('幅');
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, sources: ['https://example.com/x'] }] }))).toThrow('一次資料');
  });
});
