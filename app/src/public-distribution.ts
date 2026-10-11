export type PublicCitation = { id: string; title: string; url: string; license: string; locator: string; quote: string };
export type PublicActor = { id: string; label: string; date: string; action: string; identityNote: string; citationIds: string[] };
export type PublicCase = {
  schemaVersion: 'public-case/v1';
  snapshotId: string;
  caseId: string;
  title: string;
  scoringStatus: 'held';
  impactScale: null;
  gdpLoss: null;
  responsibilityShare: null;
  holdReason: string;
  periodNote: string;
  observationFrom: string;
  observationTo: string;
  implementations: { id: string; date: string; text: string }[];
  observations: { id: string; text: string; method: 'before_after_not_causal' | 'stated_figure_not_recomputed' }[];
  comparison: string;
  counterEvidence: string[];
  actors: PublicActor[];
  organizations: { id: string; name: string; relation: string }[];
  contextMentions: { id: string; label: string; basis: string }[];
  missingMaterials: string[];
  citations: PublicCitation[];
  statisticLink: { seriesId: 'real_gdp'; relation: 'temporal_overlap_not_attribution'; note: string };
  causeCandidates: { id: string; label: string; status: 'unestablished' }[];
};

const dateText = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value);
const prose = (value: unknown, limit = 4000) => typeof value === 'string' && value.trim().length > 0 && value.length <= limit;

/** 版を指定したときだけその版を読む。未指定の現在版へは落とさない。 */
export function distributionEconomyUrl(edition: string): string {
  if (edition && !/^[a-f0-9]{64}$/.test(edition)) throw new Error('統計版が不正です。');
  return edition ? `/distribution/releases/${edition}.json` : '/distribution/economy.json';
}
export function distributionCaseUrl(edition: string): string {
  if (edition && !/^[a-f0-9]{64}$/.test(edition)) throw new Error('統計版が不正です。');
  return edition ? `/distribution/cases/${edition}.json` : '/distribution/case.json';
}

export function parsePublicCase(text: string): PublicCase {
  if (text.length > 1_000_000) throw new Error('政策事例が大きすぎます。');
  const value = JSON.parse(text) as PublicCase;
  const allowed = ['schemaVersion', 'snapshotId', 'caseId', 'title', 'scoringStatus', 'impactScale', 'gdpLoss', 'responsibilityShare', 'holdReason', 'periodNote', 'observationFrom', 'observationTo', 'implementations', 'observations', 'comparison', 'counterEvidence', 'actors', 'organizations', 'contextMentions', 'missingMaterials', 'citations', 'statisticLink', 'causeCandidates'];
  if (!value || value.schemaVersion !== 'public-case/v1' || !/^[a-f0-9]{64}$/.test(value.snapshotId) || Object.keys(value).some(key => !allowed.includes(key))) throw new Error('政策事例の形式が不正です。');
  if (value.scoringStatus !== 'held' || value.impactScale !== null || value.gdpLoss !== null || value.responsibilityShare !== null) throw new Error('未確定の影響を点数や金額にしていません。');
  if (![value.caseId, value.title, value.holdReason, value.periodNote, value.comparison].every(item => prose(item)) || !dateText(value.observationFrom) || !dateText(value.observationTo) || value.observationFrom > value.observationTo) throw new Error('政策事例の期間が不正です。');
  if (!Array.isArray(value.citations) || value.citations.length < 3) throw new Error('出典が不足しています。');
  const citations = new Map<string, PublicCitation>();
  for (const citation of value.citations) {
    const url = new URL(citation.url);
    if (citations.has(citation.id) || url.protocol !== 'https:' || url.hostname !== 'www.fsa.go.jp' || url.username || url.password || ![citation.title, citation.license, citation.locator, citation.quote].every(item => prose(item, 500))) throw new Error('出典が不正です。');
    citations.set(citation.id, citation);
  }
  const lists = [value.implementations, value.observations, value.counterEvidence, value.actors, value.organizations, value.contextMentions, value.missingMaterials, value.causeCandidates];
  if (lists.some(list => !Array.isArray(list) || list.length === 0) || value.actors.length < 3) throw new Error('政策事例の項目が不足しています。');
  for (const actor of value.actors) {
    if (!prose(actor.label, 200) || !dateText(actor.date) || !prose(actor.action) || !prose(actor.identityNote) || !Array.isArray(actor.citationIds) || actor.citationIds.some(id => !citations.has(id)) || 'score' in actor) throw new Error('人物の行動が不正です。');
  }
  if (new Set(value.actors.map(actor => actor.label)).size < 3) throw new Error('複数人物の行動が不足しています。');
  for (const item of value.observations) if (!prose(item.text) || !['before_after_not_causal', 'stated_figure_not_recomputed'].includes(item.method)) throw new Error('観測結果が不正です。');
  for (const item of value.counterEvidence) if (!prose(item)) throw new Error('反証が不正です。');
  for (const item of value.missingMaterials) if (!prose(item, 1000)) throw new Error('不足資料が不正です。');
  for (const item of value.causeCandidates) if (item.status !== 'unestablished' || !prose(item.label)) throw new Error('原因候補が不正です。');
  if (value.statisticLink?.seriesId !== 'real_gdp' || value.statisticLink.relation !== 'temporal_overlap_not_attribution' || !prose(value.statisticLink.note)) throw new Error('統計との関係が不正です。');
  return value;
}
