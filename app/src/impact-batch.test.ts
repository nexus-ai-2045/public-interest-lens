import { describe, expect, it } from 'vitest';
import {
  FISCAL_YEAR_FILES, INDICATOR_MAP, asOfYear, buildCrossCountry, buildImpactSeries, buildPairPoints, chooseOption, evaluateLaw, extractSeries, intlByCountry,
  chooseIntlSpec, directionOf, matchTitleRule, mapRow, neededYears, resolveMapping, USAGE_TITLE_RULES, pandemicOverlap, parseCsv, startPeriod, toCsv, MAP_HEADER, type Mapping, type Tables,
} from './impact-batch';

// すべて人工の表です。実在の統計ではありません。
const csv = (header: string, rows: (string | number)[][]) => parseCsv(toCsv(header.split(','), rows));
const yearly = (from: number, values: number[], extra: string[] = []) => values.map((v, i) => [...extra, from + i, v]);

describe('CSV の読み書き', () => {
  it('引用符の中のカンマ・改行・二重引用符を読み、書き戻せる', () => {
    const rows = parseCsv('﻿a,b\n"農業,林業","x""y"\r\n"改\n行",2\n');
    expect(rows).toEqual([{ a: '農業,林業', b: 'x"y' }, { a: '改\n行', b: '2' }]);
    expect(parseCsv(toCsv(['a', 'b'], rows.map(r => [r.a, r.b])))).toEqual(rows);
  });
});

describe('系列の取り出しと窓', () => {
  const tables: Tables = new Map([
    ['t.csv', csv('系列,年,値', [...yearly(2000, [1, 2, 3], ['A']), ['A', 2003, ''], ...yearly(2000, [5, 5], ['B'])])],
    ['dup.csv', csv('系列,年,値', [['A', 2000, 1], ['A', 2000, 2]])],
  ]);

  it('空欄の年は入れず（0で埋めない）、同じ年に違う値があれば止める', () => {
    expect([...extractSeries(tables, { file: 't.csv', where: { 系列: 'A' } })]).toEqual([[2000, 1], [2001, 2], [2002, 3]]);
    expect(() => extractSeries(tables, { file: 'dup.csv', where: { 系列: 'A' } })).toThrow('同じ年に異なる値');
    expect(() => extractSeries(tables, { file: 'none.csv', where: {} })).toThrow('未読込');
  });

  it('判定に必要な年は、開始年の5年前から4年後まで（開始前5年＋開始後1〜5年目）', () => {
    expect(neededYears('2005-04-01')).toEqual([2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009]);
  });

  it('候補は必要な年を多く覆うものを選び、同数なら先に書いた（新しい基準の）ものを選ぶ', () => {
    const t: Tables = new Map([
      ['new.csv', csv('k,年,値', [...yearly(1994, Array(31).fill(1), ['x']), ...yearly(1994, Array(31).fill(1), ['y'])])],
      ['old.csv', csv('k,年,値', [...yearly(1980, Array(30).fill(1), ['x']), ...yearly(1980, Array(30).fill(1), ['y'])])],
    ]);
    const opts = ['new.csv', 'old.csv'].map(file => ({ file, a: { file, where: { k: 'x' } }, b: { file, where: { k: 'y' } } }));
    expect(chooseOption(t, '1992-04-01', opts, o => [o.a, o.b])!.option.file).toBe('old.csv');
    expect(chooseOption(t, '2001-04-01', opts, o => [o.a, o.b])!.option.file).toBe('new.csv');
  });

  it('対象と比較を、開始前の最後の共通年=100にそろえ、両方に値がある年だけ残す', () => {
    const a = new Map([[2000, 50], [2001, 100], [2002, 150], [2003, 200]]);
    const b = new Map([[2000, 10], [2001, 20], [2003, 40]]);
    const { points, baseYear } = buildPairPoints(a, b, '2002-04-01');
    expect(baseYear).toBe(2001);
    expect(points).toEqual([
      { asOf: '2000-12-31', treated: 50, control: 50 },
      { asOf: '2001-12-31', treated: 100, control: 100 },
      { asOf: '2003-12-31', treated: 200, control: 200 },
    ]);
    expect(buildPairPoints(a, b, '1999-01-01').baseYear).toBeNull();
  });

  it('年度の系列は4月始まりで数え、期末を翌年3月31日にする（1〜3月の開始は前年度が1年目）', () => {
    expect(startPeriod('2019-04-01', 'fiscal')).toBe(2019);
    expect(startPeriod('2019-03-31', 'fiscal')).toBe(2018);
    expect(startPeriod('2019-03-31')).toBe(2019);
    expect(asOfYear(2018, 'fiscal')).toBe('2019-03-31');
    expect(neededYears('2019-02-01', 'fiscal')).toEqual([2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]);
    const a = new Map([[2016, 10], [2017, 20], [2018, 40]]), b = new Map([[2016, 1], [2017, 2], [2018, 4]]);
    // 2019-02-01 開始なら 2018年度（期末2019-03-31）は開始後。基準は2017年度。
    const { points, baseYear } = buildPairPoints(a, b, '2019-02-01', 'fiscal');
    expect(baseYear).toBe(2017);
    expect(points.map(p => p.asOf)).toEqual(['2017-03-31', '2018-03-31', '2019-03-31']);
    expect(points.filter(p => p.asOf < '2019-02-01')).toHaveLength(2);
  });

  it('開始後2〜5年目に新型コロナの年が入るときだけ注意を付ける', () => {
    expect(pandemicOverlap('2015-09-04')).toEqual([]);
    expect(pandemicOverlap('2016-04-01')).toEqual([2020]);
    expect(pandemicOverlap('2020-12-01')).toEqual([2021, 2022]);
  });
});

