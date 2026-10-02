import { describe, expect, it } from 'vitest';
import { parseLocalInspection } from './local-inspection';

const fixture = () => ({ schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24', coverage: { scope: '公式資料', assessedPeople: 0, sourceRecords: 1, sourceStatus: 'pages_captured' }, people: [], policies: [], involvements: [], evidence: [], held: [{ id: 'held', reason: '評価保留', title: '公式議案', submittedAt: '2024-02-29', sourceUrl: 'https://www.sangiin.go.jp/example', voteUrl: 'https://www.sangiin.go.jp/vote', recordPath: 'private/path' }] });
const parse = (value: unknown) => parseLocalInspection(JSON.stringify(value));

describe('ローカル取得資料の安全な表示', () => {
  it('内部の選定IDと提供元の議案IDが異なる入力でも正しい投票を対応付ける', () => {
    const policySelection = { criterionVersion: 'research-digital-registered-pilot-v1',
      inventoryCompleteness: 'registered_candidates_only', asOf: fixture().asOf,
      scope: '限定選定', policies: [{ id: 'project-policy', billId: 'bill-1', title: '試験政策',
        submittedAt: '2026-03-01', sourceUrl: 'https://www.sangiin.go.jp/example' }] };
    const result = parse({ ...fixture(), policySelection, readableEvidence: readableFixture() });
    expect(result).toHaveProperty('policySelection.policies.0.billId', 'bill-1');
  });
  it('既存JSONの選定政策を必要な表示項目だけへ投影する', () => {
    const policySelection = { criterionVersion: 'research-digital-registered-pilot-v1',
      inventoryCompleteness: 'registered_candidates_only', asOf: fixture().asOf,
      scope: '登録済み候補集合内の限定選定', policies: [{ id: 'policy-1', title: '試験政策',
        submittedAt: '2026-03-01', sourceUrl: 'https://www.sangiin.go.jp/example', recordPath: 'private/path' }] };
    const result = parse({ ...fixture(), policySelection });
    expect(result).toHaveProperty('policySelection.policies.0.id', 'policy-1');
    expect(result).not.toHaveProperty('policySelection.policies.0.recordPath');
  });
  it('選定の基準日不一致・重複・上限超過・未選定投票を拒否する', () => {
    const policySelection = { criterionVersion: 'research-digital-registered-pilot-v1',
      inventoryCompleteness: 'registered_candidates_only', asOf: fixture().asOf,
      scope: '限定選定', policies: [{ id: 'policy-1', title: '試験政策', submittedAt: '2026-03-01',
        sourceUrl: 'https://www.sangiin.go.jp/example' }] };
    for (const selection of [
      { ...policySelection, asOf: '2026-09-25' },
      { ...policySelection, policies: [policySelection.policies[0], policySelection.policies[0]] },
      { ...policySelection, policies: Array(4).fill(policySelection.policies[0]) },
      { ...policySelection, inventoryCompleteness: 'all_candidates' },
    ]) expect(() => parse({ ...fixture(), policySelection: selection })).toThrow();
    const readableEvidence = readableFixture();
    expect(() => parse({ ...fixture(), policySelection, readableEvidence: { ...readableEvidence,
      votes: [{ ...readableEvidence.votes[0], policyId: 'unselected' }] } })).toThrow();
  });
  it('読める本文と個人投票を未検証の別資料として保持する', () => {
    const readableEvidence = readableFixture();
    expect(parse({ ...fixture(), readableEvidence })).toHaveProperty('readableEvidence', readableEvidence);
  });
  it('未検証資料から自己申告の検証済み・不一致件数・重複IDを受け入れない', () => {
    const data = readableFixture();
    for (const readableEvidence of [
      { ...data, verificationState: 'verified' },
      { ...data, counts: { ...data.counts, confirmedActionEvidence: 1 } },
      { ...data, counts: { ...data.counts, readableSpeechBodies: 0 } },
      { ...data, counts: { ...data.counts, savedRecords: -1 } },
      { ...data, votes: [{ ...data.votes[0], id: data.speeches[0].id }] },
      { ...data, votes: [{ ...data.votes[0], position: 'abstain' }] },
      { ...data, speeches: Array(1001).fill(data.speeches[0]) },
    ]) expect(() => parse({ ...fixture(), readableEvidence })).toThrow();
  });
  it('本文資料にも公式URL・日付・取得日時・ハッシュ・引用箇所を要求する', () => {
    const data = readableFixture();
    for (const change of [{ sourceUrl: 'https://example.com' }, { date: '2026-02-30' }, { observedAt: '2026-10-01' }, { sha256: 'z'.repeat(64) }, { locator: '' }, { text: '' }, { text: 'a'.repeat(100001) }]) {
      expect(() => parse({ ...fixture(), readableEvidence: { ...data, speeches: [{ ...data.speeches[0], ...change }] } })).toThrow();
    }
  });
  it('一つの原本から多数の発言本文を保存でき、原本数と本文数を足し合わせない', () => {
    const data = readableFixture();
    const speeches = Array.from({ length: 397 }, (_, i) => ({ ...data.speeches[0], id: `speech-${i}` }));
    expect(parse({ ...fixture(), readableEvidence: { ...data, speeches, votes: [], counts: { savedRecords: 1, readableSpeechBodies: 397, sourceVoteRows: 0, confirmedActionEvidence: 0 } } }).readableEvidence?.counts.savedRecords).toBe(1);
    expect(() => parse({ ...fixture(), readableEvidence: { ...data, counts: { ...data.counts, savedRecords: 1 } } })).toThrow();
  });
  it('従来の有効な入力を保ち未指定の取得時刻とハッシュはnullにする', () => {
    const result = parse(fixture());
    expect(result.held[0].observedAt).toBeNull(); expect(result.held[0].sha256).toBeNull();
    expect(result.held[0]).not.toHaveProperty('recordPath');
    expect(result.sourceRecords).toBe(1);
  });
  it('国会会議録の資料URLと正しい取得日時・ハッシュを保持する', () => {
    const value = fixture();
    value.held[0].sourceUrl = 'https://kokkai.ndl.go.jp/api/speech';
    const result = parse({ ...value, held: [{ ...value.held[0], observedAt: '2026-09-24T12:30:01.123+09:00', sha256: 'a'.repeat(64) }] });
    expect(result.held[0].sourceUrl).toContain('kokkai.ndl.go.jp');
    expect(result.held[0].observedAt).toBe('2026-09-24T12:30:01.123+09:00');
    expect(result.held[0].sha256).toBe('a'.repeat(64));
  });
  it.each(['http://www.sangiin.go.jp/a', 'https://www.sangiin.go.jp.evil.example/a', 'https://u:p@www.sangiin.go.jp/a', 'https://www.sangiin.go.jp:443/a', 'javascript:alert(1)'])('不正な資料URLを拒否する: %s', sourceUrl => {
    const value = fixture(); value.held[0].sourceUrl = sourceUrl;
    expect(() => parse(value)).toThrow();
  });
  it('国会会議録URLを採決URLとして扱わない', () => {
    const value = fixture(); value.held[0].voteUrl = 'https://kokkai.ndl.go.jp/api/speech';
    expect(() => parse(value)).toThrow();
  });
  it.each(['2026-02-30', '2026-13-01', '2026-9-1'])('存在しない基準日と提出日を拒否する: %s', date => {
    expect(() => parse({ ...fixture(), asOf: date })).toThrow();
    const value = fixture(); value.held[0].submittedAt = date;
    expect(() => parse(value)).toThrow();
  });
  it.each(['2026-02-30T12:00:00Z', '2026-09-24T25:00:00Z', '2026-09-24T12:00:00', '2026-09-24', '2026-09-24T12:00:00+25:00'])('不正な取得日時を拒否する: %s', observedAt => {
    expect(() => parse({ ...fixture(), held: [{ ...fixture().held[0], observedAt }] })).toThrow();
  });
  it.each(['a'.repeat(63), 'z'.repeat(64), 123])('不正なハッシュを拒否する', sha256 => {
    expect(() => parse({ ...fixture(), held: [{ ...fixture().held[0], sha256 }] })).toThrow();
  });
  it('壊れたJSON・必須配列・件数・5MB超過を拒否する', () => {
    expect(() => parseLocalInspection('{')).toThrow();
    expect(() => parse({ ...fixture(), evidence: {} })).toThrow();
    expect(() => parse({ ...fixture(), coverage: { ...fixture().coverage, assessedPeople: -1 } })).toThrow();
    expect(() => parseLocalInspection(' '.repeat(5_000_001))).toThrow();
    expect(() => parse({ ...fixture(), ignored: 'あ'.repeat(1_700_000) })).toThrow();
  });
});

function readableFixture() {
  return { verificationState: 'unverified', selectionScope: '研究開発・デジタル化支援の限定資料', speeches: [{ id: 'speech-1', speakerName: '記載名甲', date: '2025-01-15', text: '研究開発について説明します。', sourceUrl: 'https://kokkai.ndl.go.jp/api/speech', observedAt: '2026-10-01T00:00:00Z', sha256: 'a'.repeat(64), locator: 'speechRecord[0]' }], votes: [{ id: 'vote-1', nameText: '記載名乙', date: '2025-01-15', position: 'not_voted', title: '研究開発議案', policyId: 'bill-1', text: '投票なし欄に記載', sourceUrl: 'https://www.sangiin.go.jp/vote', observedAt: '2026-10-01T00:00:00Z', sha256: 'b'.repeat(64), locator: '投票なし一覧' }], counts: { savedRecords: 2, readableSpeechBodies: 1, sourceVoteRows: 1, confirmedActionEvidence: 0 } };
}
