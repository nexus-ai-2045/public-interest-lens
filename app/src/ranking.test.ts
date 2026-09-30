import { describe, expect, it } from 'vitest';
import { actionKey, actionMatchesView, rankPeople, type RankingOptions } from './ranking';
import { rankingDataset } from './ranking-data';

const fixture = () => structuredClone(rankingDataset);
const defaults: RankingOptions = { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-09-24', weights: { economy: 70, technology: 30 } };

describe('行動から人物への評価契約', () => {
  it('表示条件は期間の両端を含み、未来・期間外・別方向・別分野を除く', () => {
    const data = fixture();
    const action = data.involvements.find(item => item.personId === 'fiction-a')!;
    const policy = data.policies.find(item => item.id === action.policyId)!;
    expect(actionMatchesView({ ...action, actionDate: '2022-09-24' }, policy, defaults)).toBe(true);
    expect(actionMatchesView({ ...action, actionDate: defaults.asOf }, policy, defaults)).toBe(true);
    expect(actionMatchesView({ ...action, actionDate: '2022-09-23' }, policy, defaults)).toBe(false);
    expect(actionMatchesView({ ...action, actionDate: '2026-09-25' }, policy, defaults)).toBe(false);
    expect(actionMatchesView(action, { ...policy, direction: 'benefit' }, defaults)).toBe(false);
    expect(actionMatchesView(action, { ...policy, domain: 'technology' }, defaults)).toBe(false);
    expect(actionMatchesView({ ...action, actionDate: '2000-01-01' }, policy, { ...defaults, period: 'cumulative' })).toBe(true);
  });

  it('表示条件は保留・参考行動も含み、総合では全分野を含む', () => {
    const data = fixture();
    const action = data.involvements.find(item => item.personId === 'fiction-a')!;
    const policy = data.policies.find(item => item.id === action.policyId)!;
    expect(actionMatchesView({ ...action, role: 'context', evidenceIds: [] }, { ...policy, reviewStatus: 'pending' }, defaults)).toBe(true);
    expect(actionMatchesView(action, { ...policy, domain: 'fiscal' }, { ...defaults, domain: 'overall', weights: { economy: 0, technology: 0 } })).toBe(true);
  });

  it('分野と貢献・悪影響を切り替えると独立した順位を返す', () => {
    const harm = rankPeople(fixture(), defaults);
    const benefit = rankPeople(fixture(), { ...defaults, direction: 'benefit' });
    const technology = rankPeople(fixture(), { ...defaults, domain: 'technology', direction: 'benefit' });
    expect(harm[0].person.id).toBe('fiction-a');
    expect(benefit[0].person.id).toBe('fiction-b');
    expect(technology[0].person.id).toBe('fiction-c');
  });

  it('同一人物・政策の提出と採決は最大の役割を一度だけ算定する', () => {
    const data = fixture();
    const lead = data.involvements.find(item => item.personId === 'fiction-a')!;
    data.involvements.push({ ...lead, role: 'vote', description: '架空の採決', evidenceIds: [...lead.evidenceIds] });
    expect(rankPeople(data, defaults).find(row => row.person.id === 'fiction-a')?.score).toBe(3);
    expect(actionKey(lead)).not.toBe(actionKey(data.involvements.at(-1)!));
  });

  it('取得日でなく行動日で2年・4年・累積を切り替える', () => {
    const data = fixture();
    data.involvements.filter(item => item.personId === 'fiction-a').forEach(item => { item.actionDate = '2024-09-23'; });
    expect(rankPeople(data, { ...defaults, period: 2 }).find(row => row.person.id === 'fiction-a')?.score).toBeNull();
    expect(rankPeople(data, { ...defaults, period: 4 }).find(row => row.person.id === 'fiction-a')?.score).toBe(3);
    data.involvements.filter(item => item.personId === 'fiction-a').forEach(item => { item.actionDate = '2000-01-01'; });
    expect(rankPeople(data, { ...defaults, period: 'cumulative' }).find(row => row.person.id === 'fiction-a')?.score).toBe(3);
  });

  it('根拠不足と未検証分野は0点ではなく未評価にする', () => {
    const data = fixture();
    data.evidence.filter(item => ['e-action-a', 'e-action-a-vote'].includes(item.id)).forEach(item => { item.kind = 'unknown'; });
    expect(rankPeople(data, defaults).find(row => row.person.id === 'fiction-a')).toMatchObject({ score: null, rank: null, heldCount: 1 });
    expect(rankPeople(data, { ...defaults, domain: 'fiscal' }).every(row => row.score === null)).toBe(true);
  });

  it('個人の賛否は本人の確認済み資料がなければ採点しない', () => {
    const data = fixture();
    const action = data.involvements.find(item => item.role === 'vote')!;
    action.evidenceIds = [];
    expect(rankPeople(data, { ...defaults, domain: 'technology', direction: 'benefit' }).find(row => row.person.id === action.personId)?.score).toBeNull();
  });

  it('全重み0、重複ID、欠落参照、架空フラグ不一致を拒否する', () => {
    expect(rankPeople(fixture(), { ...defaults, domain: 'overall', weights: { economy: 0, technology: 0 } }).every(row => row.score === null)).toBe(true);
    const duplicate = fixture(); duplicate.people.push(duplicate.people[0]);
    expect(() => rankPeople(duplicate, defaults)).toThrow();
    const missing = fixture(); missing.involvements[0].evidenceIds = ['missing'];
    expect(() => rankPeople(missing, defaults)).toThrow();
    const fakeFlag = fixture(); fakeFlag.fictional = false;
    expect(() => rankPeople(fakeFlag, defaults)).toThrow();
  });

  it('入力順に依存せず、同点は同順位にする', () => {
    const data = fixture();
    const first = rankPeople(data, defaults);
    data.people.reverse(); data.involvements.reverse(); data.policies.reverse();
    expect(rankPeople(data, defaults)).toEqual(first);
  });
});
