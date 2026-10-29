// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { countByState, filterActors, filterRulings, parseStopSide, rulingKind } from './stop-side';

const committed = readFileSync(new URL('../public/distribution/stop-side.json', import.meta.url), 'utf8');
const sample = () => ({
  schema: 'public-stop-side/v1', notes: ['注記'], counts: { actors: 2 },
  groups: [{ key: 'hotline', label: '甲', about: '乙' }],
  actors: [
    { h: 'a1', g: 'hotline', v: 'c', o: '国土交通省', t: 'ライドシェア', l: '道路運送法', u: 'https://www8.cao.go.jp/x.pdf' },
    { h: 'a2', g: 'hotline', v: 'h', o: '厚生労働省', t: '医薬品', r: 'ページ違い' },
  ],
  rulings: [{ id: 'r1', name: 'タクシー運賃', rule: '特措法', court: '大阪地裁', date: '2015-12-16', no: '平成26(行ウ)105', judge: '違法・無効（説明）', summary: '要旨', check: '2系統一致' }],
  rulingsHeld: [],
});

describe('止めた側のデータの検証', () => {
  it('配布中のファイルをそのまま読めて、件数が数え直しと合う', () => {
    const data = parseStopSide(committed);
    expect(data.actors).toHaveLength(data.counts.actors);
    const by = countByState(data.actors);
    expect([by.c, by.h, by.u]).toEqual([data.counts.confirmed, data.counts.held, data.counts.unchecked]);
    expect(data.rulings).toHaveLength(data.counts.rulings);
    expect(data.rulingsHeld).toHaveLength(data.counts.rulingsHeld);
  });
  it('URL のない行にリンクを作らず、リンクは https の官公庁資料だけ', () => {
    const data = parseStopSide(committed);
    expect(data.actors.filter(a => a.u).length).toBe(data.counts.withLink);
    expect(data.actors.every(a => !a.u || a.u.startsWith('https://'))).toBe(true);
    expect(data.rulings.every(r => !r.u || r.u.startsWith('https://www.courts.go.jp/'))).toBe(true);
  });
  it('保留の行は理由を持つ（誤りの型が無い保留を除く）', () => {
    const data = parseStopSide(committed);
    const held = data.actors.filter(a => a.v === 'h');
    expect(held.filter(a => a.r).length).toBeGreaterThan(held.length * 0.9);
  });
  it('形式の違う入力・http の URL・未知の印を受け付けない', () => {
    expect(() => parseStopSide('{}')).toThrow();
    const bad = sample(); bad.actors[0].u = 'http://example.test/';
    expect(() => parseStopSide(JSON.stringify(bad))).toThrow();
    const odd = sample(); (odd.actors[0] as { v: string }).v = 'x';
    expect(() => parseStopSide(JSON.stringify(odd))).toThrow();
  });
  it('系統・印・ことばで絞る', () => {
    const data = parseStopSide(JSON.stringify(sample()));
    expect(filterActors(data.actors, { group: 'all', state: 'c', query: '' }).map(a => a.h)).toEqual(['a1']);
    expect(filterActors(data.actors, { group: 'hotline', state: 'all', query: '道路運送法 ライド' }).map(a => a.h)).toEqual(['a1']);
    expect(filterActors(data.actors, { group: 'hotline', state: 'all', query: 'なにもない語' })).toEqual([]);
  });
  it('判決は規制への判断の頭の語で分ける', () => {
    const data = parseStopSide(JSON.stringify(sample()));
    expect(rulingKind(data.rulings[0])).toBe('違法・無効');
    expect(filterRulings(data.rulings, '違法・無効', 'タクシー')).toHaveLength(1);
    expect(filterRulings(data.rulings, '規制維持', '')).toHaveLength(0);
  });
});
