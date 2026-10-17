// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { GrowthBars, LatestTable, LineChart, type WorldView } from './WorldGdpPage';
import { parseWorldGdp } from './world-gdp';

const data = parseWorldGdp(readFileSync(new URL('../public/distribution/world-gdp.json', import.meta.url), 'utf8'));
const base: WorldView = { metric: 'nominalUsd', period: '1990', log: false, hidden: [], focus: '', basis: 'real' };

describe('世界のGDP比較の表示', () => {
  it('折れ線は日本を強調し、表示しない国を描きません', () => {
    const html = renderToStaticMarkup(<LineChart data={data} view={{ ...base, hidden: ['CHN'], focus: 'KOR', log: true }} hover="" onHover={() => {}} narrow={false} />);
    expect(html.match(/world-line-japan/g)).toHaveLength(1);
    expect(html.match(/world-line-focus/g)).toHaveLength(1);
    expect(html).not.toContain('中国：');
    expect(html).not.toContain('NaN');
  });
  it('実質成長率と一人あたりの線も描けます（狭い画面を含む）', () => {
    for (const metric of ['realGrowth', 'perCapitaPpp'] as const) for (const narrow of [true, false]) {
      const html = renderToStaticMarkup(<LineChart data={data} view={{ ...base, metric, period: 'all' }} hover="USA" onHover={() => {}} narrow={narrow} />);
      expect(html).toContain('world-line-japan');
      expect(html).not.toContain('NaN');
    }
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
