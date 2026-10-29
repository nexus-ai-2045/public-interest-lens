// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DEFAULT_QUERY, certaintyTier, collapseObservations, detailBundleUrl, filterCatalog, groupByObservation, isOutlierMark, parseLawsCatalog, readQuery, straddlesZero, writeQuery } from './laws-catalog';
import { plainLawName } from './law-name';

const catalog = parseLawsCatalog(readFileSync(new URL('../public/distribution/laws.json', import.meta.url), 'utf8'));
const bundles = new Map<string, Record<string, unknown>>();
const detailOf = (id: string) => {
  const url = detailBundleUrl(id);
  if (!bundles.has(url)) bundles.set(url, JSON.parse(readFileSync(new URL(`../public${url}`, import.meta.url), 'utf8')).items);
  return bundles.get(url)![id];
};

describe('全法律の一覧', () => {
  it('成立した法律を全部載せ、政策も同じ一覧に入れる', () => {
    expect(catalog.laws.length).toBe(catalog.counts.enacted);
    expect(new Set(catalog.laws.map(item => item.id)).size).toBe(catalog.laws.length);
    expect(catalog.policies.some(item => item.title === '金融再生プログラム')).toBe(true);
  });
  it('額のない行には必ず理由があり、額のある行には向きがある', () => {
    for (const item of [...catalog.laws, ...catalog.policies]) {
      expect(item.summary.length).toBeGreaterThan(0);
      if (item.amount) expect(item.side).not.toBeNull();
      expect(detailOf(item.id)).toBeTruthy();
    }
  });
  it('既定の並びは確かな額 → 参考の額 → 額なしの順で、組の中は額の大きい順', () => {
    const list = filterCatalog(catalog.laws, DEFAULT_QUERY);
    for (let i = 1; i < list.length; i++) {
      const [a, b] = [list[i - 1], list[i]];
      expect(certaintyTier(a)).toBeLessThanOrEqual(certaintyTier(b));
      if (certaintyTier(a) === certaintyTier(b) && a.amount && b.amount) expect(a.amount.median).toBeGreaterThanOrEqual(b.amount.median);
    }
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'confirmed' }).every(item => item.certainty === '高' || item.certainty === '中')).toBe(true);
  });
  it('確かな額は高・中だけで、確かさ低は別に数える（低は幅が0をまたぐ旨を幅から決める）', () => {
    const solid = filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'confirmed' });
    const low = filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'low' });
    // 出所：public-distribution の laws.json（counts.published は高・中・低の合計）。
    expect(solid.length + low.length).toBe(catalog.counts.published);
    expect(low.every(item => item.certainty === '低' && item.amount)).toBe(true);
    expect(solid.some(item => item.certainty === '低')).toBe(false);
    // 既定の並びでも、低は高・中より後ろに来る。
    const order = filterCatalog(catalog.laws, DEFAULT_QUERY).filter(item => item.certainty === '高' || item.certainty === '中' || item.certainty === '低');
    expect(order.slice(0, solid.length).every(item => item.certainty !== '低')).toBe(true);
    // 幅が0をまたぐ印は、幅そのものから決める。データの印と食い違わない。
    for (const item of low) expect(item.marks.some(mark => mark.startsWith('向きが定まらない')) === straddlesZero(item.amount)).toBe(true);
    expect(straddlesZero({ median: 1, low: -1, high: 2 })).toBe(true);
    expect(straddlesZero({ median: 5, low: 1, high: 9 })).toBe(false);
    expect(straddlesZero(null)).toBe(false);
  });
  it('検索・向き・分野で絞れる', () => {
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, text: 'サイバーセキュリティ基本法' }).map(item => item.id)).toContain('衆法-186-35');
    // 画面に出す「何をする法律」の呼び方でも見つかる。
    const named = catalog.laws.find(item => item.id === '閣法-142-49')!;
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, text: plainLawName(named.what!) }).map(item => item.id)).toContain('閣法-142-49');
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'loss' }).every(item => item.side === 'loss')).toBe(true);
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'none' }).every(item => !item.amount)).toBe(true);
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, field: '金融' }).every(item => item.field === '金融')).toBe(true);
  });
  it('古い順でも新しい順でも、年の無い行は最後', () => {
    for (const sort of ['oldest', 'newest'] as const) expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, sort }).at(-1)!.year).toBeNull();
  });
  it('絞り込みは URL に書き出して読み戻せる', () => {
    const query = { text: '観光', side: 'loss' as const, field: '宿泊・観光', kind: '閣法', sort: 'newest' as const };
    expect(readQuery(writeQuery(query))).toEqual(query);
    expect(writeQuery(DEFAULT_QUERY)).toBe('');
  });
  it('同じ観測は代表の1行にまとめ、絞り込みで代表が外れても1本は残る', () => {
    const list = filterCatalog(catalog.laws, DEFAULT_QUERY);
    const rows = collapseObservations(list);
    const groups = groupByObservation(catalog.laws);
    expect(rows.filter(item => item.observation).length).toBe(groups.size);
    expect(catalog.observations?.count).toBe(groups.size);
    for (const row of rows) if (row.observation) expect(row.observation.representative).toBe(true);
    for (const [, members] of groups) {
      expect(members.filter(item => item.observation!.representative).length).toBe(1);
      // 代表は確かさの高い順（高・中・低・参考）、同じなら id の小さい法律。
      const rank = (c?: string) => ['高', '中', '低', '参考'].indexOf(c ?? '参考');
      const best = [...members].sort((a, b) => rank(a.certainty) - rank(b.certainty) || a.id.localeCompare(b.id))[0];
      expect(best.observation!.representative).toBe(true);
      expect(members[0].observation!.size).toBe(members.length);
    }
    const [group] = [...groups.values()].filter(members => members.length > 2);
    const withoutRep = group.slice(1);
    expect(collapseObservations(withoutRep).map(item => item.id)).toEqual([withoutRep[0].id]);
    expect(collapseObservations(withoutRep, new Set([withoutRep[1].id])).map(item => item.id)).toEqual([withoutRep[0].id, withoutRep[1].id]);
    const none = filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'none' });
    expect(collapseObservations(none).length).toBe(none.length);
  });
  it('桁外れの印は倍率と一緒に付き、額も順位も変わらない', () => {
    const outliers = catalog.laws.filter(item => item.marks.some(isOutlierMark));
    expect(outliers.length).toBe(catalog.observations?.outliers);
    expect(outliers.length).toBeGreaterThan(0);
    for (const item of outliers) { expect(item.scale).toBeGreaterThan(1); expect(item.amount).not.toBeNull(); }
    expect(catalog.laws.filter(item => item.scale !== undefined).length).toBe(outliers.length);
    expect(filterCatalog(catalog.laws, DEFAULT_QUERY).length).toBe(catalog.laws.length);
  });
});
