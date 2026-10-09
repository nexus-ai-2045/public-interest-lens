import { describe, it, expect } from 'vitest';
import { selectEconomicPeriod, type EconomicSeries } from './economy-view';
const series: EconomicSeries = { id: 'real_gdp', label: '実質GDP', unit: '円', basis: '', sourceUrl: 'https://api.worldbank.org/', points: Array.from({ length: 46 }, (_, i) => ({ year: 1980 + i, value: i === 42 ? null : 100 + i })) };
describe('結果年の期間選択', () => {
  it('末尾の欠測年と行が無い年も期間へ残します', () => {
    const missing = { ...series, points: [{ year: 2021, value: 90 }, { year: 2023, value: 100 }, { year: 2024, value: null }] };
    expect(selectEconomicPeriod(missing, '4')).toEqual([{ year: 2021, value: 90 }, { year: 2022, value: null }, { year: 2023, value: 100 }, { year: 2024, value: null }]);
  });
  it('40年・30年・4年を同じ系列から選び、欠落を保ちます', () => {
    expect(selectEconomicPeriod(series, '40')).toHaveLength(40);
    expect(selectEconomicPeriod(series, '30')[0].year).toBe(1996);
    expect(selectEconomicPeriod(series, '4')[0]).toEqual({ year: 2022, value: null });
  });
  it('任意期間と未来・逆転の拒否を扱います', () => {
    expect(selectEconomicPeriod(series, 'custom', 2000, 2010)).toHaveLength(11);
    expect(() => selectEconomicPeriod(series, 'custom', 2025, 2000)).toThrow();
    expect(() => selectEconomicPeriod(series, 'custom', 2000, 2026)).toThrow();
  });
});
