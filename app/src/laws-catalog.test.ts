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
    // 同じ額を共有する法律は額を出さなくなったので、3本以上の観測が残っているときだけ代表の動きを確かめる
    const [group] = [...groups.values()].filter(members => members.length > 2);
    if (group) {
      const withoutRep = group.slice(1);
      expect(collapseObservations(withoutRep).map(item => item.id)).toEqual([withoutRep[0].id]);
      expect(collapseObservations(withoutRep, new Set([withoutRep[1].id])).map(item => item.id)).toEqual([withoutRep[0].id, withoutRep[1].id]);
    }
    const none = filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'none' });
    expect(collapseObservations(none).length).toBe(none.length);
  });
  it('桁外れの印は倍率と一緒に付き、額も順位も変わらない', () => {
    const outliers = catalog.laws.filter(item => item.marks.some(isOutlierMark));
    expect(outliers.length).toBe(catalog.observations?.outliers);
    for (const item of outliers) { expect(item.scale).toBeGreaterThan(1); expect(item.amount).not.toBeNull(); }
    expect(catalog.laws.filter(item => item.scale !== undefined).length).toBe(outliers.length);
    expect(filterCatalog(catalog.laws, DEFAULT_QUERY).length).toBe(catalog.laws.length);
  });
});

describe('降格した法律の参考値の理由・根拠', () => {
  const row = (extra: Record<string, unknown>) => ({ id: '閣法-1-1', kind: '閣法', title: 'テスト法', year: 2000, field: 'その他', side: null, amount: null, marks: [], step: 'enacted', summary: '', ...extra });
  const parse = (extra: Record<string, unknown>) => parseLawsCatalog(JSON.stringify({ schema: 'public-laws/v1', counts: {}, fields: [], laws: [row(extra)], policies: [] })).laws[0];

  it('refReason・refBasis が文字列なら読む', () => {
    const item = parse({ refReason: '検証で降格', refBasis: '出典の表' });
    expect(item.refReason).toBe('検証で降格');
    expect(item.refBasis).toBe('出典の表');
  });

  it('文字列以外・空は無視し、欄が無くても落ちない', () => {
    const item = parse({ refReason: 3, refBasis: { a: 1 } });
    expect('refReason' in item).toBe(false);
    expect('refBasis' in item).toBe(false);
    expect('refReason' in parse({ refReason: '  ' })).toBe(false);
    expect('refReason' in parse({})).toBe(false);
  });
});

describe('共有額の参考値', () => {
  const shared = catalog.laws.filter(item => item.shared);
  it('1本ごとの額を持たず、群の総枠と本数を持つ。降格の印とは別', () => {
    expect(shared.length).toBe(catalog.shared?.laws);
    expect(shared.filter(item => item.shared.whole).length).toBe(catalog.shared?.whole);
    for (const item of shared) {
      expect(item.amount).toBeNull();
      expect(item.side).toBeNull();
      expect(item.shared.size).toBeGreaterThanOrEqual(2);
      expect(item.refReason).toBeUndefined();
      expect(item.observation?.key).toBe(item.shared.key);
      expect(item.observation?.size).toBe(item.shared.size);
      expect(detailOf(item.id).sharedBasis).toContain('使った前提');
    }
  });
  it('額なし・向きの絞り込みには入らず、専用の絞り込みで出る', () => {
    const ids = new Set(shared.map(item => item.id));
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'shared' }).map(item => item.id).sort()).toEqual([...ids].sort());
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'none' }).some(item => ids.has(item.id))).toBe(false);
    expect(filterCatalog(catalog.laws, { ...DEFAULT_QUERY, side: 'amount' }).some(item => ids.has(item.id))).toBe(false);
    expect(readQuery('?side=shared').side).toBe('shared');
  });
  it('既定の並びでは、額のある行の後・額なしの前に置く', () => {
    const list = filterCatalog(catalog.laws, DEFAULT_QUERY);
    const rank = (item: { amount: unknown; shared?: unknown }) => item.amount ? 0 : item.shared ? 1 : 2;
    const ranks = list.map(rank);
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });
  it('形の悪い共有額は読み込みを拒否する', () => {
    const row = (shared: unknown, amount: unknown = null) => JSON.stringify({ schema: 'public-laws/v1', counts: {}, fields: [], laws: [{ id: 'x', kind: '閣法', title: 't', year: 1, field: 'f', side: null, amount, marks: [], step: 'enacted', summary: 's', shared }], policies: [] });
    const ok = { key: 'k', size: 2, median: 10, low: 5, high: 20, side: 'loss', whole: false };
    expect(() => parseLawsCatalog(row(ok))).not.toThrow();
    expect(() => parseLawsCatalog(row({ ...ok, size: 1 }))).toThrow();
    expect(() => parseLawsCatalog(row({ ...ok, median: 30 }))).toThrow();
    expect(() => parseLawsCatalog(row(ok, { median: 1, low: 1, high: 1 }))).toThrow();
  });
});
