import { describe, expect, it } from 'vitest';
import { judgeImpact, type ImpactPoint, type ImpactSeries } from './impact-rule';
import { FINANCIAL_REVIVAL_DRAFT } from './case-evaluation';

// 金融再生以外は人工の系列です。実在の統計ではありません。
const years = (gaps: number[], from = 1995): ImpactPoint[] => gaps.map((g, i) => ({ asOf: `${from + i}-03-31`, treated: 10 + g, control: 10 }));
const series = (gaps: number[], change: Partial<ImpactSeries> = {}): ImpactSeries =>
  ({ definition: '人工', start: '1999-10-01', better: 'lower', target: years(gaps), economy: null, sectorGdpShare: null, ...change });
// 開始前1995〜1999年は差がほぼ0、開始後2001年以降に差が−3へ開く。
const clear = [0, 0.1, -0.1, 0.05, 0, -0.5, -3, -3, -3.1, -3];

describe('影響段階の判定ルール impact-rule-v1', () => {
  it('金融再生の実測（平成12〜19年3月期）は、開始前のばらつきが大きく保留になる', () => {
    const judged = judgeImpact(FINANCIAL_REVIVAL_DRAFT.assessments[0].series!);
    expect(judged).toMatchObject({ stage: null, direction: 'benefit', preYears: 3, effect: -1.575, spread: 1.2 });
    expect(judged.reason).toContain('保留');
  });

  it('開始前が3年に足りなければ、計算せずに保留', () => {
    expect(judgeImpact(series([0, 0, -3, -3, -3, -3], { start: '1996-10-01' }))).toMatchObject({ stage: null, effect: null, preYears: 2 });
  });

  it('狙った指標だけで差が続けば段階1、経済全体の指標も同じ向きなら段階2、規模と傾き除去も満たせば段階3', () => {
    expect(judgeImpact(series(clear))).toMatchObject({ stage: 1, direction: 'benefit' });
    const economy = { definition: '人工', better: 'higher' as const, points: years(clear.map(g => -g)) };
    expect(judgeImpact(series(clear, { economy }))).toMatchObject({ stage: 2 });
    expect(judgeImpact(series(clear, { economy, sectorGdpShare: 0.05 }))).toMatchObject({ stage: 3 });
  });

  it('経済全体の指標が逆向きなら段階1に留まる', () => {
    const economy = { definition: '人工', better: 'higher' as const, points: years(clear) };
    expect(judgeImpact(series(clear, { economy, sectorGdpShare: 0.05 }))).toMatchObject({ stage: 1 });
  });

  it('開始前から同じ向きに差が開いていた分は、段階3の傾き除去で落ちる', () => {
    const trending = [2, 1, 0, -1, -2, -3, -4, -5, -6, -7];
    const economy = { definition: '人工', better: 'higher' as const, points: years(trending.map(g => -g)) };
    expect(judgeImpact(series(trending, { economy, sectorGdpShare: 0.05 }))).toMatchObject({ stage: 2 });
  });

  it('低いほど良い指標が上がれば悪影響の向き、重複した期末は保留', () => {
    expect(judgeImpact(series(clear.map(g => -g)))).toMatchObject({ stage: 1, direction: 'harm' });
    const dup = series(clear); dup.target[1] = { ...dup.target[0] };
    expect(judgeImpact(dup)).toMatchObject({ stage: null, reason: '同じ期末の観測が重複しています' });
  });
});