describe('国際比較の点列', () => {
  const byCountry = new Map([
    ['JPN', new Map([[2000, 50], [2001, 100]])],
    ['USA', new Map([[2000, 10], [2001, 20]])],
    ['KOR', new Map([[2000, 10]])],
  ]);
  it('指数は日本の開始前最後の年=100に全員そろえ、その年の値が無い国は外す', () => {
    const built = buildCrossCountry(byCountry, { code: 'X', label: 'X', rebase: true, better: 'higher' }, '2002-01-01')!;
    expect(built.baseYear).toBe(2001);
    expect(built.controls.map(c => c.country)).toEqual(['USA']);
    expect(built.treated).toEqual([{ asOf: '2000-12-31', value: 50 }, { asOf: '2001-12-31', value: 100 }]);
  });
  it('比率はそろえずにそのまま渡し、全ての比較国を残す', () => {
    const built = buildCrossCountry(byCountry, { code: 'X', label: 'X', rebase: false, better: 'higher' }, '2002-01-01')!;
    expect(built.controls.map(c => c.country)).toEqual(['KOR', 'USA']);
    expect(built.controls[1].points[1].value).toBe(20);
  });
  it('日本に開始前の値が無ければ、比率でも比べない（null）', () => {
    expect(buildCrossCountry(byCountry, { code: 'X', label: 'X', rebase: false, better: 'higher' }, '2000-06-01')).toBeNull();
  });
  it('別ファイルの国際系列（国が「区分」列）を、指標の行だけ国ごとに読む', () => {
    const t: Tables = new Map([['w.csv', csv('系列,区分,年,値,備考', [
      ['A', 'JPN', 2000, 1, 'WB X'], ['A', 'JPN', 2001, 2, 'WB X'], ['A', 'USA', 2000, 3, 'WB X'], ['A', 'USA', 2001, '', 'WB X'], ['B', 'JPN', 2000, 9, 'WB Y'],
    ])]]);
    const source = { file: 'w.csv', countryColumn: '区分', where: { 備考: 'WB X' } };
    const got = intlByCountry(t, { code: 'WB:X', label: 'X', rebase: false, better: 'lower', source });
    expect([...got.keys()]).toEqual(['JPN', 'USA']);
    expect([...got.get('JPN')!]).toEqual([[2000, 1], [2001, 2]]);
    expect([...got.get('USA')!]).toEqual([[2000, 3]]);
    expect(() => intlByCountry(t, { code: 'WB:X', ratio: 'WB:Y', label: 'X', rebase: false, better: 'lower', source })).toThrow('ratio');
  });
});

