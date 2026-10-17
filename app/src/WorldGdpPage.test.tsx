// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { GrowthBars, LatestTable, worldBaseYear, worldLineSeries, type WorldView } from './WorldGdpPage';
import { parseWorldGdp } from './world-gdp';

const data = parseWorldGdp(readFileSync(new URL('../public/distribution/world-gdp.json', import.meta.url), 'utf8'));
const base: WorldView = { metric: 'nominalUsd', period: '1990', indexed: false, hidden: [], focus: '', basis: 'real' };

describe('世界のGDP比較の表示', () => {
  it('折れ線の系列は表示しない国を除き、期間の中の年だけを持ちます', () => {
    const lines = worldLineSeries(data, { ...base, hidden: ['CHN'] });
    expect(lines.some(line => line.id === 'CHN')).toBe(false);
    expect(lines.some(line => line.id === 'JPN')).toBe(true);
    for (const line of lines) for (const point of line.points) expect(point.year).toBeGreaterThanOrEqual(1990);
    expect(worldBaseYear(data, base)).toBe(1990);
  });
  it('一人あたりの線には台湾を入れません（同じ基準の値が無いため）', () => {
    const lines = worldLineSeries(data, { ...base, metric: 'perCapitaPpp', period: 'all' });
    expect(lines.some(line => line.id === 'TWN')).toBe(false);
    expect(lines.length).toBe(16);
  });
  it('最新年の順位表と期間平均の横棒で、日本の順位を示します', () => {
    const table = renderToStaticMarkup(<LatestTable data={data} view={base} />);
    expect(table).toMatch(/日本は<strong>\d+か国・地域中\d+位<\/strong>/);
    expect(table).toContain('class="is-japan"');
    const bars = renderToStaticMarkup(<GrowthBars data={data} view={{ ...base, period: '2000', basis: 'perCapita' }} />);
    expect(bars).toMatch(/日本は<strong>\d+か国・地域中\d+位<\/strong>/);
    expect(bars).not.toContain('台湾');
    expect(bars).not.toContain('NaN');
  });
});
