import { describe, expect, it } from 'vitest';
import { allocateLoss, estimateLoss, type LossInput } from './loss-rule';

// すべて人工の系列です。実在の統計ではありません。
const pts = (values: number[], from = 2010) => values.map((value, i) => ({ asOf: `${from + i}-12-31`, value }));
// 比較国は毎年ほぼ2%伸び、日本は開始前は同じ伸び、開始後は横ばい。
const grow = (rate: number, n = 10) => Array.from({ length: n }, (_, i) => 100 * (1 + rate) ** i);
const jpFlat = [...grow(0.02, 5), ...Array(5).fill(100 * 1.02 ** 4)];
const input = (change: Partial<LossInput> = {}): LossInput => ({
  definition: '人工', start: '2015-01-01', judgement: { stage: 2, direction: 'harm' },
  treated: pts(jpFlat), controls: [0.018, 0.02, 0.022].map((r, i) => ({ country: `C${i}`, points: pts(grow(r)) })),
  baseNominalYen: 1e12, regulationBenefitYen: 0, ...change,
});

describe('反実仮想の損失額 loss-rule-v1', () => {
  it('比較国が伸びて日本が横ばいなら、正の損失額と四分位の幅が出る', () => {
    const r = estimateLoss(input());
    expect(r.years).toBe(5);
    expect(r.publishable).toBe(true);
    expect(r.lossYen!.median).toBeGreaterThan(0);
    expect(r.lossYen!.low).toBeLessThan(r.lossYen!.median);
    expect(r.lossYen!.high).toBeGreaterThan(r.lossYen!.median);
  });

  it('段階1以下・比較国3か国未満・開始前3年未満は保留', () => {
    expect(estimateLoss(input({ judgement: { stage: 1, direction: 'harm' } })).lossYen).toBeNull();
    expect(estimateLoss(input({ controls: input().controls.slice(0, 2) })).lossYen).toBeNull();
    expect(estimateLoss(input({ start: '2012-06-01' })).lossYen).toBeNull();
  });

  it('開始前から続く伸びの差は損失に数えない', () => {
    // 日本が開始前から比較国より毎年2%遅く、開始後もその差のままなら、損失はほぼ0で向きが立たず保留。
    const jp = grow(0.0);
    const r = estimateLoss(input({ treated: pts(jp) }));
    expect(r.lossYen).toBeNull();
  });

  it('向きが段階の判定と逆なら保留、規制の便益が未測定なら公開しない', () => {
    expect(estimateLoss(input({ judgement: { stage: 2, direction: 'benefit' } })).lossYen).toBeNull();
    const r = estimateLoss(input({ regulationBenefitYen: null }));
    expect(r.lossYen).not.toBeNull();
    expect(r.publishable).toBe(false);
  });
});

describe('個人への配分', () => {
  const loss = { low: 100, median: 200, high: 400 };
  it('行動×立場で按分し、合計は損失×帰属率を超えない。最大の行動だけ数え、資料の無い行動は数えない', () => {
    const a = allocateLoss(loss, [
      { personId: 'A', action: 'decide', position: 'minister_or_party_exec', evidenceUrl: 'https://example.go.jp/1' },
      { personId: 'A', action: 'vote', position: 'minister_or_party_exec', evidenceUrl: 'https://example.go.jp/2' },
      { personId: 'B', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/3' },
      { personId: 'C', action: 'question', position: 'other', evidenceUrl: '' },
    ]);
    expect(a.map(x => [x.personId, x.weight])).toEqual([['A', 10], ['B', 1]]);
    expect(a.reduce((s, x) => s + x.shareYen.median, 0)).toBeLessThanOrEqual(100);
    expect(a[0].shareYen.median).toBe(91);
  });
});