describe('対応表と1法律の判定', () => {
  it('bill-triage-v1 の分野表の指標がすべて対応表にあり、系列なしには理由がある', () => {
    const triageIndicators = ['不良債権比率', '貸出残高', '企業倒産件数', '旅客輸送の付加価値', '利用件数', '就業者数', '宿泊者数', '宿泊業の付加価値', '客室数',
      '通信業の付加価値', 'ブロードバンド普及率', 'ネット企業の時価総額', '世界輸出シェア', '生産額', '電力価格', '発電構成', 'エネルギー効率', '労働生産性', '賃金', '雇用の流動性',
      '電子申請率', '行政手続きの時間'];
    expect(INDICATOR_MAP.map(m => m.indicator).sort()).toEqual([...triageIndicators].sort());
    for (const m of INDICATOR_MAP) {
      expect(m.reason.length).toBeGreaterThan(10);
      if (m.match === '系列なし') expect(m.target ?? m.intl ?? m.titleRules ?? null).toBeNull();
      else if (m.match !== '比較群なし') expect(m.target ?? m.intl ?? m.titleRules ?? null).not.toBeNull();
      expect(m.target === null || !m.titleRules).toBe(true);
      if (m.match === '比較群なし') expect(m.unused).toBeTruthy();
      expect(mapRow(m)).toHaveLength(MAP_HEADER.length);
    }
  });

  it('年度のファイルは年度の組にだけ使い、暦年の系列と組にしない', () => {
    for (const m of INDICATOR_MAP) for (const spec of [m.target, m.economy]) {
      if (!spec) continue;
      for (const o of spec.options) for (const ref of [o.treated, o.control]) {
        expect(FISCAL_YEAR_FILES.includes(ref.file), `${m.indicator} ${o.name}`).toBe(spec.period === 'fiscal');
      }
    }
  });

  it('全銀行に及ぶ不良債権比率は国内の比較群を作らず、国際比較だけ。労働市場の賃金・雇用の流動性は比較群なし', () => {
    const byName = new Map(INDICATOR_MAP.map(m => [m.indicator, m]));
    expect(byName.get('不良債権比率')).toMatchObject({ target: null, intl: { code: 'WB:FB.AST.NPER.ZS', better: 'lower' } });
    expect(byName.get('エネルギー効率')).toMatchObject({ target: null, intl: { code: 'WB:EG.EGY.PRIM.PP.KD', rebase: true } });
    for (const i of ['賃金', '雇用の流動性']) expect(byName.get(i)!.match).toBe('比較群なし');
    for (const i of ['企業倒産件数', '電子申請率', '行政手続きの時間', 'ネット企業の時価総額']) expect(byName.get(i)!.match).toBe('系列なし');
    expect(byName.get('利用件数')!.titleRules).toBe(USAGE_TITLE_RULES);
  });

  it('向きは指標ごとに固定し、決められない雇用の流動性は参考。不良債権は低いほど良い', () => {
    const byName = new Map(INDICATOR_MAP.map(m => [m.indicator, m]));
    expect(directionOf(byName.get('雇用の流動性')!)).toMatch(/^参考/);
    expect(directionOf(byName.get('賃金')!)).toBe('高いほど良い');
    expect(directionOf(byName.get('不良債権比率')!)).toBe('低いほど良い');
    expect(directionOf(byName.get('ブロードバンド普及率')!)).toBe('高いほど良い');
    expect(directionOf(byName.get('利用件数')!)).toBe('高いほど良い');
    expect(directionOf(byName.get('電子申請率')!)).toBe('');
    expect(byName.get('雇用の流動性')!.intl).toMatchObject({ reference: true, rebase: false });
    for (const m of INDICATOR_MAP) if (m.indicator !== '雇用の流動性') expect(m.intl?.reference).toBeUndefined();
  });

  it('国際の系列がない比較群なしの指標は判定ルールを呼ばず、判定を「比較群なし」にする', () => {
    const noIntl: Mapping = { indicator: '人工', field: '人工', match: '比較群なし', target: null, economy: null, share: [], intl: null, reason: '人工の理由です', unused: '人工' };
    const r = evaluateLaw(new Map(), { id: 'x', title: 't', field: '人工', indicator: '人工', start: '2005-04-01' }, [noIntl]);
    expect(r).toMatchObject({ verdict: '比較群なし', cross: '系列なし', effect: null, direction: '' });
    expect(r.reason).toMatch(/^比較群なし：/);
  });

  it('系列なしの指標は判定ルールを呼ばずに理由を返す', () => {
    const r = evaluateLaw(new Map(), { id: 'x', title: 't', field: '金融', indicator: '企業倒産件数', start: '2005-04-01' });
    expect(r).toMatchObject({ verdict: '系列なし', cross: '系列なし', effect: null });
    expect(r.reason).toMatch(/^系列なし：/);
    expect(evaluateLaw(new Map(), { id: 'x', title: 't', field: '金融', indicator: '未知', start: '2005-04-01' }).reason).toContain('対応表にない');
  });

  // 開始前はほぼ同じ伸び、開始後2年目以降に対象だけ伸びる。経済全体の指標も同じ向き、GDP比5%。
  const header = 'k,年,値';
  const treatedGrowth = [100, 100.2, 99.9, 100.1, 100, 101, 110, 111, 112, 113];
  const synthetic: Tables = new Map([
    ['s.csv', csv(header, [...yearly(2000, treatedGrowth, ['t']), ...yearly(2000, Array(10).fill(100), ['c']), ...yearly(2000, treatedGrowth.map(v => v * 0.5), ['et']), ...yearly(2000, Array(10).fill(50), ['ec']),
      ...yearly(2000, Array(10).fill(5), ['n']), ...yearly(2000, Array(10).fill(100), ['N'])])],
  ]);
  const ref = (k: string) => ({ file: 's.csv', where: { k } });
  const mapping: Mapping = {
    indicator: '人工', field: '人工', match: '直接', intl: null, reason: '人工の系列で試すための対応',
    target: { definition: '人工', better: 'higher', options: [{ name: '人工', treated: ref('t'), control: ref('c') }] },
    economy: { definition: '人工', better: 'higher', options: [{ name: '人工', treated: ref('et'), control: ref('ec') }] },
    share: [{ name: '人工', sector: ref('n'), total: ref('N') }],
  };

  it('窓を作って judgeImpact に渡し、経済全体の指標とGDP比も渡す', () => {
    const built = buildImpactSeries(synthetic, mapping, '2005-04-01')!;
    expect(built.baseYear).toBe(2004);
    expect(built.series.sectorGdpShare).toBe(0.05);
    expect(built.series.economy?.points).toHaveLength(10);
    const r = evaluateLaw(synthetic, { id: 'x', title: 't', field: '人工', indicator: '人工', start: '2005-04-01' }, [mapping]);
    expect(r.verdict).toBe('段階3');
    expect(r.direction).toBe('貢献');
    expect(r.effect).toBeGreaterThan(9);
  });

  it('年度の対応は年度で窓を作り、系列欄に年度と書く', () => {
    const fiscal: Mapping = { ...mapping, economy: null, share: [], target: { ...mapping.target!, period: 'fiscal' } };
    // 2006-02-01 開始は2005年度が1年目。開始前は2000〜2004年度、基準は2004年度。
    const built = buildImpactSeries(synthetic, fiscal, '2006-02-01')!;
    expect(built.baseYear).toBe(2004);
    expect(built.label).toContain('2004年度=100');
    expect(built.series.target.find(p => p.asOf === '2005-03-31')!.treated).toBe(100);
    expect(evaluateLaw(synthetic, { id: 'x', title: 't', field: '人工', indicator: '人工', start: '2006-02-01' }, [fiscal]).verdict).toBe('段階1');
  });

  it('開始後の年が足りなければ「期間が足りない」として保留', () => {
    const r = evaluateLaw(synthetic, { id: 'x', title: 't', field: '人工', indicator: '人工', start: '2009-04-01' }, [mapping]);
    expect(r).toMatchObject({ verdict: '保留', effect: null });
    expect(r.reason).toContain('期間が足りない');
  });
});

