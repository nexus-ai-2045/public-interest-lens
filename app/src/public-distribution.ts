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

export type PublicRankingLaw = {
  id: string; title: string; side: 'loss' | 'benefit'; field: string; indicator: string; stage: string; enforcedOn: string;
  amountMedianYen: number; amountLowYen: number; amountHighYen: number; lowerBound: boolean; window: string;
  comparisonCountries: string[]; benefitStatus: string; group: string; sources: string[];
};
export type PublicRankingHeld = { id: string; title: string; side: 'loss' | 'benefit'; reasonCode: string; reason: string };
export type PublicRanking = {
  schema: 'public-ranking/v1';
  generatedFrom: { rules: string[]; inputs: Record<string, string> };
  approval: { approvedAt: string | null; approvedLaws: string[] };
  laws: PublicRankingLaw[];
  held: PublicRankingHeld[];
  counts: Record<'enacted' | 'evaluated' | 'dated' | 'staged' | 'amounted' | 'publishable' | 'published', number>;
};

export const distributionRankingUrl = '/distribution/ranking.json';
const LAW_ID = /^(閣法|衆法|参法)-\d+-\d+$/;
const SOURCE_HOSTS = new Set(['www.shugiin.go.jp', 'www.sangiin.go.jp', 'laws.e-gov.go.jp']);
const COUNT_KEYS = ['enacted', 'evaluated', 'dated', 'staged', 'amounted', 'publishable', 'published'];
const onlyKeys = (value: unknown, keys: string[]) => !!value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).every(key => keys.includes(key)) && keys.every(key => key in value);
const yen = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;

/** 許可したキーだけを読む。承認リストに無い法律の額・人物・未知のキーがあれば読み込みを拒否する。 */
export function parsePublicRanking(text: string): PublicRanking {
  if (text.length > 1_000_000) throw new Error('ランキングのデータが大きすぎます。');
  const value = JSON.parse(text) as PublicRanking;
  if (!onlyKeys(value, ['schema', 'generatedFrom', 'approval', 'laws', 'held', 'counts']) || value.schema !== 'public-ranking/v1') throw new Error('ランキングの形式が不正です。');
  if (!onlyKeys(value.generatedFrom, ['rules', 'inputs']) || !Array.isArray(value.generatedFrom.rules) || !value.generatedFrom.rules.every(rule => prose(rule, 80)) || !Object.values(value.generatedFrom.inputs ?? {}).every(hash => typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash))) throw new Error('生成元の記録が不正です。');
  const { approval } = value;
  if (!onlyKeys(approval, ['approvedAt', 'approvedLaws']) || !Array.isArray(approval.approvedLaws) || !approval.approvedLaws.every(id => typeof id === 'string' && LAW_ID.test(id))) throw new Error('承認の記録が不正です。');
  if (approval.approvedLaws.length ? !(typeof approval.approvedAt === 'string' && dateText(approval.approvedAt)) : approval.approvedAt !== null) throw new Error('承認日が不正です。');
  const approved = new Set(approval.approvedLaws);
  if (!Array.isArray(value.laws) || !Array.isArray(value.held)) throw new Error('ランキングの項目が不足しています。');
  const seen = new Set<string>();
  for (const law of value.laws) {
    if (!onlyKeys(law, ['id', 'title', 'side', 'field', 'indicator', 'stage', 'enforcedOn', 'amountMedianYen', 'amountLowYen', 'amountHighYen', 'lowerBound', 'window', 'comparisonCountries', 'benefitStatus', 'group', 'sources'])) throw new Error('法律の項目が不正です。');
    if (!approved.has(law.id) || seen.has(law.id)) throw new Error('承認されていない法律の額は表示しません。');
    seen.add(law.id);
    if (!['loss', 'benefit'].includes(law.side) || ![law.title, law.field, law.indicator, law.stage, law.window, law.benefitStatus, law.group].every(item => prose(item, 500)) || !dateText(law.enforcedOn) || typeof law.lowerBound !== 'boolean') throw new Error('法律の項目が不正です。');
    if (![law.amountMedianYen, law.amountLowYen, law.amountHighYen].every(yen) || law.amountLowYen > law.amountMedianYen || law.amountMedianYen > law.amountHighYen) throw new Error('額の幅が不正です。');
    if (!Array.isArray(law.comparisonCountries) || !law.comparisonCountries.length || !law.comparisonCountries.every(code => /^[A-Z]{3}$/.test(code))) throw new Error('比較国が不正です。');
    if (!Array.isArray(law.sources) || !law.sources.length) throw new Error('一次資料がありません。');
    for (const source of law.sources) {
      const url = new URL(source);
      if (url.protocol !== 'https:' || !SOURCE_HOSTS.has(url.hostname) || url.username || url.password) throw new Error('一次資料の URL が不正です。');
    }
  }
  if (approval.approvedLaws.some(id => !seen.has(id))) throw new Error('承認した法律が見つかりません。');
  for (const item of value.held) {
    if (!onlyKeys(item, ['id', 'title', 'side', 'reasonCode', 'reason']) || !LAW_ID.test(item.id) || seen.has(item.id) || !['loss', 'benefit'].includes(item.side) || !/^(R\d|APPROVAL|SOURCE)$/.test(item.reasonCode) || !prose(item.title, 500) || !prose(item.reason, 500)) throw new Error('保留の項目が不正です。');
    seen.add(item.id);
  }
  if (!onlyKeys(value.counts, COUNT_KEYS) || !COUNT_KEYS.every(key => Number.isSafeInteger(value.counts[key as keyof PublicRanking['counts']]) && value.counts[key as keyof PublicRanking['counts']] >= 0)) throw new Error('件数が不正です。');
  if (value.counts.published !== value.laws.length) throw new Error('公開件数が一致しません。');
  return value;
}
