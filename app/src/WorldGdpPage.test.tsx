// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { DEFAULT_METRIC, GrowthBars, LatestTable, MissedGrowthSummary, droppedForBase, parseWorldView, worldAccents, worldBaseYear, worldLineSeries, type WorldView } from './WorldGdpPage';
import { cumulateGrowth, parseWorldGdp } from './world-gdp';

const data = parseWorldGdp(readFileSync(new URL('../public/distribution/world-gdp.json', import.meta.url), 'utf8'));
const base: WorldView = { metric: 'nominalUsd', period: '1990', indexed: false, log: false, hidden: [], focus: '', basis: 'real' };

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
  it('既定は一人あたりGDPを初期年＝100で見る表示で、実質成長率は選択肢の最後です', () => {
    expect(DEFAULT_METRIC).toBe('perCapitaPpp');
    const view = parseWorldView('');
    expect(view.metric).toBe('perCapitaPpp');
    expect(view.indexed).toBe(true);
    expect(parseWorldView('?scale=abs').indexed).toBe(false);
    expect(parseWorldView('?metric=nominal').metric).toBe('nominalUsd');
    expect(parseWorldView('?metric=realgdp').metric).toBe('realGdp');
    expect(parseWorldView('?metric=unknown').metric).toBe('perCapitaPpp');
    expect(data.countries.every(country => (country.series.realGrowth ?? []).length > 0)).toBe(true);
  });
  it('実質成長率の積み上げ（実質GDP）は、年ごとの率を複利で掛け合わせたものです', () => {
    const points = cumulateGrowth([[2001, 10], [2002, -10], [2003, 0]])!;
    expect(points[0]).toEqual([2000, 100]);
    expect(points.map(([, value]) => Math.round(value * 100) / 100)).toEqual([100, 110, 99, 99]);
    expect(cumulateGrowth([[2001, 10], [2003, 10]])!.length).toBe(2);
    const japan = data.countries.find(country => country.code === 'JPN')!.series.realGdp!;
    expect(japan.at(-1)![1]).toBeGreaterThan(japan[0][1]);
  });
  it('日本・米国・中国のほかに、期間で伸びた国の色を分け、初期年の値が無い国は指数から外します', () => {
    const { colors, leaders } = worldAccents(data, { ...base, metric: 'perCapitaPpp', period: '2000' });
    expect(colors.USA).toBeDefined();
    expect(colors.CHN).toBeDefined();
    expect(colors.JPN).toBeUndefined();
    expect(leaders.length).toBe(4);
    expect(new Set(Object.values(colors)).size).toBe(Object.keys(colors).length);
    expect(droppedForBase(data, { ...base, metric: 'realGdp', period: '1960', indexed: true })).toContain('ロシア');
  });
  it('原因の軸の結論は3行で、失敗型の国の注記と式へのリンクを持ち、原因を断定しません', () => {
    const html = renderToStaticMarkup(<MissedGrowthSummary />);
    expect(html.match(/<li>/g)).toHaveLength(3);
    for (const name of ['イタリア', 'ロシア', 'ブラジル']) expect(html).toContain(name);
    expect(html).toContain('href="/methodology#spec-cause-axis"');
    expect(html).toContain('暫定');
    expect(html).toContain('原因は特定せず');
  });
});
