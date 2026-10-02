import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RealRecordsPage } from './RealRecordsPage';

describe('実資料の入口', () => {
  it('実際の記録を開く入口と未照合・未評価を示し、架空順位へフォールバックしない', () => {
    const html = renderToStaticMarkup(<RealRecordsPage onDemo={() => {}} onEvaluation={() => {}} />);
    expect(html).toContain('実資料・未採点');
    expect(html).toContain('本人・候補者履歴は未照合、影響は未評価です');
    expect(html).toContain('閲覧用JSONを開く');
    expect(html).toContain('資料を読み込んでいます');
    expect(html).not.toContain('fiction-');
    expect(html).not.toContain('レビュー待ち');
    expect(html).not.toContain('貢献優勢');
  });
});
