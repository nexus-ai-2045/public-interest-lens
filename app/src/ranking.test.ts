import { describe, expect, it } from 'vitest';
import { rankPeople, type RankingOptions } from './ranking';
import { rankingDataset } from './ranking-data';

const options: RankingOptions = { fromYear: 1976, toYear: 2026, weights: { productivity: 1, income: 1, fiscal: 1 } };
const copy = () => structuredClone(rankingDataset);
describe('人物ランキングの算定契約', () => {
  it('重み変更で順位が逆転し証拠不足は未評価になる', () => {
    const productivity = rankPeople(copy(), { ...options, weights: { productivity: 1, income: 0, fiscal: 0 } });
    const income = rankPeople(copy(), { ...options, weights: { productivity: 0, income: 1, fiscal: 0 } });
    expect(productivity[0].person.id).toBe('fiction-a');
    expect(income[0].person.id).toBe('fiction-b');
    expect(productivity.find(row => row.person.id === 'fiction-d')).toMatchObject({ score: null, rank: null, omittedCount: 1, coverage: 0 });
  });
  it('全重みゼロなら全員未評価', () => {
    expect(rankPeople(copy(), { ...options, weights: { productivity: 0, income: 0, fiscal: 0 } }).every(row => row.rank === null && row.score === null)).toBe(true);
  });
  it('期間外の政策は集計しない', () => {
    expect(rankPeople(copy(), { ...options, fromYear: 2025 }).every(row => row.score === null)).toBe(true);
  });
  it('同一表示点は競技順位、入力順に依存しない', () => {
    const data = copy();
    data.involvements = [
      { personId: 'fiction-a', policyId: 'policy-p', role: '提案', attribution: 1, evidenceIds: ['e-action'] },
      { personId: 'fiction-b', policyId: 'policy-p', role: '提案', attribution: 1, evidenceIds: ['e-action'] },
      { personId: 'fiction-c', policyId: 'policy-p', role: '提案', attribution: .5, evidenceIds: ['e-action'] },
    ];
    const rows = rankPeople(data, options);
    expect(rows.map(row => row.rank)).toEqual([1, 1, 3, null]);
    data.people.reverse(); data.involvements.reverse();
    expect(rankPeople(data, options)).toEqual(rows);
  });
  it.each(['ai', 'unknown', 'computed'] as const)('%sを確認済み証拠として使わない', kind => {
    const data = copy(); data.evidence.forEach(e => { e.kind = kind; });
    expect(rankPeople(data, options).every(row => row.score === null)).toBe(true);
  });
  it('未レビュー政策を除外する', () => {
    const data = copy(); data.policies.forEach(p => { p.reviewStatus = 'pending'; });
    expect(rankPeople(data, options).every(row => row.rank === null)).toBe(true);
  });
  it('空の証拠も除外する', () => {
    const data = copy(); data.involvements.forEach(i => { i.evidenceIds = []; });
    expect(rankPeople(data, options).every(row => row.rank === null)).toBe(true);
  });
  it('欠落した証拠参照を拒否する', () => {
    const data = copy(); data.policies[0].evidenceIds.push('missing');
    expect(() => rankPeople(data, options)).toThrow();
  });
  it('関与の証拠・人物・政策参照が欠落した場合も拒否する', () => {
    for (const field of ['personId', 'policyId', 'evidenceIds'] as const) {
      const data = copy();
      if (field === 'evidenceIds') data.involvements[0][field] = ['missing'];
      else data.involvements[0][field] = 'missing';
      expect(() => rankPeople(data, options)).toThrow();
    }
  });
  it('丸め前の差があっても表示点が同じなら同順位にする', () => {
    const data = copy();
    data.involvements = [
      { personId: 'fiction-a', policyId: 'policy-p', role: '提案', attribution: .99999, evidenceIds: ['e-action'] },
      { personId: 'fiction-b', policyId: 'policy-p', role: '提案', attribution: 1, evidenceIds: ['e-action'] },
    ];
    expect(rankPeople(data, options).slice(0, 2).map(row => [row.person.id, row.rank, row.score])).toEqual([
      ['fiction-a', 1, 24], ['fiction-b', 1, 24],
    ]);
  });
  it('対象期間の両端を含め、入力を変更しない', () => {
    const data = copy(); const original = copy();
    const rows = rankPeople(data, { ...options, fromYear: 1995, toYear: 1995 });
    expect(rows[0]).toMatchObject({ eligibleCount: 1, score: 24 });
    expect(data).toEqual(original);
  });
  it('部分的な証拠不足を件数と網羅率に残す', () => {
    const data = copy(); data.involvements[1].evidenceIds = ['e-pending'];
    expect(rankPeople(data, options).find(row => row.person.id === 'fiction-a')).toMatchObject({ eligibleCount: 1, omittedCount: 1, coverage: .5 });
  });
  it('同一人物同一政策の重複を拒否する', () => {
    const data = copy(); data.involvements.push(data.involvements[0]);
    expect(() => rankPeople(data, options)).toThrow();
  });
  it('ID重複を拒否する', () => {
    const data = copy(); data.people.push(data.people[0]);
    expect(() => rankPeople(data, options)).toThrow();
  });
  it.each([NaN, Infinity, -1, 101])('不正な影響度 %s を拒否する', harm => {
    const data = copy(); data.policies[0].harm = harm;
    expect(() => rankPeople(data, options)).toThrow();
  });
  it('不正な重み・年・日付・帰属係数を拒否する', () => {
    expect(() => rankPeople(copy(), { ...options, weights: { ...options.weights, income: NaN } })).toThrow();
    expect(() => rankPeople(copy(), { ...options, fromYear: 2030 })).toThrow();
    const data = copy(); data.evidence[0].date = '2025-02-30';
    expect(() => rankPeople(data, options)).toThrow();
    const invalid = copy(); invalid.involvements[0].attribution = 1.01;
    expect(() => rankPeople(invalid, options)).toThrow();
  });
});