// ---- gap-stats の配線 ----

describe('国際の候補の選び方（つながない）', () => {
  const t: Tables = new Map([
    ['a.csv', csv('国,区分,年,値', [...yearly(2010, [1, 2, 3, 4, 5, 6, 7, 8], ['JPN', 'A']), ...yearly(2010, [1, 2, 3, 4, 5, 6, 7, 8], ['USA', 'A'])])],
    ['b.csv', csv('国,区分,年,値', [...yearly(1998, Array.from({ length: 23 }, (_, i) => i + 1), ['JPN', 'B']), ...yearly(1998, [9, 9, 9, 9, 9], ['USA', 'B'])])],
  ]);
  const spec = {
    code: 'X', label: 'X', rebase: false, better: 'lower' as const,
    source: { file: 'a.csv', countryColumn: '国', where: { 区分: 'A' }, name: 'A' },
    altSources: [{ file: 'b.csv', countryColumn: '国', where: { 区分: 'B' }, name: 'B' }],
  };
  it('日本の判定に必要な10年を最も多く覆う候補を、法律ごとに1つ選ぶ', () => {
    // 2001年施行は1996〜2005年が必要。A は0年、B は1998〜2005年の8年。
    expect(chooseIntlSpec(t, spec, '2001-04-01').source?.name).toBe('B');
    // 2016年施行は2011〜2020年が必要。A は2011〜2017年の7年、B は10年。
    expect(chooseIntlSpec(t, spec, '2016-04-01').source?.name).toBe('B');
    // 2013年施行は2008〜2017年が必要。A は2010〜2017年の8年、B は10年。
    expect(chooseIntlSpec(t, spec, '2013-01-01').source?.name).toBe('B');
  });
  it('同数なら先に書いた候補、候補が1つならそのまま。選んだ後は altSources を持たない', () => {
    const same = chooseIntlSpec(t, { ...spec, altSources: [{ ...spec.source, name: 'A2' }] }, '2013-01-01');
    expect(same.source?.name).toBe('A');
    expect(same.altSources).toBeUndefined();
    const single = { ...spec, altSources: undefined };
    expect(chooseIntlSpec(t, single, '2001-04-01')).toBe(single);
  });
  it('候補の値は混ぜない（選ばれなかった候補の年は使わない）', () => {
    const chosen = chooseIntlSpec(t, { ...spec, altSources: [{ ...spec.source, name: 'A2' }] }, '2013-01-01');
    const jp = intlByCountry(t, chosen).get('JPN')!;
    expect(jp.get(2010)).toBe(1);
    expect([...jp.keys()]).toHaveLength(8);
  });
});

