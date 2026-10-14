import { describe, expect, it } from 'vitest';
import { judgeAcrossCountries, judgeImpact, type ImpactPoint, type ImpactSeries } from './impact-rule';
import { FINANCIAL_REVIVAL_DRAFT } from './case-evaluation';

// 金融再生以外は人工の系列です。実在の統計ではありません。
const years = (gaps: number[], from = 1995): ImpactPoint[] => gaps.map((g, i) => ({ asOf: `${from + i}-03-31`, treated: 10 + g, control: 10 }));
const series = (gaps: number[], change: Partial<ImpactSeries> = {}): ImpactSeries =>
  ({ definition: '人工', start: '1999-10-01', better: 'lower', target: years(gaps), economy: null, sectorGdpShare: null, ...change });
// 開始前1995〜1999年は差がほぼ0、開始後2001年以降に差が−3へ開く。
const clear = [0, 0.1, -0.1, 0.05, 0, -0.5, -3, -3, -3.1, -3];

describe('影響段階の判定ルール impact-rule-v1', () => {
  it('金融再生の実測（平成10〜19年3月期、開始前5年）は段階1になる', () => {
    const judged = judgeImpact(FINANCIAL_REVIVAL_DRAFT.assessments[0].series!);
    expect(judged).toMatchObject({ stage: 1, direction: 'benefit', preYears: 5, effect: -2.6565, spread: 1.280519 });
    expect(judged.reason).toContain('経済全体の指標で同じ向きの差が確認できないため段階1');
  });

  it('金融再生でも開始前を3年に削ると、ばらつきの2倍を超えず保留になる', () => {
    const s = FINANCIAL_REVIVAL_DRAFT.assessments[0].series!;
    expect(judgeImpact({ ...s, target: s.target.filter(p => p.asOf >= '2000-03-31') })).toMatchObject({ stage: null, preYears: 3 });
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

describe('国際比較の判定 judgeAcrossCountries', () => {
  // 人工の系列。日本は開始後に3下がり、比較国はほぼ横ばい。
  const yearsOf = (vals: number[]) => vals.map((value, i) => ({ asOf: `${1995 + i}-12-31`, value }));
  const japan = yearsOf([100, 100.1, 99.9, 100, 100.05, 99.5, 97, 97, 96.9, 97]);
  const flat = (country: string, wobble = 0) => ({ country, points: yearsOf([100, 100 + wobble, 100, 100 - wobble, 100, 100, 100, 100, 100, 100]) });
  const cross = (controls: { country: string; points: { asOf: string; value: number }[] }[]) =>
    judgeAcrossCountries({ definition: '人工', start: '1999-10-01', better: 'lower', sectorGdpShare: null, treated: japan, controls });

  it('3か国すべてで同じ向きなら段階1', () => {
    expect(cross([flat('A'), flat('B', 0.05), flat('C', 0.1)])).toMatchObject({ stage: 1, direction: 'benefit' });
  });

  it('比較国が2か国では保留', () => {
    expect(cross([flat('A'), flat('B')])).toMatchObject({ stage: null });
  });

  it('向きが国ごとに割れたら保留し、多数が逆向きならその向きになる', () => {
    const falling = (country: string) => ({ country, points: yearsOf([100, 100.1, 99.9, 100, 100.05, 99.5, 96, 96, 95.9, 96]) });
    expect(cross([flat('A'), falling('B'), flat('C', 3)])).toMatchObject({ stage: null });
    expect(cross([flat('A'), falling('B'), falling('C')])).toMatchObject({ stage: 1, direction: 'harm' });
  });

  it('開始前から差が同じ向きに開いていた国は数えない', () => {
    const rising = (country: string) => ({ country, points: yearsOf([97, 98, 99, 100.5, 101.5, 101, 101, 101, 101, 101]) });
    const judged = cross([rising('A'), rising('B'), flat('C')]);
    expect(judged.countries.filter(c => c.country !== 'C').every(c => !c.passes)).toBe(true);
    expect(judged.stage).toBeNull();
  });
});
