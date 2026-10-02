import { DOMAINS, type Domain, type Period, type RankingOptions } from './ranking';

export type ViewState = {
  options: RankingOptions; query: string; house: string; roleClass: string;
  selectedPersonId: string; selectedActionKey: string; selectedPolicyId: string; selectedEvidenceId: string;
  assessment: 'actions' | 'outlook'; tab: 'actions' | 'policy' | 'evidence';
  history: 'view' | 'all';
};

export function readViewState(search: string, asOf: string): ViewState {
  const params = new URLSearchParams(search);
  const string = (key: string) => (params.get(key) ?? '').slice(0, 2000);
  const domain = string('domain');
  const period = string('period');
  const weight = (key: string, fallback: number) => {
    const raw = params.get(key);
    const value = Number(raw);
    return raw !== null && raw.trim() !== '' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : fallback;
  };
  const house = string('house');
  const role = string('role');
  const tab = string('tab');
  return {
    options: {
      domain: domain === 'overall' || DOMAINS.includes(domain as Domain) ? domain as RankingOptions['domain'] : 'economy',
      direction: string('direction') === 'benefit' ? 'benefit' : 'harm',
      period: ['2', '4', '8'].includes(period) ? Number(period) as Period : period === 'cumulative' ? 'cumulative' : 4,
      asOf, weights: { economy: weight('economy', 70), technology: weight('technology', 30) },
    },
    query: string('q'), house: ['衆議院', '参議院'].includes(house) ? house : 'all',
    roleClass: ['一般議員', '大臣', '非在職'].includes(role) ? role : 'all',
    selectedPersonId: string('person'), selectedActionKey: string('action'), selectedPolicyId: string('policy'), selectedEvidenceId: string('evidence'),
    assessment: string('assessment') === 'outlook' ? 'outlook' : 'actions',
    history: string('history') === 'all' ? 'all' : 'view',
    tab: tab === 'policy' || tab === 'evidence' ? tab : 'actions',
  };
}

/** URLSearchParamsへ直接渡せる、先頭の疑問符なしの検索文字列。 */
export function serializeViewState(state: ViewState): string {
  const params = new URLSearchParams();
  params.set('domain', state.options.domain); params.set('direction', state.options.direction); params.set('period', String(state.options.period));
  params.set('economy', String(state.options.weights.economy)); params.set('technology', String(state.options.weights.technology));
  const set = (key: string, value: string) => { if (value) params.set(key, value.slice(0, 2000)); };
  set('q', state.query);
  if (state.house !== 'all') set('house', state.house);
  if (state.roleClass !== 'all') set('role', state.roleClass);
  set('person', state.selectedPersonId); set('action', state.selectedActionKey); set('policy', state.selectedPolicyId);
  set('evidence', state.selectedEvidenceId);
  params.set('assessment', state.assessment); params.set('tab', state.tab);
  if (state.history === 'all') params.set('history', 'all');
  return params.toString();
}
