import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReadableEvidencePanel } from './ReadableEvidencePanel';
import type { ReadableEvidence } from './local-inspection';

const data: ReadableEvidence = {
  verificationState: 'unverified', selectionScope: '保存済みの有限範囲',
  speeches: [{ id: 'speech-1', speakerName: '試験の記載名', date: '2026-07-10',
    text: '政策への対応を確定していない試験本文です。', sourceUrl: 'https://kokkai.ndl.go.jp/api/meeting',
    observedAt: '2026-09-30T00:00:00Z', sha256: 'a'.repeat(64), locator: 'speechID=speech-1' }],
  votes: [{ id: 'vote-1', nameText: '試験の記載名', date: '2026-07-10', position: 'not_voted',
    title: '試験の政策甲', policyId: 'policy-a', text: '試験の投票なし記録です。',
    sourceUrl: 'https://www.sangiin.go.jp/japanese/touhyoulist/', observedAt: '2026-09-30T00:00:00Z',
    sha256: 'b'.repeat(64), locator: 'HTML line=1' }],
  counts: { savedRecords: 2, readableSpeechBodies: 1, sourceVoteRows: 1, confirmedActionEvidence: 0 },
};
const policies = [
  { id: 'policy-a', title: '試験の政策甲', sourceUrl: 'https://www.sangiin.go.jp/japanese/joho1/kousei/gian/a.htm' },
  { id: 'policy-b', title: '試験の政策乙', sourceUrl: 'https://www.sangiin.go.jp/japanese/joho1/kousei/gian/b.htm' },
];

describe('実資料の政策別収録範囲', () => {
  it('選定政策の投票行の有無を示し、欠測を反対や0点へ変換しない', () => {
    const props = { data, policies };
    const html = renderToStaticMarkup(<ReadableEvidencePanel {...props} />);
    expect(html).toContain('選定政策ごとの収録状況');
    expect(html).toContain('試験の政策乙');
    expect(html).toContain('このファイルには投票行がありません');
    expect(html).toContain('投票行 1件・未検証');
    expect(html).not.toContain('反対 0');
    expect(html).not.toContain('評価点');
  });
  it('可読発言を選定政策への関連発言として自動認定しない', () => {
    const props = { data, policies };
    const html = renderToStaticMarkup(<ReadableEvidencePanel {...props} />);
    expect(html).toContain('発言と選定政策の対応は未確認です');
    expect(html).toContain('確認済み行動証拠 0件');
  });
});
