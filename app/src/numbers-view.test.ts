// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { magnitudeLabel, niceMax, parseCharts, ticks } from './numbers-view';

describe('数字で見る（numbers-view）', () => {
  it('桁の名前と目盛り', () => {
    expect(magnitudeLabel(12)).toBe('1兆円');
    expect(magnitudeLabel(14)).toBe('100兆円');
    expect(magnitudeLabel(11)).toBe('1000億円');
    expect(niceMax(87)).toBe(100);
    expect(niceMax(130)).toBe(200);
    expect(ticks(100, 4)).toEqual([0, 25, 50, 75, 100]);
  });
  it('公開の charts.json が読め、旧方式の議員の配分の節（members・roles・parties）を持たない', () => {
    // @ts-ignore Node の URL を使う
    const charts = parseCharts(JSON.parse(readFileSync(new URL('../public/distribution/charts.json', import.meta.url), 'utf8')));
    expect(charts.histogram.length).toBeGreaterThan(0);
    for (const key of ['members', 'roles', 'parties']) expect(charts).not.toHaveProperty(key);
  });
});
