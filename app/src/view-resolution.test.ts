import { describe, expect, it } from 'vitest';
import { actionKey, actionMatchesView, type RankingDataset } from './ranking';
import { rankingDataset } from './ranking-data';
import { readViewState } from './view-state';
import { getRelatedActions, resolveView } from './view-resolution';

const state = () => readViewState('', rankingDataset.asOf);
const dataset = (): RankingDataset => ({ ...rankingDataset, involvements: rankingDataset.involvements.map(action => ({ ...action })) });

describe('行動表示の選択整合性', () => {
  it('現在条件に合う行動がない人物は行動・政策・根拠を空にする', () => {
    const data = dataset();
    const personId = data.people[0].id;
    data.involvements = data.involvements.filter(action => action.personId !== personId);
    const source = rankingDataset.involvements[0];
    data.involvements.push({ ...source, personId, actionDate: '2000-01-01' });
    const result = resolveView(data, { ...state(), selectedPersonId: personId });
    expect(result.selectedPersonId).toBe(personId);
    expect(result.selectedActionKey).toBe('');
    expect(result.selectedPolicyId).toBe('');
    expect(result.selectedEvidenceId).toBe('');
  });

  it('旧URLで指定された対象外行動だけは全履歴で復元する', () => {
    const data = dataset();
    const old = { ...data.involvements[0], actionDate: '2000-01-01' };
    data.involvements.push(old);
    const input = { ...state(), selectedPersonId: old.personId, selectedActionKey: actionKey(old), selectedEvidenceId: old.evidenceIds[0] };
    const result = resolveView(data, input, 'url');
    expect(result.history).toBe('all');
    expect(result.selectedActionKey).toBe(actionKey(old));
    expect(result.selectedEvidenceId).toBe(old.evidenceIds[0]);
  });

  it('不明な行動キーはURL由来でも全履歴へ切り替えない', () => {
    const result = resolveView(dataset(), { ...state(), selectedActionKey: 'unknown' }, 'url');
    expect(result.history).toBe('view');
    expect(result.selectedActionKey).not.toBe('unknown');
  });

  it('通常操作では対象外の選択を全履歴へ自動拡張しない', () => {
    const data = dataset();
    const old = { ...data.involvements[0], actionDate: '2000-01-01' };
    data.involvements.push(old);
    const result = resolveView(data, { ...state(), selectedPersonId: old.personId, selectedActionKey: actionKey(old) });
    expect(result.history).toBe('view');
    expect(result.selectedActionKey).not.toBe(actionKey(old));
  });

  it('全履歴から現在条件へ戻すと行動・政策・根拠の参照を一致させる', () => {
    const data = dataset();
    const old = { ...data.involvements[0], actionDate: '2000-01-01' };
    data.involvements.push(old);
    const all = resolveView(data, { ...state(), history: 'all', selectedPersonId: old.personId, selectedActionKey: actionKey(old) });
    const current = resolveView(data, { ...all, history: 'view', selectedActionKey: '', selectedPolicyId: '', selectedEvidenceId: '' });
    const selected = data.involvements.find(action => actionKey(action) === current.selectedActionKey)!;
    const policy = data.policies.find(item => item.id === selected.policyId)!;
    expect(actionMatchesView(selected, policy, current.options)).toBe(true);
    expect(current.selectedPolicyId).toBe(policy.id);
    expect([...selected.evidenceIds, ...policy.evidenceIds]).toContain(current.selectedEvidenceId);
  });

  it('保留・関係情報と同一政策の異なる行動を現在条件のツリーに保持する', () => {
    const data = dataset();
    const original = data.involvements[0];
    const context = { ...original, role: 'context' as const, description: '関係情報の追加記録' };
    data.involvements.push(context);
    data.policies = data.policies.map(policy => policy.id === original.policyId ? { ...policy, reviewStatus: 'pending' } : policy);
    const related = getRelatedActions(data, original.personId, state().options, 'view');
    expect(related.some(item => actionKey(item.action) === actionKey(original))).toBe(true);
    expect(related.some(item => actionKey(item.action) === actionKey(context))).toBe(true);
  });
});
