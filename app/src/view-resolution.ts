import { actionKey, actionMatchesView, rankPeople, type RankingDataset, type RankingOptions } from './ranking';
import type { ViewState } from './view-state';

export function getRelatedActions(data: RankingDataset, personId: string, options: RankingOptions, history: ViewState['history']) {
  const policies = new Map(data.policies.map(policy => [policy.id, policy]));
  return data.involvements.filter(action => action.personId === personId).flatMap(action => {
    const policy = policies.get(action.policyId);
    return policy && (history === 'all' || actionMatchesView(action, policy, options)) ? [{ action, policy }] : [];
  }).sort((a, b) => b.action.actionDate.localeCompare(a.action.actionDate));
}

/** URL由来の旧行動リンクだけ全履歴へ広げ、通常操作は表示条件を維持する。 */
export function resolveView(data: RankingDataset, state: ViewState, origin: 'url' | 'interaction' = 'interaction'): ViewState {
  const visible = rankPeople(data, state.options).filter(row => row.person.name.includes(state.query.trim()) && (state.house === 'all' || row.person.house === state.house) && (state.roleClass === 'all' || row.person.roleClass === state.roleClass));
  const person = visible.find(row => row.person.id === state.selectedPersonId) ?? visible[0];
  const all = getRelatedActions(data, person?.person.id ?? '', state.options, 'all');
  const explicit = all.find(item => actionKey(item.action) === state.selectedActionKey);
  const restoreLegacy = origin === 'url' && person?.person.id === state.selectedPersonId && explicit && !actionMatchesView(explicit.action, explicit.policy, state.options);
  const history = state.history === 'all' || restoreLegacy ? 'all' : 'view';
  const actions = getRelatedActions(data, person?.person.id ?? '', state.options, history).map(item => item.action);
  const scoredAction = actions.find(item => person?.contributions.some(contribution => contribution.actionKey === actionKey(item)));
  const action = actions.find(item => actionKey(item) === state.selectedActionKey) ?? actions.find(item => item.policyId === state.selectedPolicyId) ?? scoredAction ?? actions[0];
  const policy = data.policies.find(item => item.id === action?.policyId);
  const availableEvidence = [...(action?.evidenceIds ?? []), ...(policy?.evidenceIds ?? [])];
  const selectedEvidenceId = availableEvidence.includes(state.selectedEvidenceId) ? state.selectedEvidenceId : availableEvidence[0] ?? '';
  return { ...state, history, selectedPersonId: person?.person.id ?? '', selectedActionKey: action ? actionKey(action) : '', selectedPolicyId: action?.policyId ?? '', selectedEvidenceId };
}
