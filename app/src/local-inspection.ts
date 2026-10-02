export type LocalInspection = {
  readableEvidence?: ReadableEvidence;
  policySelection?: PolicySelection;
  asOf: string; scope: string; assessedPeople: number; sourceRecords: number | null;
  sourceStatus: 'capped' | 'query_exhausted' | 'pages_captured';
  held: {
    id: string; reason: string; sourceSpeechId: string | null; title: string | null;
    submittedAt: string | null; sourceUrl: string | null; voteUrl: string | null;
    observedAt: string | null; sha256: string | null;
  }[];
};

export type SelectedPolicy = { id: string; billId?: string; title: string; submittedAt: string; sourceUrl: string };
export type PolicySelection = { criterionVersion: 'research-digital-registered-pilot-v1';
  inventoryCompleteness: 'registered_candidates_only'; asOf: string; scope: string; policies: SelectedPolicy[] };

type SourceRecord = { id: string; date: string; text: string; sourceUrl: string; observedAt: string; sha256: string; locator: string };
export type ReadableEvidence = {
  verificationState: 'unverified'; selectionScope: string;
  speeches: (SourceRecord & { speakerName: string })[];
  votes: (SourceRecord & { nameText: string; position: 'for' | 'against' | 'not_voted' | 'unknown'; title: string; policyId: string })[];
  counts: { savedRecords: number; readableSpeechBodies: number; sourceVoteRows: number; confirmedActionEvidence: 0 };
};

