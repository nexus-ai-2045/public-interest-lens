import { describe, expect, it } from 'vitest';
import { parseLocalInspection } from './local-inspection';

const fixture = () => ({ schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24', coverage: { scope: '公式資料', assessedPeople: 0, sourceRecords: 1, sourceStatus: 'pages_captured' }, people: [], policies: [], involvements: [], evidence: [], held: [{ id: 'held', reason: '評価保留', title: '公式議案', submittedAt: '2024-02-29', sourceUrl: 'https://www.sangiin.go.jp/example', voteUrl: 'https://www.sangiin.go.jp/vote', recordPath: 'private/path' }] });
const parse = (value: unknown) => parseLocalInspection(JSON.stringify(value));

describe('ローカル取得資料の安全な表示', () => {
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
