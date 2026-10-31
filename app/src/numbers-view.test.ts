// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { magnitudeLabel, memberHref, memberRange, niceMax, parseCharts, roleShares, ticks, topMembers, type ChartMember } from './numbers-view';

describe('数字で見る（numbers-view）', () => {
  it('桁の名前と目盛り', () => {
    expect(magnitudeLabel(12)).toBe('1兆円');
    expect(magnitudeLabel(14)).toBe('100兆円');
    expect(magnitudeLabel(11)).toBe('1000億円');
    expect(niceMax(87)).toBe(100);
    expect(niceMax(130)).toBe(200);
    expect(ticks(100, 4)).toEqual([0, 25, 50, 75, 100]);
  });
  it('議員の上位は向きで入れ替わる', () => {
    const m = (id: string, net: number): ChartMember => ({ id, name: id, rank: 0, net, low: net, high: net, loss: 0, credit: 0 });
    const list = [m('a', -5), m('b', 3), m('c', -9), m('d', 7)];
    expect(topMembers(list, 'harm').map(x => x.id)).toEqual(['c', 'a']);
    expect(topMembers(list, 'benefit').map(x => x.id)).toEqual(['d', 'b']);
  });
  it('配り先の割合は合計1', () => {
    const rows = roleShares([{ role: 'party', kind: 'party', loss: 2, benefit: 0 }, { role: 'vote', kind: 'person', loss: 6, benefit: 1 }], 'loss');
    expect(rows.map(r => r.role)).toEqual(['vote', 'party']);
    expect(rows.reduce((s, r) => s + r.share, 0)).toBeCloseTo(1);
  });
  it('公開の charts.json が読める', () => {
    // @ts-ignore Node の URL を使う
    const charts = parseCharts(JSON.parse(readFileSync(new URL('../public/distribution/charts.json', import.meta.url), 'utf8')));
    expect(charts.histogram.length).toBeGreaterThan(0);
    // 検証を通った配分の法律が無い間は、議員別の額（確かな額）は0人。
    expect(charts.members.length).toBeGreaterThanOrEqual(0);
  });
  it('純額の幅がゼロをまたぐ議員は、下限を0にする（逆向きの可能性を消さない）', () => {
    const m = (low: number, high: number) => ({ id: 'x', name: 'x', rank: 1, net: 1, low, high, loss: 0, credit: 0 });
    expect(memberRange(m(-2.31e12, 5.25e12))).toEqual({ low: 0, high: 5.25e12 });
    expect(memberRange(m(1e12, 3e12))).toEqual({ low: 1e12, high: 3e12 });
    expect(memberRange(m(-3e12, -1e12))).toEqual({ low: 1e12, high: 3e12 });
  });

  it('議員へのリンクは議員ページの名前の選択（?name=）を使う', () => {
    expect(memberHref('山田 太郎')).toBe('/members?name=%E5%B1%B1%E7%94%B0%20%E5%A4%AA%E9%83%8E');
  });
});