const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
function officialUrl(value: unknown, vote: boolean): string | null {
  if (value == null || value === '') return null;
  if (typeof value !== 'string') throw new Error('公式資料URLが不正です');
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('公式資料URLが不正です'); }
  const authority = /^https:\/\/([^/\?#]+)/i.exec(value)?.[1];
  if (url.protocol !== 'https:' || !authority || authority.includes(':') || url.username || url.password || url.port || !(url.hostname === 'www.sangiin.go.jp' || (!vote && url.hostname === 'kokkai.ndl.go.jp'))) throw new Error('公式資料URLの接続先が不正です');
  return url.toString();
}
function validObservedAt(value: string): boolean {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  return Boolean(match && validDate(match[1]) && Number(match[2]) <= 23 && Number(match[3]) <= 59 && Number(match[4]) <= 59 && (!match[6] || (Number(match[6]) <= 23 && Number(match[7]) <= 59)) && !Number.isNaN(Date.parse(value)));
}

function boundedString(value: unknown, limit: number, label: string): string {
  if (typeof value !== 'string' || !value.trim() || value.length > limit) throw new Error(`${label}が不正です`);
  return value;
}
function parsePolicySelection(value: unknown, asOf: string): PolicySelection {
  if (!object(value) || value.criterionVersion !== 'research-digital-registered-pilot-v1'
      || value.inventoryCompleteness !== 'registered_candidates_only' || value.asOf !== asOf
      || !Array.isArray(value.policies) || value.policies.length > 3) throw new Error('政策選定の基準・期間・件数が不正です');
  const seen = new Set<string>();
  const sourceIds = new Set<string>();
  const policies = value.policies.map(entry => {
    if (!object(entry)) throw new Error('選定政策の形式が不正です');
    const id = boundedString(entry.id, 200, '選定政策ID');
    if (seen.has(id)) throw new Error('選定政策IDが重複しています');
    seen.add(id);
    const billId = entry.billId == null ? id : boundedString(entry.billId, 200, '提供元議案ID');
    if (sourceIds.has(billId)) throw new Error('提供元の議案IDが重複しています');
    sourceIds.add(billId);
    if (typeof entry.submittedAt !== 'string' || !validDate(entry.submittedAt)
        || entry.submittedAt > asOf) throw new Error('選定政策の日付が不正です');
    const sourceUrl = officialUrl(entry.sourceUrl, true);
    if (!sourceUrl) throw new Error('選定政策の公式資料URLが必要です');
    return { id, billId, title: boundedString(entry.title, 1000, '選定政策名'), submittedAt: entry.submittedAt, sourceUrl };
  });
  return { criterionVersion: 'research-digital-registered-pilot-v1', inventoryCompleteness: 'registered_candidates_only',
    asOf, scope: boundedString(value.scope, 1000, '政策選定範囲'), policies };
}
function parseReadableEvidence(value: unknown): ReadableEvidence {
  if (!object(value) || value.verificationState !== 'unverified' || !Array.isArray(value.speeches) || !Array.isArray(value.votes) || !object(value.counts)) throw new Error('読める資料の形式または未検証状態が不正です');
  if (value.speeches.length > 1000 || value.votes.length > 1000) throw new Error('発言と投票行はそれぞれ1000件以下にしてください');
  const ids = new Set<string>();
  const source = (entry: unknown, vote: boolean): SourceRecord => {
    if (!object(entry)) throw new Error('資料行が不正です');
    const id = boundedString(entry.id, 200, '資料ID');
    if (ids.has(id)) throw new Error('資料IDが重複しています');
    ids.add(id);
    if (typeof entry.date !== 'string' || !validDate(entry.date) || typeof entry.observedAt !== 'string' || !validObservedAt(entry.observedAt) || typeof entry.sha256 !== 'string' || !/^[a-fA-F0-9]{64}$/.test(entry.sha256)) throw new Error('資料の日付・取得日時・ハッシュが不正です');
    const sourceUrl = officialUrl(entry.sourceUrl, vote);
    if (!sourceUrl) throw new Error('原資料URLが必要です');
    return { id, date: entry.date, text: boundedString(entry.text, 100_000, '本文'), sourceUrl, observedAt: entry.observedAt, sha256: entry.sha256, locator: boundedString(entry.locator, 1000, '引用箇所') };
  };
  const speeches = value.speeches.map(entry => ({ ...source(entry, false), speakerName: boundedString(entry.speakerName, 300, '記載名') }));
  const votes = value.votes.map(entry => {
    const common = source(entry, true);
    if (!['for', 'against', 'not_voted', 'unknown'].includes(entry.position)) throw new Error('投票区分が不正です');
    return { ...common, nameText: boundedString(entry.nameText, 300, '記載名'), position: entry.position as ReadableEvidence['votes'][number]['position'], title: boundedString(entry.title, 1000, '議案名'), policyId: boundedString(entry.policyId, 200, '政策ID') };
  });
  const counts = value.counts;
  const representedOriginals = new Set([...speeches, ...votes].map(row => row.sha256.toLowerCase())).size;
  if (!['savedRecords', 'readableSpeechBodies', 'sourceVoteRows', 'confirmedActionEvidence'].every(key => Number.isInteger(counts[key]) && (counts[key] as number) >= 0) || counts.readableSpeechBodies !== speeches.length || counts.sourceVoteRows !== votes.length || counts.confirmedActionEvidence !== 0 || (counts.savedRecords as number) < representedOriginals) throw new Error('読める資料の件数が一致しません');
  return { verificationState: 'unverified', selectionScope: boundedString(value.selectionScope, 1000, '選択範囲'), speeches, votes, counts: { savedRecords: counts.savedRecords as number, readableSpeechBodies: speeches.length, sourceVoteRows: votes.length, confirmedActionEvidence: 0 } };
}

/** 送信や評価をせず、表示に必要な公式資料メタデータだけを取り出す。 */
export function parseLocalInspection(text: string): LocalInspection {
  if (text.length > 5_000_000 || new TextEncoder().encode(text).byteLength > 5_000_000) throw new Error('5MB以下のJSONを選んでください');
  const record: unknown = JSON.parse(text);
  if (!object(record)) throw new Error('JSONの形式が不正です');
  const coverage = record.coverage;
  if (record.schemaVersion !== 'ranking-dataset/v1' || record.fictional !== false || !object(coverage)) throw new Error('実データ用 ranking-dataset/v1 ではありません');
  if (!['people', 'policies', 'involvements', 'evidence'].every(key => Array.isArray(record[key]))) throw new Error('必要な配列がありません');
  if (typeof record.asOf !== 'string' || !validDate(record.asOf) || typeof coverage.scope !== 'string') throw new Error('基準日または収録範囲が不正です');
  if (!Number.isInteger(coverage.assessedPeople) || (coverage.assessedPeople as number) < 0 || !['capped', 'query_exhausted', 'pages_captured'].includes(coverage.sourceStatus as string)) throw new Error('取得・評価状態が不正です');
  if (coverage.sourceRecords != null && (!Number.isInteger(coverage.sourceRecords) || (coverage.sourceRecords as number) < 0)) throw new Error('取得件数が不正です');
  if (record.held !== undefined && !Array.isArray(record.held)) throw new Error('保留情報が不正です');
  const held = ((record.held as unknown[] | undefined) ?? []).map(entry => {
    if (!object(entry) || typeof entry.id !== 'string' || typeof entry.reason !== 'string' || !entry.reason.trim()) throw new Error('保留理由が不正です');
    const submittedAt = entry.submittedAt == null ? null : entry.submittedAt;
    if (submittedAt !== null && (typeof submittedAt !== 'string' || !validDate(submittedAt))) throw new Error('議案提出日が不正です');
    const observedAt = entry.observedAt == null ? null : entry.observedAt;
    if (observedAt !== null && (typeof observedAt !== 'string' || !validObservedAt(observedAt))) throw new Error('資料取得日時が不正です');
    const sha256 = entry.sha256 == null ? null : entry.sha256;
    if (sha256 !== null && (typeof sha256 !== 'string' || !/^[a-fA-F0-9]{64}$/.test(sha256))) throw new Error('資料ハッシュが不正です');
    return {
      id: entry.id.slice(0, 120), reason: entry.reason.slice(0, 500),
      sourceSpeechId: typeof entry.sourceSpeechId === 'string' ? entry.sourceSpeechId.slice(0, 120) : null,
      title: typeof entry.title === 'string' && entry.title.trim() ? entry.title.slice(0, 300) : null,
      submittedAt, sourceUrl: officialUrl(entry.sourceUrl, false), voteUrl: officialUrl(entry.voteUrl, true), observedAt, sha256,
    };
  });
  const readableEvidence = record.readableEvidence === undefined ? undefined : parseReadableEvidence(record.readableEvidence);
  const policySelection = record.policySelection === undefined ? undefined : parsePolicySelection(record.policySelection, record.asOf);
  if (policySelection && readableEvidence) {
    const selected = new Set(policySelection.policies.map(policy => policy.billId ?? policy.id));
    if (readableEvidence.votes.some(vote => !selected.has(vote.policyId))) throw new Error('選定政策にない投票行があります');
  }
  return { asOf: record.asOf, scope: coverage.scope.slice(0, 300), assessedPeople: coverage.assessedPeople as number, sourceRecords: coverage.sourceRecords as number | null ?? null, sourceStatus: coverage.sourceStatus as LocalInspection['sourceStatus'], held, ...(readableEvidence ? { readableEvidence } : {}), ...(policySelection ? { policySelection } : {}) };
}
