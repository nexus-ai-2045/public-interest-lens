// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DEFAULT_QUERY, collapseObservations, detailBundleUrl, filterCatalog, groupByObservation, isOutlierMark, parseLawsCatalog, readQuery, writeQuery } from './laws-catalog';
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
    const rank = (step: string, amount: unknown) => step === 'published' ? 0 : amount ? 1 : 2;
    for (let i = 1; i < list.length; i++) {
      const [a, b] = [list[i - 1], list[i]];
      expect(rank(a.step, a.amount)).toBeLessThanOrEqual(rank(b.step, b.amount));
      if (rank(a.step, a.amount) === rank(b.step, b.amount) && a.amount && b.amount) expect(a.amount.median).toBeGreaterThanOrEqual(b.amount.median);
    }
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'confirmed' }).every(item => item.step === 'published')).toBe(true);
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
  it('損失順は損失の行が先、便益順は便益の行が先で、それぞれ額の大きい順', () => {
    for (const [sort, side] of [['loss', 'loss'], ['benefit', 'benefit']] as const) {
      const list = filterCatalog(catalog.laws, { ...DEFAULT_QUERY, sort });
      const firstOther = list.findIndex(item => item.side !== side);
      expect(list.slice(0, firstOther).every(item => item.side === side)).toBe(true);
      expect(list.slice(firstOther).some(item => item.side === side)).toBe(false);
      const head = list.slice(0, firstOther).filter(item => item.step === 'published');
      for (let i = 1; i < head.length; i++) expect(head[i - 1].amount!.median).toBeGreaterThanOrEqual(head[i].amount!.median);
      expect(readQuery(`?sort=${sort}`).sort).toBe(sort);
    }
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
