import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { GrowthCauses } from './GrowthCauses';
import { parseGrowthCauses } from './world-gdp';

describe('成長要因の表示', () => {
  it('調査結果が空なら何も表示しません', () => {
    expect(renderToStaticMarkup(<GrowthCauses data={{ countries: [], method: '' }} />)).toBe('');
  });
  it('要因・日本との違い・https の出典だけを表示します', () => {
    const data = parseGrowthCauses({ method: '公的統計と一次資料で確認しました。', countries: [{ code: 'KOR', name: '韓国', summary: '要約です。', claims: [{ id: 'k1', factor: '研究開発投資', claim: '主張です。', japanContrast: '日本との違いです。', sources: [{ title: '公式資料', url: 'https://www.imf.org/x' }, { title: '平文', url: 'http://example.com/' }] }] }] });
    const html = renderToStaticMarkup(<GrowthCauses data={data} />);
    expect(html).toContain('研究開発投資');
    expect(html).toContain('日本との違いです。');
    expect(html).toContain('https://www.imf.org/x');
    expect(html).not.toContain('http://example.com/');
  });
  it('日本との違いが空の要因は「日本では」を出しません', () => {
    const data = parseGrowthCauses({ method: '方法です。', countries: [{ code: 'NLD', name: 'オランダ', summary: '要約です。', claims: [{ id: 'n1', factor: '輸出', claim: '主張です。', japanContrast: '', sources: [] }] }] });
    const html = renderToStaticMarkup(<GrowthCauses data={data} />);
    expect(html).toContain('方法です。');
    expect(html).toContain('輸出');
    expect(html).not.toContain('日本では');
  });
  it('同梱の調査結果を読み込めます', async () => {
    const raw = (await import('./growth-causes.json')).default;
    const data = parseGrowthCauses(raw);
    expect(data.countries.map(c => c.code)).toEqual(['CHN', 'IND', 'VNM', 'IDN', 'KOR', 'TWN', 'USA', 'NLD', 'NOR', 'DEU', 'GBR']);
    expect(data.countries.every(c => c.claims.length > 0 && c.claims.every(claim => claim.sources.length > 0))).toBe(true);
  });
});
