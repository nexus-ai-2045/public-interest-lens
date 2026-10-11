import { describe, expect, it } from 'vitest';
import { cagr, economy, periodGrowth, seriesById } from './economy';

describe('economy', () => {
  it('世界銀行の日本データで、1980〜2025年がそろっている', () => {
    expect(economy.provider).toBe('World Bank WDI');
    expect(economy.country).toBe('JPN');
    const pts = seriesById('real_gdp_per_capita').points;
    expect(pts[0].year).toBe(1980);
    expect(pts[pts.length - 1].year).toBe(2025);
  });

  it('年平均成長率を計算する', () => {
    expect(cagr([{ year: 2000, value: 100 }, { year: 2002, value: 121 }], 2000, 2002)).toBeCloseTo(10, 6);
    expect(cagr([{ year: 2000, value: 100 }], 2000, 2002)).toBeNull();
  });

  it('1980年代の伸びは2000年代以降より大きい（見出しの記述の根拠）', () => {
    const [g80, , g00, g10] = periodGrowth(seriesById('real_gdp_per_capita').points, [1980, 1990, 2000, 2010, 2020]);
    expect(g80.rate!).toBeGreaterThan(g00.rate!);
    expect(g80.rate!).toBeGreaterThan(g10.rate!);
  });
});
