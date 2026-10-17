// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import growthCausesFile from './growth-causes.json';
import { averageGrowth, formatRate, formatUsd, growthRanking, latestRanking, levelGrowth, linearTicks, logTicks, parseGrowthCauses, parseWorldGdp, periodRange } from './world-gdp';

const committed = readFileSync(new URL('../public/distribution/world-gdp.json', import.meta.url), 'utf8');
const wb = (code: string, id: string) => `https://api.worldbank.org/v2/country/${code}/indicator/${id}?format=json`;
const sample = () => ({
  schemaVersion: 'world-gdp/v1',
  fetchedAt: '2026-10-17T00:00:00Z',
  notes: ['注記です。'],
  countries: [
    { code: 'JPN', name: '日本', provider: 'World Bank WDI', sourceUrls: { nominalUsd: wb('JPN', 'NY.GDP.MKTP.CD'), realGrowth: wb('JPN', 'NY.GDP.MKTP.KD.ZG'), perCapitaPpp: wb('JPN', 'NY.GDP.PCAP.PP.KD') }, series: { nominalUsd: [[2020, 5e12], [2021, 4.5e12]], realGrowth: [[2020, -4], [2021, 2], [2022, 1]], perCapitaPpp: [[2020, 40000], [2022, 44100]] } },
    { code: 'USA', name: 'アメリカ', provider: 'World Bank WDI', sourceUrls: { nominalUsd: wb('USA', 'NY.GDP.MKTP.CD'), realGrowth: wb('USA', 'NY.GDP.MKTP.KD.ZG') }, series: { nominalUsd: [[2020, 21e12], [2021, 23e12]], realGrowth: [[2020, -2], [2021, 6], [2022, 2]] } },
    { code: 'TWN', name: '台湾', provider: 'IMF World Economic Outlook', sourceUrls: { realGrowth: 'https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/TWN' }, series: { realGrowth: [[2021, 6.5], [2022, 2.6]] } },
  ],
});
const text = (value: unknown) => JSON.stringify(value);

describe('世界のGDPデータの検証', () => {
  it('公開配布中のファイルをそのまま読めます', () => {
    const data = parseWorldGdp(committed);
    expect(data.countries.length).toBeGreaterThanOrEqual(10);
    expect(data.countries.some(country => country.code === 'CHN')).toBe(true);
    expect(data.countries.some(country => country.code === 'JPN')).toBe(true);
  });
  it('正しい形を受け入れます', () => {
    expect(parseWorldGdp(text(sample())).countries).toHaveLength(3);
  });
  it('版の名前・未知の項目・日本の欠落を拒否します', () => {
    expect(() => parseWorldGdp(text({ ...sample(), schemaVersion: 'world-gdp/v2' }))).toThrow();
    expect(() => parseWorldGdp(text({ ...sample(), extra: 1 }))).toThrow();
    const noJapan = sample(); noJapan.countries.shift();
    expect(() => parseWorldGdp(text(noJapan))).toThrow();
    const dup = sample(); dup.countries[1].code = 'JPN';
    expect(() => parseWorldGdp(text(dup))).toThrow();
    const badDate = sample(); badDate.fetchedAt = '昨日';
    expect(() => parseWorldGdp(text(badDate))).toThrow();
  });
  it('出典は https の世界銀行か IMF だけを受け入れます', () => {
    for (const url of ['http://api.worldbank.org/v2/x', 'https://example.com/x', 'https://user:pw@api.worldbank.org/x', 'https://api.worldbank.org.example.com/x', 'javascript:alert(1)']) {
      const data = sample(); data.countries[0].sourceUrls.nominalUsd = url;
      expect(() => parseWorldGdp(text(data)), url).toThrow();
    }
    const missing = sample(); delete missing.countries[0].sourceUrls.realGrowth;
    expect(() => parseWorldGdp(text(missing))).toThrow();
    const orphan = sample(); orphan.countries[2].sourceUrls.nominalUsd = wb('TWN', 'X');
    expect(() => parseWorldGdp(text(orphan))).toThrow();
  });
  it('年の重複・逆順・範囲外と、値の不正を拒否します', () => {
    const cases: [number, string, unknown][] = [
      [0, 'nominalUsd', [[2021, 1], [2020, 2]]],
      [0, 'nominalUsd', [[2020, 1], [2020, 2]]],
      [0, 'nominalUsd', [[1800, 1]]],
      [0, 'nominalUsd', [[2020.5, 1]]],
      [0, 'nominalUsd', [[2020, 0]]],
      [0, 'nominalUsd', [[2020, -1]]],
      [0, 'nominalUsd', [[2020, null]]],
      [0, 'nominalUsd', [[2020, '1']]],
      [0, 'nominalUsd', []],
      [0, 'realGrowth', [[2020, 150]]],
      [0, 'perCapitaPpp', [[2020, 1, 2]]],
    ];
    for (const [index, metric, points] of cases) {
      const data = sample(); data.countries[index].series[metric] = points;
      expect(() => parseWorldGdp(text(data)), JSON.stringify(points)).toThrow();
    }
    const unknown = sample(); unknown.countries[0].series.population = [[2020, 1]];
    expect(() => parseWorldGdp(text(unknown))).toThrow();
  });
});

