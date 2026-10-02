import { describe, expect, it } from 'vitest';
import { getPersonSummaries } from './person-summary';
import { rankPeople, type RankingDataset, type RankingOptions } from './ranking';

const options: RankingOptions = { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-09-24', weights: { economy: 70, technology: 30 } };
function fixture(benefit = true, harm = true): RankingDataset {
  return {
    schemaVersion: 'ranking-dataset/v1', fictional: true, asOf: options.asOf,
    coverage: { scope: '架空', assessedPeople: 1, targetPeople: 1, sourceStatus: '架空資料' },
    people: [{ id: 'p', name: '架空人物' }],
    evidence: [{ id: 'e', date: '2025-01-01', title: '架空資料', source: '架空', summary: '架空の確認済み資料', kind: 'verified' }],
    policies: (['benefit', 'harm'] as const).map(direction => ({ id: direction, title: '架空政策', domain: 'economy', direction, impact: direction === 'benefit' ? 3 : 1, reviewStatus: 'reviewed', rationale: '架空', counterEvidence: '架空', alternativeExplanation: '架空', evidenceIds: ['e'] })),
    involvements: (['benefit', 'harm'] as const).filter(direction => direction === 'benefit' ? benefit : harm).map(direction => ({ personId: 'p', policyId: direction, actionDate: '2025-01-01', role: 'lead', description: '架空の行動', evidenceIds: ['e'] })),
  };
}
describe('人物の双方向要約', () => {
  it('既存の独立した算定値を比較し、新しい差引点数を作らない', () => {
    const data = fixture();
    expect(getPersonSummaries(data, options).get('p')).toEqual({ benefit: 3, harm: 1, trend: 'benefit_lead', label: '貢献優勢' });
    data.policies[0].impact = 1; data.policies[1].impact = 3;
    expect(getPersonSummaries(data, options).get('p')).toEqual({ benefit: 1, harm: 3, trend: 'harm_lead', label: '悪影響優勢' });
  });
  it('丸め済みの同点は同程度とする', () => {
    const data = fixture(); data.policies.forEach(policy => { policy.impact = 1; });
    expect(getPersonSummaries(data, options).get('p')).toEqual({ benefit: 1, harm: 1, trend: 'balanced', label: '同程度' });
    data.policies[0].impact = 3; data.policies[1].domain = 'technology';
    expect(getPersonSummaries(data, { ...options, domain: 'overall', weights: { economy: 24.99, technology: 75.01 } }).get('p')).toEqual({ benefit: .75, harm: .75, trend: 'balanced', label: '同程度' });
  });
  it.each([
    [true, false, 'benefit_only', '貢献の記録あり・悪影響は未評価', 3, null],
    [false, true, 'harm_only', '悪影響の記録あり・貢献は未評価', null, 1],
    [false, false, 'insufficient', '判断材料不足', null, null],
  ] as const)('片側・両側の未評価を0点に置換しない (%s, %s)', (benefit, harm, trend, label, b, h) => {
    expect(getPersonSummaries(fixture(benefit, harm), options).get('p')).toEqual({ benefit: b, harm: h, trend, label });
  });
  it('有効な算定が丸めで0になっても未評価とは区別する', () => {
    const data = fixture(true, false);
    const weighted = { ...options, domain: 'overall' as const, weights: { economy: .001, technology: 100 } };
    expect(getPersonSummaries(data, weighted).get('p')).toEqual({ benefit: 0, harm: null, trend: 'benefit_only', label: '貢献の記録あり・悪影響は未評価' });
  });
  it('総合の全重み0は未評価だが、単独分野は重みを使わない', () => {
    const data = fixture(); const zero = { ...options, weights: { economy: 0, technology: 0 } };
    expect(getPersonSummaries(data, { ...zero, domain: 'overall' }).get('p')?.trend).toBe('insufficient');
    expect(getPersonSummaries(data, zero).get('p')?.benefit).toBe(3);
    data.policies.forEach(policy => { policy.domain = 'technology'; });
    expect(getPersonSummaries(data, { ...zero, domain: 'technology' }).get('p')?.benefit).toBe(3);
  });
  it.each(['fiscal', 'security', 'governance'] as const)('準備中の分野 %s は判断材料不足とする', domain => {
    expect(getPersonSummaries(fixture(), { ...options, domain }).get('p')).toEqual({ benefit: null, harm: null, trend: 'insufficient', label: '判断材料不足' });
  });
  it('展望表示では行動評価を要約として流用しない', () => {
    expect(getPersonSummaries(fixture(), options, 'outlook').get('p')).toEqual({ benefit: null, harm: null, trend: 'insufficient', label: '判断材料不足' });
  });
  it('同一政策の複数行動は最大役割だけを算定し、入力・方向・順位を変えない', () => {
    const data = fixture(); data.involvements.push({ ...data.involvements[0], role: 'vote', description: '架空の採決' });
    const before = structuredClone(data); const beforeOptions = structuredClone(options);
    const ranks = rankPeople(data, options);
    expect(getPersonSummaries(data, options).get('p')?.benefit).toBe(3);
    expect(data).toEqual(before); expect(options).toEqual(beforeOptions);
    expect(rankPeople(data, options)).toEqual(ranks);
    expect(getPersonSummaries(data, { ...options, direction: 'benefit' })).toEqual(getPersonSummaries(data, options));
  });
});
