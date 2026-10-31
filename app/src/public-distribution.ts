import type { PublicMembers } from './members-build';
import type { PublicMembersReference } from './members-reference';
import { validGenerationMetadata, type GenerationMetadata } from './generation-metadata';
/** コロナ対応の費用便益（covid-benefit-v1）の観測グループ。比較国を持たない。 */
export const COVID_BENEFIT_GROUP = '全体指標-コロナ費用便益';
/** コロナ対応の費用便益（支出×帰属×乗数）のグループか。法律ごとに「-<法律id>」が付く。 */
export const isCovidBenefitGroup = (group?: string) => !!group && group.startsWith(`${COVID_BENEFIT_GROUP}-`);
export type PublicCitation = { id: string; title: string; url: string; license: string; locator: string; quote: string };
export type PublicActor = { id: string; label: string; date: string; action: string; identityNote: string; citationIds: string[]; identityCitationIds?: string[] };
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
    if (!prose(actor.label, 200) || !dateText(actor.date) || !prose(actor.action) || !prose(actor.identityNote) || !Array.isArray(actor.citationIds) || actor.citationIds.some(id => !citations.has(id)) || (actor.identityCitationIds !== undefined && (!Array.isArray(actor.identityCitationIds) || actor.identityCitationIds.some(id => !citations.has(id)))) || 'score' in actor) throw new Error('人物の行動が不正です。');
  }
  if (new Set(value.actors.map(actor => actor.label)).size < 3) throw new Error('複数人物の行動が不足しています。');
  for (const item of value.observations) if (!prose(item.text) || !['before_after_not_causal', 'stated_figure_not_recomputed'].includes(item.method)) throw new Error('観測結果が不正です。');
  for (const item of value.counterEvidence) if (!prose(item)) throw new Error('反証が不正です。');
  for (const item of value.missingMaterials) if (!prose(item, 1000)) throw new Error('不足資料が不正です。');
  for (const item of value.causeCandidates) if (item.status !== 'unestablished' || !prose(item.label)) throw new Error('原因候補が不正です。');
  if (value.statisticLink?.seriesId !== 'real_gdp' || value.statisticLink.relation !== 'temporal_overlap_not_attribution' || !prose(value.statisticLink.note)) throw new Error('統計との関係が不正です。');
  return value;
}

export type Certainty = '高' | '中' | '低' | '参考';
export type PublicRankingLaw = {
  id: string; title: string; side: 'loss' | 'benefit'; certainty: Certainty; notes: string[]; field: string; indicator: string; stage: string; enforcedOn: string;
  amountMedianYen: number; amountLowYen: number; amountHighYen: number; lowerBound: boolean; window: string;
  comparisonCountries: string[]; benefitStatus: string; group: string; sources: string[];
  demotedReason?: string; demotedBasis?: string;
};
export type PublicRankingOther = { id: string; title: string; outcome: string; reason: string };
export type PublicRanking = {
  schema: 'public-ranking/v3';
  generatedFrom: { rules: string[]; inputs: Record<string, string>; parameters: { heldOut: string[]; noAmount: string[] } } & GenerationMetadata;
  approval: { approvedAt: string | null; scope: 'all-laws' | null; note: string | null };
  laws: PublicRankingLaw[];
  others: PublicRankingOther[];
  counts: Record<'enacted' | 'evaluated' | 'dated' | 'staged' | 'published' | 'confirmed' | 'reference' | 'others', number>;
};

export const distributionRankingUrl = '/distribution/ranking.json';
// 衆議院の制定法律ページを出典に残した公開ランキングの文字数上限。
// 現在の生成結果は約300万字。成立した法律がすべて額ありになり、許可した出典が1件増えても収まる。
export const RANKING_TEXT_LIMIT = 4_000_000;
// 国民投票法の法律案（衆法-166-）は議案情報の番号が空欄のまま台帳にある。id は台帳どおり。
const LAW_ID = /^(閣法|衆法|参法)-\d+-\d*$/;
const SOURCE_HOSTS = new Set(['www.shugiin.go.jp', 'www.sangiin.go.jp', 'laws.e-gov.go.jp']);
const COUNT_KEYS = ['enacted', 'evaluated', 'dated', 'staged', 'published', 'confirmed', 'reference', 'others'];
export const CERTAINTIES = ['高', '中', '低', '参考'];
const onlyKeys = (value: unknown, keys: string[]) => !!value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).every(key => keys.includes(key)) && keys.every(key => key in value);
const yen = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const signedYen = (value: unknown) => Number.isSafeInteger(value);

