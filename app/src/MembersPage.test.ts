import { describe, expect, it } from 'vitest';
import { MEMBER_RANKING_HIDDEN } from './MembersPage';
import { buildExposureRanking, toPublicExposureRanking, type ExposureGroup, type Involvement } from './exposure-ranking';
import { panelExposureRanking } from './public-distribution';

const group = (id: string, median: number): ExposureGroup => ({ kind: 'group-diff', id, group: id, window: '2010年', diff: { low: median / 2, median, high: median * 2 }, benchmark: 'x', lawCount: 9 });
const params = { roleRatio: { proposer: 0.4, yes: 0.2, no: 0.2, cabinet: 0.2 }, minLaws: 2, topThreeShareCap: 1 };
const inv = (actorId: string, lawId: string): Involvement => ({ actorKind: 'person', actorId, groupId: 'g', lawId, role: 'proposer', weight: 1 });

describe('議員ページ', () => {
  it('表示を解くのは設計決定0008 のねくの確認の後（それまで隠す）', () => {
    expect(MEMBER_RANKING_HIDDEN).toBe(true);
  });

  it('公開用の曝露ランキングを画面の入力に戻す：階層に入った人の額は残し、伏せた額は画面が出さない所だけ0で埋める', () => {
    const ranking = buildExposureRanking([group('g', 100)], [inv('甲', 'L1'), inv('甲', 'L2'), inv('乙', 'L1'), inv('丙', 'L3')], params);
    const pub = toPublicExposureRanking(ranking, params.minLaws);
    const panel = panelExposureRanking(pub);
    const ranked = ranking.people.find(p => p.actorId === '甲')!;
    expect(ranked.tier).not.toBeNull();
    expect(panel.people.find(p => p.actorId === '甲')!.exposureYen).toEqual(ranked.exposureYen);
    const hidden = panel.people.find(p => p.actorId === '乙')!;
    expect(hidden.tier).toBeNull();
    expect(hidden.exposureYen).toEqual({ low: 0, median: 0, high: 0 });
    expect(panel.totals).toEqual(ranking.totals);
  });

  it('合計まで伏せた公開用データ（額を出さない行が1つだけ）は画面に出さない', () => {
    const ranking = buildExposureRanking([group('g', 100)], [inv('甲', 'L1'), inv('甲', 'L2'), inv('乙', 'L1')], params);
    const pub = toPublicExposureRanking(ranking, params.minLaws);
    expect(pub.totals.expected).toBeNull();
    expect(() => panelExposureRanking(pub)).toThrow();
  });
});