describe('利用件数は題名がちょうど1つの施設・交通機関を名指すときだけ', () => {
  const mapping = INDICATOR_MAP.find(m => m.indicator === '利用件数')!;
  it('空港名・航空法の題名は1つの規則に当たり、交通政策基本法・港湾法・鉄道・道路・複数の名指しには当たらない', () => {
    expect(matchTitleRule(USAGE_TITLE_RULES, '中部国際空港の設置及び管理に関する法律案')?.keyword).toBe('中部国際空港');
    expect(matchTitleRule(USAGE_TITLE_RULES, '航空法の一部を改正する法律案')?.keyword).toBe('航空法');
    for (const title of ['交通政策基本法案', '港湾法の一部を改正する法律案', '鉄道軌道整備法の一部を改正する法律案', '道路法等の一部を改正する法律案', '自動車の保管場所の確保等に関する法律の一部を改正する法律案',
      '成田国際空港及び関西国際空港に関する法律案', '中部国際空港と航空法の法律案']) {
      expect(matchTitleRule(USAGE_TITLE_RULES, title), title).toBeNull();
    }
  });
  it('当たった規則は、その空港の暦年・合計の乗降客数を実質GDPと比べる対応になる', () => {
    const m = resolveMapping(mapping, { title: '中部国際空港の設置及び管理に関する法律案' })!;
    expect(m.target?.better).toBe('higher');
    expect(m.target?.options[0].treated).toEqual({ file: 'gap-stats/airport_passengers.csv', where: { 国: 'JPN', 区分: '中部国際（会社管理）／暦年／合計' } });
    expect(m.target?.options[0].control.where).toEqual({ 価格: '実質(連鎖方式)', 経済活動: '合計' });
    expect(resolveMapping(mapping, { title: '交通政策基本法案' })).toBeNull();
    // 題名で決めない指標はそのまま
    const other = INDICATOR_MAP.find(x => x.indicator === '宿泊者数')!;
    expect(resolveMapping(other, { title: '何でも' })).toBe(other);
  });
  it('名指しのない題名は系列なし（理由に題名の規則を書く）', () => {
    const r = evaluateLaw(new Map(), { id: 'x', title: '交通政策基本法案', field: '交通・移動', indicator: '利用件数', start: '2013-12-04' });
    expect(r).toMatchObject({ verdict: '系列なし', cross: '系列なし', effect: null });
    expect(r.reason).toContain('ちょうど1つだけ名指していない');
  });
  it('系列が施行より後に始まり開始前が3年に足りないときは、元の判定（系列なし）を保つ。開始前が足りれば判定する', () => {
    const airport = Array.from({ length: 12 }, (_, i) => ['JPN', '中部国際（会社管理）／暦年／合計', 2007 + i, 100 + (i < 8 ? 0 : 20 * (i - 7))]);
    const gdp = (price: string) => Array.from({ length: 30 }, (_, i) => [price, '合計', 1994 + i, 100 + i]);
    const tables: Tables = new Map([
      ['gap-stats/airport_passengers.csv', csv('国,区分,年,値', airport)],
      ...['2020', '2015', '2011', '2005', '2000'].map(b => [`domestic-stats/sna_gdp_by_industry_${b}base.csv`, csv('価格,経済活動,年,値', [...gdp('実質(連鎖方式)'), ...gdp('名目')])] as [string, Tables extends Map<string, infer R> ? R : never]),
    ]);
    const title = '中部国際空港の設置及び管理に関する法律案';
    const early = evaluateLaw(tables, { id: 'x', title, field: '交通・移動', indicator: '利用件数', start: '2005-04-01' });
    expect(early.verdict).toBe('系列なし');
    expect(early.reason).toContain('期間が足りない');
    const late = evaluateLaw(tables, { id: 'x', title, field: '交通・移動', indicator: '利用件数', start: '2011-04-01' });
    expect(late.verdict).not.toBe('系列なし');
    expect(late.series).toContain('中部国際空港');
  });
});

