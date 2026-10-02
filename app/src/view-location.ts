import { actionKey, type RankingDataset } from './ranking';
import { registeredRankingVersion } from './ranking-snapshot';
import { readViewState, type ViewState } from './view-state';
import { resolveView } from './view-resolution';

export type ViewPage = 'ranking' | 'person' | 'action';
/** 架空版の算定契約と全データ内容を固定します。実評価版とは別の名前空間です。 */
export const viewDataVersion = registeredRankingVersion;
export type ViewLocation = { state: ViewState; page: ViewPage; invalid: string | null };

export function readViewLocation(pathname: string, search: string, asOf: string, data: RankingDataset): ViewLocation {
  const params = new URLSearchParams(search);
  if (params.has('view')) params.set('direction', params.get('view')!);
  if (params.has('years')) params.set('period', params.get('years')!);
  let state = readViewState(params.toString(), asOf);
  let page: ViewPage = 'ranking';
  const fail = (invalid: string): ViewLocation => ({ state, page, invalid });
  if (params.has('version')) {
    try { if (params.get('version') !== viewDataVersion(data)) return fail('指定された評価版は利用できません。'); }
    catch { return fail('指定された評価版のデータ内容は利用できません。'); }
  }
  const ids = data.involvements.flatMap(action => action.id === undefined ? [] : [action.id]);
  if (ids.some(id => !id.trim()) || new Set(ids).size !== ids.length) return fail('行動IDが空または重複しています。');
  const match = /^\/(people|actions)\/([^/]+)\/?$/.exec(pathname);
  if (match) {
    page = match[1] === 'people' ? 'person' : 'action';
    let id: string;
    try { id = decodeURIComponent(match[2]); } catch { return fail('URLの識別子が不正です。'); }
    if (page === 'person') {
      state = { ...state, selectedPersonId: id, selectedActionKey: '', selectedPolicyId: '' };
    } else {
      const action = data.involvements.find(item => item.id === id);
      if (!action) return fail('指定された行動は見つかりません。');
      state = { ...state, selectedPersonId: action.personId, selectedActionKey: actionKey(action), selectedPolicyId: action.policyId };
    }
  } else if (!['/', '/ranking', '/ranking/'].includes(pathname)) {
    return fail('指定されたページは見つかりません。');
  } else if (state.selectedActionKey) {
    page = 'action';
  } else if (state.selectedPersonId) {
    page = 'person';
  }
  const explicitPerson = state.selectedPersonId;
  if (explicitPerson && !data.people.some(person => person.id === explicitPerson)) return fail('指定された人物は見つかりません。');
  if (state.selectedActionKey) {
    const action = data.involvements.find(item => actionKey(item) === state.selectedActionKey && item.personId === explicitPerson);
    if (!action) return fail('指定された行動は見つかりません。');
    if (!action.id) return fail('この行動には安定したIDがありません。');
    const policy = data.policies.find(item => item.id === action.policyId);
    if (state.selectedEvidenceId && ![...action.evidenceIds, ...(policy?.evidenceIds ?? [])].includes(state.selectedEvidenceId)) return fail('指定された根拠はこの行動に対応しません。');
  }
  const resolved = resolveView(data, state, 'url');
  if (explicitPerson && resolved.selectedPersonId !== explicitPerson) return fail('指定された人物は現在の比較対象外です。');
  return { state: resolved, page, invalid: null };
}

/** 既定値・導出可能な政策ID・説明文・一時検索状態はURLに保存しません。 */
export function serializeViewLocation(state: ViewState, data: RankingDataset, page: ViewPage, pinVersion?: string): string {
  let path = '/ranking';
  const action = data.involvements.find(item => actionKey(item) === state.selectedActionKey && item.personId === state.selectedPersonId);
  if (page === 'person') {
    if (!data.people.some(person => person.id === state.selectedPersonId)) throw new Error('指定された人物は見つかりません。');
    path = `/people/${encodeURIComponent(state.selectedPersonId)}`;
  } else if (page === 'action') {
    if (!action?.id || data.involvements.filter(item => item.id === action.id).length !== 1) throw new Error('行動IDが空または重複しています。');
    path = `/actions/${encodeURIComponent(action.id)}`;
  }
  const params = new URLSearchParams();
  if (state.options.domain !== 'economy') params.set('domain', state.options.domain);
  if (state.options.direction !== 'harm') params.set('view', state.options.direction);
  if (state.options.period !== 4) params.set('years', String(state.options.period));
  if (state.options.domain === 'overall') {
    if (state.options.weights.economy !== 70) params.set('economy', String(state.options.weights.economy));
    if (state.options.weights.technology !== 30) params.set('technology', String(state.options.weights.technology));
  }
  if (state.house !== 'all') params.set('house', state.house);
  if (state.roleClass !== 'all') params.set('role', state.roleClass);
  if (state.history === 'all') params.set('history', 'all');
  if (state.assessment !== 'actions') params.set('assessment', state.assessment);
  if (state.tab !== 'actions') params.set('tab', state.tab);
  if (page === 'action' && state.selectedEvidenceId) {
    const policy = data.policies.find(item => item.id === action?.policyId);
    if (![...(action?.evidenceIds ?? []), ...(policy?.evidenceIds ?? [])].includes(state.selectedEvidenceId)) throw new Error('根拠が行動に対応しません。');
    params.set('evidence', state.selectedEvidenceId);
  }
  if (pinVersion !== undefined) {
    if (pinVersion !== viewDataVersion(data)) throw new Error('指定された評価版は利用できません。');
    params.set('version', pinVersion);
  }
  const query = params.toString();
  return `${path}${query ? `?${query}` : ''}`;
}