describe('期間平均と順位の計算', () => {
  const data = parseWorldGdp(text(sample()));
  it('実質成長率を複利で平均します', () => {
    const result = averageGrowth([[2020, 10], [2021, -10]], 2020, 2021)!;
    expect(result.value).toBeCloseTo((Math.sqrt(1.1 * 0.9) - 1) * 100, 10);
    expect(result).toMatchObject({ from: 2020, to: 2021, years: 2 });
    expect(averageGrowth([[2020, 1]], 2021, 2022)).toBeNull();
  });
  it('水準の系列から年平均の伸びを求めます', () => {
    const result = levelGrowth([[2020, 40000], [2022, 44100]], 2000, 2030)!;
    expect(result.value).toBeCloseTo(5, 10);
    expect(result.years).toBe(2);
    expect(levelGrowth([[2020, 1]], 2000, 2030)).toBeNull();
  });
  it('期間は指標の収録範囲に合わせます', () => {
    expect(periodRange(data, 'realGrowth', 'all')).toEqual({ from: 2020, to: 2022 });
    expect(periodRange(data, 'realGrowth', '1990')).toEqual({ from: 2020, to: 2022 });
    expect(periodRange(data, 'nominalUsd', '2015')).toEqual({ from: 2020, to: 2021 });
  });
  it('期間平均成長率の順位と、収録年が短い国の年数', () => {
    const rows = growthRanking(data, 2020, 2022);
    expect(rows.map(row => row.code)).toEqual(['TWN', 'USA', 'JPN']);
    expect(rows[0].growth).toMatchObject({ from: 2021, to: 2022, years: 2 });
    expect(rows.find(row => row.code === 'JPN')!.rank).toBe(3);
    expect(growthRanking(data, 2020, 2022, 'perCapita').map(row => row.code)).toEqual(['JPN']);
  });
  it('最新年の順位は値の大きい順で、値の無い国を入れません', () => {
    const rows = latestRanking(data, 'nominalUsd');
    expect(rows.map(row => [row.code, row.rank, row.year])).toEqual([['USA', 1, 2021], ['JPN', 2, 2021]]);
  });
});

describe('目盛りと表記', () => {
  it('線形・対数の目盛り', () => {
    expect(linearTicks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(linearTicks(-27, 19, 5)).toEqual([-20, -10, 0, 10]);
    expect(logTicks(4e9, 3e13)).toEqual([1e10, 1e11, 1e12, 1e13]);
    expect(logTicks(1500, 95000)).toEqual([2000, 5000, 10000, 20000, 50000]);
    expect(logTicks(0, 10)).toEqual([]);
  });
  it('金額と率の表記', () => {
    expect(formatUsd(4.4e12)).toBe('4.4兆ドル');
    expect(formatUsd(30.77e12)).toBe('30.8兆ドル');
    expect(formatUsd(4e9)).toBe('40億ドル');
    expect(formatRate(1.234)).toBe('+1.2％');
    expect(formatRate(-0.5)).toBe('−0.5％');
  });
});

describe('成長要因の調査結果', () => {
  it('同梱のファイルを読めます（空でも可）', () => {
    expect(Array.isArray(parseGrowthCauses(growthCausesFile).countries)).toBe(true);
  });
  it('https 以外の出典は表示から外し、形が崩れたものは拒否します', () => {
    const value = { method: '方法', countries: [{ code: 'KOR', name: '韓国', summary: '要約', claims: [{ id: 'k1', factor: '要因', claim: '主張', japanContrast: '日本では', sources: [{ title: '公式', url: 'https://www.imf.org/x' }, { title: '平文', url: 'http://example.com' }, { title: 'スクリプト', url: 'javascript:alert(1)' }] }] }] };
    expect(parseGrowthCauses(value).countries[0].claims[0].sources).toEqual([{ title: '公式', url: 'https://www.imf.org/x' }]);
    expect(() => parseGrowthCauses({ countries: [{ code: 'KOR' }], method: '' })).toThrow();
    expect(() => parseGrowthCauses({ countries: 'x', method: '' })).toThrow();
    const dupe = { method: '', countries: [{ ...value.countries[0], claims: [value.countries[0].claims[0], value.countries[0].claims[0]] }] };
    expect(() => parseGrowthCauses(dupe)).toThrow();
  });
});
