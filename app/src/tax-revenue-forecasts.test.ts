import { expect, test } from 'vitest';
// @ts-expect-error Nodeのテスト実行時に利用する。
import { readFileSync } from 'node:fs';
import { buildMembers, taxRevenueForecastsOf } from './members-build';
import { parseCsv } from './impact-batch';

const csv = readFileSync(new URL('../../data/acquired/tax-revenue-estimates/estimates.csv', import.meta.url), 'utf8');

test('政府予測39行の全10列を欠測とゼロを区別して保持する', () => {
  const raw = parseCsv(csv), forecasts = taxRevenueForecastsOf(csv);
  expect(forecasts).toHaveLength(39);
  expect(forecasts.map(f => ({
    '年度': String(f.fiscalYear), '税目': f.taxCategory,
    '平年度_億円': f.fullYearOku === null ? '' : String(f.fullYearOku),
    '初年度_億円': f.firstYearOku === null ? '' : String(f.firstYearOku),
    '決め方': f.method, '消費税の改正を含む': f.includesConsumptionChange ? '1' : '',
    '改正事項': f.items, '出典URL': f.sourceUrl, '外部資料ID': f.materialId, '取得日時': f.observedAt,
  }))).toEqual(raw);
  const header = '年度,税目,平年度_億円,初年度_億円,決め方,消費税の改正を含む,改正事項,出典URL,外部資料ID,取得日時\n';
  expect(taxRevenueForecastsOf(header + '2024,個人所得課税,0,,,,,,,\n')[0]).toMatchObject({ fullYearOku: 0, firstYearOku: null });
  expect(() => taxRevenueForecastsOf(csv + csv.split('\n')[1] + '\n')).toThrow(/重複/);
});

test('年度予測を追加しても法律・人物の額と税率帳簿は変わらない', () => {
  const base = { involvements: '', publish: '', loss: '', enacted: '', votes: '' };
  const before = buildMembers(base), after = buildMembers({ ...base, taxRevenueForecasts: csv });
  const { taxRevenueForecasts, ...rest } = after;
  expect(rest).toEqual(before);
  expect(taxRevenueForecasts?.find(f => f.fiscalYear === 2018 && f.taxCategory === '消費課税')).toBeDefined();
  expect(taxRevenueForecasts?.find(f => f.fiscalYear === 2024 && f.taxCategory === '個人所得課税')).toBeDefined();
  for (const forecast of taxRevenueForecasts!) {
    expect(forecast).not.toHaveProperty('lawId');
    expect(forecast).not.toHaveProperty('amount');
    expect(forecast).not.toHaveProperty('total');
  }
});
