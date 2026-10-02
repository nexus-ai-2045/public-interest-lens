export type LocalInspection = {
  asOf: string; scope: string; assessedPeople: number; sourceRecords: number | null;
  sourceStatus: 'capped' | 'query_exhausted' | 'pages_captured';
  held: {
    id: string; reason: string; sourceSpeechId: string | null; title: string | null;
    submittedAt: string | null; sourceUrl: string | null; voteUrl: string | null;
    observedAt: string | null; sha256: string | null;
  }[];
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
  return { asOf: record.asOf, scope: coverage.scope.slice(0, 300), assessedPeople: coverage.assessedPeople as number, sourceRecords: coverage.sourceRecords as number | null ?? null, sourceStatus: coverage.sourceStatus as LocalInspection['sourceStatus'], held };
}
