import { describe, it, expect } from 'vitest';
import { parsePolicyCatalog } from './policy-context';

const releaseId = 'a'.repeat(64);
const policy = { policyId: '200-8', formalTitle: '試験法律案', summary: '試験制度を整備します。', officialUrl: 'https://www.sangiin.go.jp/japanese/test.htm', originalSha256: 'b'.repeat(64) };
const catalog = (policies = [policy]) => JSON.stringify({ schemaVersion: 'policy-context/v1', releaseId, policies });
describe('評価版に結び付いた議案情報', () => {
  it('必要な議案情報だけを表示へ渡します', () => {
    expect(parsePolicyCatalog(catalog([{ ...policy, recordPath: 'private' } as typeof policy]), releaseId).policies[0]).toEqual({ ...policy, summaryStatus: 'unverified_explanation' });
  });
  it('別版・重複・認証情報付きURLを拒否します', () => {
    expect(() => parsePolicyCatalog(catalog(), 'c'.repeat(64))).toThrow();
    expect(() => parsePolicyCatalog(catalog([policy, policy]), releaseId)).toThrow();
    expect(() => parsePolicyCatalog(catalog([{ ...policy, officialUrl: 'https://user:pass@www.sangiin.go.jp/' }]), releaseId)).toThrow();
  });
});