describe('国際比較だけ行う比較群なし・国内系列なしの指標', () => {
  const years = (from: number, n: number, f: (i: number) => number, country: string) => Array.from({ length: n }, (_, i) => [country, '区分X', from + i, f(i)]);
  const controls = ['USA', 'GBR', 'FRA', 'DEU', 'ITA'];
  const world = (jpFrom: number, jp: (i: number) => number): Tables => new Map([['gap-stats/t.csv', csv('国,区分,年,値', [
    ...years(jpFrom, 2030 - jpFrom, jp, 'JPN'), ...controls.flatMap(c => years(1990, 40, () => 10, c)),
  ])]]);
  const map = (reference: boolean): Mapping => ({
    indicator: '人工', field: '人工', match: '比較群なし', target: null, economy: null, share: [], reason: '人工の理由です', unused: '人工',
    intl: { code: 'X', label: '人工の国際系列', rebase: false, better: 'higher', reference, source: { file: 'gap-stats/t.csv', countryColumn: '国', where: { 区分: '区分X' } } },
  });
  const law = (start: string) => ({ id: 'x', title: 't', field: '人工', indicator: '人工', start });

  it('日本の開始前が3年に足りなければ、判定は比較群なしのまま、国際は保留で理由に系列の開始年を書く', () => {
    const r = evaluateLaw(world(2013, () => 10), law('2015-04-01'), [map(false)]);
    expect(r.verdict).toBe('比較群なし');
    expect(r.cross).toBe('保留');
    expect(r.reason).toContain('日本の開始前の観測が2年で、3年に足りない（日本の系列は2013年から）');
  });
  it('開始前が足りれば国際比較で段階が出る。判定の欄は比較群なしのまま', () => {
    const r = evaluateLaw(world(1990, i => (i < 25 ? 10 + (i % 2) * 0.1 : 20)), law('2015-04-01'), [map(false)]);
    expect(r.verdict).toBe('比較群なし');
    expect(r.cross).toMatch(/^段階1・貢献（比較国5か国/);
  });
  it('参考の指標は貢献・悪影響と書かず、日本が上昇／低下した向きだけを書く', () => {
    const up = evaluateLaw(world(1990, i => (i < 25 ? 10 + (i % 2) * 0.1 : 20)), law('2015-04-01'), [map(true)]);
    expect(up.cross).toMatch(/^段階1・上昇（参考：向きは決めない）/);
    expect(up.cross).not.toMatch(/貢献|悪影響/);
    const down = evaluateLaw(world(1990, i => (i < 25 ? 10 + (i % 2) * 0.1 : 1)), law('2015-04-01'), [map(true)]);
    expect(down.cross).toMatch(/^段階1・低下（参考/);
  });
  it('日本に開始前の値が1つもなければ、従来どおり「日本の開始前の値がない」', () => {
    const r = evaluateLaw(world(2020, () => 10), law('2015-04-01'), [map(false)]);
    expect(r.cross).toBe('保留');
    expect(r.reason).toContain('日本の開始前の値がない');
  });
  it('実際の対応表: 賃金と雇用の流動性は比較群なしのまま国際系列を持ち、電子申請率は系列なしのまま', () => {
    const wage = INDICATOR_MAP.find(m => m.indicator === '賃金')!;
    expect(wage).toMatchObject({ match: '比較群なし', target: null, intl: { rebase: true, better: 'higher' } });
    expect(wage.intl!.source!.where['区分']).toBe('実質（2025年価格）／米ドル（購買力平価）');
    const tenure = INDICATOR_MAP.find(m => m.indicator === '雇用の流動性')!;
    expect(tenure.intl!.source!.where['区分']).toBe('勤続1年未満／就業者全体／男女計');
    expect(INDICATOR_MAP.find(m => m.indicator === '電子申請率')!.match).toBe('系列なし');
    const npl = INDICATOR_MAP.find(m => m.indicator === '不良債権比率')!;
    expect(npl.intl!.altSources!.map(s => s.where['区分'])).toEqual(['WB:GFDD.SI.02']);
    const bb = INDICATOR_MAP.find(m => m.indicator === 'ブロードバンド普及率')!;
    expect(bb.intl!.code).toBe('WB:IT.NET.BBND.P2');
  });
});
