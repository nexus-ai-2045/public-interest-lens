export type PolicyContext = { policyId: string; formalTitle: string; summary: string; officialUrl: string; originalSha256: string; sourceExcerpt?: string; summaryStatus?: 'unverified_explanation' };
export type PolicyCatalog = { schemaVersion: 'policy-context/v1'; releaseId: string; policies: PolicyContext[] };

export function parsePolicyCatalog(text: string, expectedRelease: string): PolicyCatalog {
  if (new TextEncoder().encode(text).byteLength > 1_000_000) throw new Error('議案情報が大きすぎます。');
  const value = JSON.parse(text) as PolicyCatalog;
  if (value?.schemaVersion !== 'policy-context/v1' || !/^[a-f0-9]{64}$/.test(value.releaseId) || value.releaseId !== expectedRelease || !Array.isArray(value.policies)) throw new Error('議案情報の参照版が一致しません。');
  const ids = new Set<string>();
  for (const policy of value.policies) {
    if (!policy || typeof policy.policyId !== 'string' || !policy.policyId || ids.has(policy.policyId) || typeof policy.formalTitle !== 'string' || !policy.formalTitle.trim() || policy.formalTitle.length > 1000 || typeof policy.summary !== 'string' || policy.summary.length > 4000 || !/^[a-f0-9]{64}$/.test(policy.originalSha256)) throw new Error('議案情報が不正です。');
    const url = new URL(policy.officialUrl);
    if (url.protocol !== 'https:' || url.hostname !== 'www.sangiin.go.jp' || url.username || url.password || url.port) throw new Error('公式議案URLが不正です。');
    ids.add(policy.policyId);
    if ((policy.sourceExcerpt !== undefined && (typeof policy.sourceExcerpt !== 'string' || policy.sourceExcerpt.length > 10000)) || (policy.summaryStatus !== undefined && policy.summaryStatus !== 'unverified_explanation')) throw new Error('議案説明の形式が不正です。');
  }
  return { schemaVersion: value.schemaVersion, releaseId: value.releaseId, policies: value.policies.map(({ policyId, formalTitle, summary, officialUrl, originalSha256, sourceExcerpt }) => ({ policyId, formalTitle, summary, officialUrl, originalSha256, ...(sourceExcerpt !== undefined ? { sourceExcerpt } : {}), summaryStatus: 'unverified_explanation' })) };
}
