// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { COVID_BENEFIT_GROUP, parsePublicRanking, RANKING_TEXT_LIMIT } from './public-distribution';

const committed = readFileSync(new URL('../public/distribution/ranking.json', import.meta.url), 'utf8');
const note = '法律単位の結果を全件公開（2026-10-17 ユーザー承認、議員の実名は別承認）';
const law = {
  id: '衆法-186-35', title: 'サイバーセキュリティ基本法案', side: 'benefit', certainty: '高', notes: [], field: '通信・ネット', indicator: '通信業の付加価値', stage: '段階3', enforcedOn: '2014-11-12',
  amountMedianYen: 19, amountLowYen: 9, amountHighYen: 22, lowerBound: true, window: '2014〜2019年', comparisonCountries: ['USA'], benefitStatus: '安全（犯罪）：未測定', group: '通信業の付加価値-1',
  sources: ['https://laws.e-gov.go.jp/law/426AC1000000104'],
};
/** 承認済みで、額が1本だけの小さな配布データ。 */
function approved() {
  const value = JSON.parse(committed);
  value.others = [{ id: '閣法-1-1', title: '例の法律案', outcome: '評価対象外', reason: '農業分野で対応表なし' }];
  value.approval = { approvedAt: '2026-10-17', scope: 'all-laws', note };
  value.laws = [law];
  value.counts = { ...value.counts, enacted: 2, published: 1, confirmed: 1, reference: 0, others: 1 };
  return value;
}

describe('公開ランキングの配布データ', () => {
  it('コロナ対応の費用便益だけは比較国を持たず、ほかの法律は比較国が要る', () => {
    const covid = { ...law, certainty: '参考', group: `${COVID_BENEFIT_GROUP}-衆法-1-1`, comparisonCountries: [] };
    const value = approved(); value.laws = [covid];
    expect(() => parsePublicRanking(JSON.stringify(value))).not.toThrow();
    const other = approved(); other.laws = [{ ...law, comparisonCountries: [] }];
    expect(() => parsePublicRanking(JSON.stringify(other))).toThrow();
    const wrong = approved(); wrong.laws = [{ ...covid, comparisonCountries: ['USA'] }];
    expect(() => parsePublicRanking(JSON.stringify(wrong))).toThrow();
    const govSource = 'https://www.mhlw.go.jp/content/12400000/001546569.pdf';
    const withGov = approved(); withGov.laws = [{ ...covid, sources: [...covid.sources, govSource] }];
    expect(() => parsePublicRanking(JSON.stringify(withGov))).not.toThrow();
    const otherGov = approved(); otherGov.laws = [{ ...law, sources: [...law.sources, govSource] }];
    expect(() => parsePublicRanking(JSON.stringify(otherGov))).toThrow();
  });
  it('方法版・生成元・保留条件の欠落した配布を拒否する', () => {
    for (const change of [v => { delete v.generatedFrom.codeHashes; },
      v => { v.generatedFrom.methodSpecVersion = 'method-spec-v999.0'; },
      v => { delete v.generatedFrom.parameters; }]) {
      const value = approved(); change(value);
      expect(() => parsePublicRanking(JSON.stringify(value))).toThrow();
    }
  });

  it('リポジトリの ranking.json を読み、成立した法律の全件が額か理由つきで載っている', () => {
    const value = parsePublicRanking(committed);
    expect(value.approval).toEqual({ approvedAt: '2026-10-17', scope: 'all-laws', note });
    expect(value.laws.length + value.others.length).toBe(value.counts.enacted);
    expect(value.counts.enacted).toBe(3415);
    expect(new Set([...value.laws, ...value.others].map(item => item.id)).size).toBe(value.counts.enacted);
    for (const item of value.others) expect(Object.keys(item).sort()).toEqual(['id', 'outcome', 'reason', 'title']);
    expect(JSON.stringify(value.others)).not.toMatch(/Yen|中央値|四分位/);
  });
  it('確かさの4区分があり、参考は確かな額の後ろに並ぶ', () => {
    const value = parsePublicRanking(committed);
    expect(value.laws.every(item => ['高', '中', '低', '参考'].includes(item.certainty))).toBe(true);
    const flags = value.laws.map(item => item.certainty === '参考');
    expect(flags).toEqual([...flags].sort());
    expect(value.counts.confirmed + value.counts.reference).toBe(value.laws.length);
  });
  it('コロナ期と重なる法律と便益側が未測定の法律に注記がある', () => {
    const byId = new Map(parsePublicRanking(committed).laws.map(item => [item.id, item]));
    for (const id of ['衆法-189-20', '閣法-193-59', '閣法-196-2', '閣法-196-4']) expect(byId.get(id).notes).toContain('コロナ期と重なる');
    expect(byId.get('閣法-189-27').notes).toContain('便益側の一部が未測定');
  });
  it('承認の記録がある配布データは額を読む', () => {
    expect(parsePublicRanking(JSON.stringify(approved())).laws[0].amountMedianYen).toBe(19);
  });
  it('承認の記録が無いのに額がある配布データは拒否する', () => {
    const value = approved();
    value.approval = { approvedAt: null, scope: null, note: null };
    expect(() => parsePublicRanking(JSON.stringify(value))).toThrow('承認');
    value.approval = { approvedAt: null, scope: 'all-laws', note };
    expect(() => parsePublicRanking(JSON.stringify(value))).toThrow('承認');
  });
  it('人物の欄や未知のキーは拒否する', () => {
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), people: [] }))).toThrow('形式');
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, members: ['x'] }] }))).toThrow();
    const other = approved();
    other.others[0] = { ...other.others[0], amountMedianYen: 1 };
    expect(() => parsePublicRanking(JSON.stringify(other))).toThrow('結果');
  });
  it('幅の逆転と許可外の出典は拒否する。幅は確かさによらず0をまたいでよい（中央値は側の向きに正）', () => {
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, amountLowYen: 30 }] }))).toThrow('幅');
    expect(parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, amountLowYen: -5 }] })).laws[0].amountLowYen).toBe(-5);
    const reference = approved();
    reference.laws = [{ ...law, certainty: '参考', amountLowYen: -5 }];
    reference.counts = { ...reference.counts, confirmed: 0, reference: 1 };
    expect(parsePublicRanking(JSON.stringify(reference)).laws[0].amountLowYen).toBe(-5);
    expect(() => parsePublicRanking(JSON.stringify({ ...approved(), laws: [{ ...law, sources: ['https://example.com/x'] }] }))).toThrow('一次資料');
    expect(() => parsePublicRanking('x'.repeat(RANKING_TEXT_LIMIT + 1))).toThrow('ランキングのデータが大きすぎます。');
  });
  it('同じ法律が額と結果の両方に載る・件数が合わない配布データは拒否する', () => {
    const both = approved();
    both.others[0].id = law.id;
    expect(() => parsePublicRanking(JSON.stringify(both))).toThrow();
    const counts = approved();
    counts.counts.published = 2;
    expect(() => parsePublicRanking(JSON.stringify(counts))).toThrow('件数');
  });
});