/** 許可したキーだけを読む。承認の記録が無いのに額がある・人物・未知のキーがあれば読み込みを拒否する。 */
export function parsePublicRanking(text: string): PublicRanking {
  if (text.length > RANKING_TEXT_LIMIT) throw new Error('ランキングのデータが大きすぎます。');
  const value = JSON.parse(text) as PublicRanking;
  if (!onlyKeys(value, ['schema', 'generatedFrom', 'approval', 'laws', 'others', 'counts']) || value.schema !== 'public-ranking/v3') throw new Error('ランキングの形式が不正です。');
  if (!onlyKeys(value.generatedFrom, ['rules', 'inputs', 'methodSpecVersion', 'codeHashes', 'parameters']) || !Array.isArray(value.generatedFrom.rules) || !value.generatedFrom.rules.every(rule => prose(rule, 80)) || !Object.values(value.generatedFrom.inputs ?? {}).every(hash => typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash))) throw new Error('生成元の記録が不正です。');
  if (!validGenerationMetadata({ methodSpecVersion: value.generatedFrom.methodSpecVersion, codeHashes: value.generatedFrom.codeHashes }, ['scripts/build_public_ranking.py', 'scripts/generation_provenance.py', 'scripts/path_guard.py'])) throw new Error('計算方法・生成ソースの版が不正です。');
  const lawIds = (ids: unknown) => Array.isArray(ids) && ids.every(id => typeof id === 'string' && /^(閣法|衆法|参法)-[0-9]+-[0-9]+$/.test(id));
  if (!onlyKeys(value.generatedFrom.parameters, ['heldOut', 'noAmount']) || !lawIds(value.generatedFrom.parameters.heldOut) || !lawIds(value.generatedFrom.parameters.noAmount)) throw new Error('出典の保留条件が不正です。');
  const { approval } = value;
  if (!onlyKeys(approval, ['approvedAt', 'scope', 'note'])) throw new Error('承認の記録が不正です。');
  const recorded = approval.scope === 'all-laws';
  if (recorded ? !(typeof approval.approvedAt === 'string' && dateText(approval.approvedAt) && prose(approval.note, 300)) : (approval.scope !== null || approval.approvedAt !== null || approval.note !== null)) throw new Error('承認日が不正です。');
  if (!Array.isArray(value.laws) || !Array.isArray(value.others)) throw new Error('ランキングの項目が不足しています。');
  if (!recorded && value.laws.length) throw new Error('承認されていない法律の額は表示しません。');
  const seen = new Set<string>();
  for (const law of value.laws) {
    // 検証で参考に降格した法律だけが、理由と根拠（demotedReason・demotedBasis）を2つそろえて持つ。額は残し、順位・配分には使わない。
    const { demotedReason, demotedBasis, ...lawBody } = law as PublicRankingLaw & { demotedReason?: unknown; demotedBasis?: unknown };
    if (!onlyKeys(lawBody, ['id', 'title', 'side', 'certainty', 'notes', 'field', 'indicator', 'stage', 'enforcedOn', 'amountMedianYen', 'amountLowYen', 'amountHighYen', 'lowerBound', 'window', 'comparisonCountries', 'benefitStatus', 'group', 'sources'])) throw new Error('法律の項目が不正です。');
    if ((demotedReason !== undefined || demotedBasis !== undefined) && (!prose(demotedReason, 500) || !prose(demotedBasis, 800) || law.certainty !== '参考')) throw new Error('降格の理由・根拠が不正です。');
    if (!LAW_ID.test(law.id) || seen.has(law.id)) throw new Error('法律の id が不正です。');
    seen.add(law.id);
    if (!['loss', 'benefit'].includes(law.side) || !CERTAINTIES.includes(law.certainty) || !Array.isArray(law.notes) || !law.notes.every(note => prose(note, 300)) || ![law.title, law.field, law.indicator, law.stage, law.window, law.benefitStatus, law.group].every(item => prose(item, 500)) || !dateText(law.enforcedOn) || typeof law.lowerBound !== 'boolean') throw new Error('法律の項目が不正です。');
    // 四分位の幅は0をまたぐことがある（中央値は側の向きに正。幅はそのまま見せる）。
    const edges = signedYen;
    if (!yen(law.amountMedianYen) || !edges(law.amountLowYen) || !edges(law.amountHighYen) || law.amountLowYen > law.amountMedianYen || law.amountMedianYen > law.amountHighYen) throw new Error('額の幅が不正です。');
    // コロナ対応の費用便益（covid-benefit-v1）は支出の規模から計算するので比較国を持たず、官公庁（go.jp）の支出・係数の資料も出典に持つ。
    const noComparison = isCovidBenefitGroup(law.group);
    if (!Array.isArray(law.comparisonCountries) || (noComparison ? law.comparisonCountries.length : !law.comparisonCountries.length) || !law.comparisonCountries.every(code => /^[A-Z]{3}$/.test(code))) throw new Error('比較国が不正です。');
    if (!Array.isArray(law.sources) || !law.sources.length) throw new Error('一次資料がありません。');
    for (const source of law.sources) {
      const url = new URL(source);
      if (url.protocol !== 'https:' || !(SOURCE_HOSTS.has(url.hostname) || (noComparison && url.hostname.endsWith('.go.jp'))) || url.username || url.password) throw new Error('一次資料の URL が不正です。');
    }
  }
  for (const item of value.others) {
    if (!onlyKeys(item, ['id', 'title', 'outcome', 'reason']) || !LAW_ID.test(item.id) || seen.has(item.id) || !prose(item.outcome, 80) || !prose(item.title, 500) || !prose(item.reason, 500)) throw new Error('結果の項目が不正です。');
    seen.add(item.id);
  }
  if (!onlyKeys(value.counts, COUNT_KEYS) || !COUNT_KEYS.every(key => Number.isSafeInteger(value.counts[key as keyof PublicRanking['counts']]) && value.counts[key as keyof PublicRanking['counts']] >= 0)) throw new Error('件数が不正です。');
  const { counts } = value;
  if (counts.published !== value.laws.length || counts.others !== value.others.length || counts.confirmed + counts.reference !== counts.published || counts.published + counts.others !== counts.enacted) throw new Error('公開件数が一致しません。');
  return value;
}


export function parsePublicMembers(text: string): PublicMembers {
  const data = JSON.parse(text) as PublicMembers;
  if (data.schema !== 'public-members/v3' || !Array.isArray(data.members) || !Array.isArray(data.laws)) throw new Error('議員データの形式が違います');
  if (!validGenerationMetadata(data.generatedFrom, ['app/src/members-build.ts', 'scripts/build_public_members.mjs', 'scripts/generation_provenance.mjs', 'scripts/path_guard.mjs', 'app/package-lock.json'])) throw new Error('議員データの生成元が不正です');
  return data;
}

export function parsePublicMembersReference(text: string): PublicMembersReference {
  const data = JSON.parse(text) as PublicMembersReference;
  if (data.schema !== 'public-members-reference/v2' || !Array.isArray(data.members)) throw new Error('参考一覧の形式が違います');
  if (!validGenerationMetadata(data.generatedFrom, ['app/src/members-reference.ts', 'scripts/build_reference_members.mjs', 'scripts/generation_provenance.mjs', 'scripts/path_guard.mjs', 'app/package-lock.json'])) throw new Error('参考一覧の生成元が不正です');
  return data;
}
