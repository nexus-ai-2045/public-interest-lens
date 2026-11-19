// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { magnitudeLabel, niceMax, parseCharts, ticks, timelineValues } from './numbers-view';

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
  it('向き未確定の額は国賊側・国士側に入れず、別の欄で数える（リリース前レビュー指摘1）', () => {
    // @ts-ignore Node の URL を使う
    const charts = parseCharts(JSON.parse(readFileSync(new URL('../public/distribution/charts.json', import.meta.url), 'utf8')));
    for (const c of charts.byCertainty) {
      expect(c.loss + c.benefit + c.undetermined).toBe(c.laws);
      if (c.certainty !== '参考') expect(c.undetermined).toBe(0);
    }
    for (const t of charts.timeline) expect(t).toHaveProperty('referenceUndetermined');
  });
  it('時系列：向き未確定は上下に分けず、大きさだけを上に出す', () => {
    const t = { year: 2000, laws: 3, confirmedLoss: 1, confirmedBenefit: 2, referenceLoss: 3, referenceBenefit: 4, referenceUndetermined: 5 };
    expect(timelineValues(t, 'confirmed')).toEqual({ up: 2, down: 1 });
    expect(timelineValues(t, 'reference')).toEqual({ up: 4, down: 3 });
    expect(timelineValues(t, 'undetermined')).toEqual({ up: 5, down: 0 });
  });
  it('旧い形（public-charts/v1：向き未確定を側に混ぜた集計）は読まない', () => {
    expect(() => parseCharts({ schema: 'public-charts/v1', histogram: [], timeline: [] })).toThrow();
  });
});
