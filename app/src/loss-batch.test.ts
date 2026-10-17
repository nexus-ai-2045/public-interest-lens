import { describe, expect, it } from 'vitest';
import { parseCsv, toCsv, type Tables } from './impact-batch';
import {
  EXPANSION_LOSS_SOURCES, LOSS_HEADER, LOSS_SOURCES, OECD_FILE, alignControls, buildLossInput, evaluateLosses, lossRow, lossWindow, observationGroups, qualifies, toLossLaw, listed, STAGE1_REFERENCE_REASON, type LossSource,
} from './loss-batch';

// すべて人工の表です。実在の統計ではありません。
const csv = (header: string, rows: (string | number)[][]) => parseCsv(toCsv(header.split(','), rows));
const impactRow = (id: string, indicator: string, start: string, verdict: string, direction: string) =>
  ({ id, 題名: `人工の法律${id}`, 分野: '人工', 指標: indicator, 施行日: start, 判定: verdict, 向き: direction });

// 比較国は毎年2%前後伸び、日本は2015年から横ばい（与信のGDP比の形の人工データ）。
const years = Array.from({ length: 16 }, (_, i) => 2010 + i);
const ratioRows = (country: string, f: (y: number) => number, last = 2025) => years.filter(y => y <= last).map(y => [country, y, f(y), `世界銀行 WDI X`]);
const tables: Tables = new Map([
  ['more-stats/wb.csv', csv('区分,年,値,備考', [
    ...ratioRows('JPN', y => 100 * 1.02 ** Math.min(y - 2010, 4)),
    ...ratioRows('AAA', y => 100 * 1.018 ** (y - 2010)),
    ...ratioRows('BBB', y => 100 * 1.02 ** (y - 2010)),
    ...ratioRows('CCC', y => 100 * 1.022 ** (y - 2010)),
    ...ratioRows('DDD', y => 100 * 1.02 ** (y - 2010), 2023),
  ])],
  ...['2015', '2011', '2005', '2000'].map(base => [`domestic-stats/sna_gdp_by_industry_${base}base.csv`, []] as [string, never[]]),
  ['domestic-stats/sna_gdp_by_industry_2020base.csv', csv('価格,経済活動,年,値', years.flatMap(y => [['名目', '合計', y, 500000], ['実質(連鎖方式)', '9.情報通信業', y, 100], ['名目', '9.情報通信業', y, 25000]]))],
]);
const loanSource = (breaks?: LossSource['breaks']): LossSource => ({
  indicator: '人工の与信', definition: '人工', sector: null, reference: true, note: '参考の注記',
  intl: { code: 'X', label: '人工の与信のGDP比', rebase: false, better: 'higher', source: { file: 'more-stats/wb.csv', countryColumn: '区分', where: { 備考: '世界銀行 WDI X' } } },
  gdp: [{ base: '2020', activity: '合計' }], breaks,
});

describe('対象の選び方', () => {
  it('impact.csv の段階2以上で向きのある行だけを対象にする（段階1・保留・系列なしは載せない）', () => {
    const rows = [impactRow('a', 'x', '2015-04-01', '段階3', '悪影響'), impactRow('b', 'x', '2015-04-01', '段階2', '貢献'), impactRow('c', 'x', '2015-04-01', '段階1', '貢献'), impactRow('d', 'x', '2015-04-01', '保留', '貢献'), impactRow('e', 'x', '2015-04-01', '系列なし', '')];
    expect(rows.map(toLossLaw).filter(qualifies).map(l => [l.id, l.stage, l.direction])).toEqual([['a', 3, 'harm'], ['b', 2, 'benefit']]);
  });

  it('参考として額を出す対象には、向きのある段階1も入る（向きの無い段階1・保留は入らない）', () => {
    const rows = [impactRow('a', 'x', '2015-04-01', '段階1', '貢献'), impactRow('b', 'x', '2015-04-01', '段階1', ''), impactRow('c', 'x', '2015-04-01', '保留', '貢献')];
    expect(rows.map(toLossLaw).filter(listed).map(l => l.id)).toEqual(['a']);
  });

  it('損失額の窓は開始年の5年前から開始後10年目（開始年が1年目）まで', () => {
    expect(lossWindow('2015-04-01')).toEqual({ from: 2010, to: 2024 });
  });
});

describe('比較国のそろえ方', () => {
  const pts = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => ({ asOf: `${from + i}-12-31`, value: 1 }));
  it('窓の年をすべて持つ国だけを使い、最新の年がそろわなければ開始後の年を短くする', () => {
    const r = alignControls(pts(2010, 2025), [{ country: 'A', points: pts(2010, 2025) }, { country: 'B', points: pts(2010, 2024) }, { country: 'C', points: pts(2010, 2024) }, { country: 'D', points: pts(2012, 2025) }], '2015-01-01');
    expect(r.treated.at(-1)!.asOf).toBe('2024-12-31');
    expect(r.controls.map(c => c.country)).toEqual(['A', 'B', 'C']);
  });
});

describe('1法律の入力と判定ルールの呼び出し', () => {
  const law = toLossLaw(impactRow('L1', '人工の与信', '2015-04-01', '段階2', '悪影響'));

  it('比較国が伸びて日本が横ばいなら損失額が出るが、規制の便益が未測定なので公開しない。参考の印が付く', () => {
    const [row] = evaluateLosses(tables, [impactRow('L1', '人工の与信', '2015-04-01', '段階2', '悪影響')], [loanSource()]);
    expect(row.result!.lossYen!.median).toBeGreaterThan(0);
    expect(row.result!.publishable).toBe(false);
    // 2025年は DDD に無いが、4か国の半数以上（3か国）がそろうので2025年まで使い、DDD を外す。
    expect(row.built!.input.controls.map(c => c.country)).toEqual(['AAA', 'BBB', 'CCC']);
    // 円への換算は、開始前最後の年（2014年）の与信のGDP比 × 名目GDP。
    expect(row.built!.input.baseNominalYen).toBeCloseTo(100 * 1.02 ** 4 / 100 * 500000 * 1e9, 0);
    const cells = lossRow(row);
    expect(cells).toHaveLength(LOSS_HEADER.length);
    expect(cells[LOSS_HEADER.indexOf('参考フラグ')]).toBe('参考');
    expect(cells[LOSS_HEADER.indexOf('損失または便益の額')]).toMatch(/^損失：中央値=\d+;第1四分位=\d+;第3四分位=\d+$/);
    expect(cells[LOSS_HEADER.indexOf('理由')]).toContain('新型コロナ');
  });

  it('段階1の行は、段階2以上と同じ方法・同じ入力で額が出るが、必ず参考の印が付き、公開には使わない', () => {
    const source = { ...loanSource(), reference: false };
    const stage2 = evaluateLosses(tables, [impactRow('L1', '人工の与信', '2015-04-01', '段階2', '悪影響')], [source])[0];
    const rows = [impactRow('L1', '人工の与信', '2015-04-01', '段階1', '悪影響')];
    const [row] = evaluateLosses(tables, rows, [source], { includeStage1: true });
    expect(row.result!.lossYen).toEqual(stage2.result!.lossYen);
    expect(row.built!.reference).toBe(true);
    expect(row.built!.stage1Reference).toBe(true);
    const cells = lossRow(row);
    expect(cells[LOSS_HEADER.indexOf('段階')]).toBe('段階1');
    expect(cells[LOSS_HEADER.indexOf('参考フラグ')]).toBe('参考');
    expect(cells[LOSS_HEADER.indexOf('理由')]).toMatch(/^参考（段階1）：/);
    expect(cells[LOSS_HEADER.indexOf('理由')]).toContain(STAGE1_REFERENCE_REASON);
    expect(cells[LOSS_HEADER.indexOf('損失または便益の額')]).toMatch(/^損失：/);
    // 段階2の行には参考の印が付かない。振り分けv1の出力（includeStage1 なし）には段階1を載せない。
    expect(lossRow(stage2)[LOSS_HEADER.indexOf('参考フラグ')]).toBe('');
    expect(evaluateLosses(tables, rows, [source])).toEqual([]);
  });

  it('対応の無い指標の段階1は、参考の印は付くが額は出ない（保留）', () => {
    const [row] = evaluateLosses(tables, [impactRow('Z', '対応なし', '2015-04-01', '段階1', '貢献')], [loanSource()], { includeStage1: true });
    const cells = lossRow(row);
    expect(cells[LOSS_HEADER.indexOf('損失または便益の額')]).toBe('');
    expect(cells[LOSS_HEADER.indexOf('参考フラグ')]).toBe('参考');
  });

  it('系列の定義が変わる年を窓がまたげば、判定ルールを呼ばずに保留にする', () => {
    const built = buildLossInput(tables, law, [loanSource([{ year: 2018, evidence: '人工の断絶' }])])!;
    expect(built.blocked).toContain('2018年をまたぐ');
    const [row] = evaluateLosses(tables, [impactRow('L1', '人工の与信', '2015-04-01', '段階2', '悪影響')], [loanSource([{ year: 2018, evidence: '人工の断絶' }])]);
    expect(row.result).toBeNull();
    expect(lossRow(row)[LOSS_HEADER.indexOf('損失または便益の額')]).toBe('');
  });

  it('比較国の同じ定義の系列が無い分野は、比較国0か国として判定ルールに渡し、保留になる（0で埋めない）', () => {
    const snaOnly: LossSource = { ...LOSS_SOURCES[0], oecd: undefined };
    const [row] = evaluateLosses(tables, [impactRow('T1', '通信業の付加価値', '2015-04-01', '段階3', '貢献')], [snaOnly]);
    expect(row.built!.input.controls).toEqual([]);
    expect(row.built!.input.baseNominalYen).toBe(25000 * 1e9);
    expect(row.result!.lossYen).toBeNull();
    expect(row.result!.reason).toContain('比較国が0か国');
  });

  it('対応の無い指標は入力を作らず、額も出さない', () => {
    const [row] = evaluateLosses(tables, [impactRow('Z', '対応なし', '2015-04-01', '段階2', '貢献')], [loanSource()]);
    expect(row.built).toBeNull();
    expect(lossRow(row)[LOSS_HEADER.indexOf('理由')]).toContain('対応がない');
  });
});

// OECD 表6の形の人工データ。LR は比較国が毎年2%前後伸び、日本は2014年から横ばい。L はわざと違う値にし、使われないことを確かめる。
const oecdYears = Array.from({ length: 26 }, (_, i) => 2000 + i);
const oecdRows = (country: string, industry: string, f: (y: number) => number, opts: { from?: number; to?: number } = {}) =>
  oecdYears.filter(y => y >= (opts.from ?? 2000) && y <= (opts.to ?? 2025)).flatMap(y => [
    [country, industry, '総付加価値（B1G）', 'LR', y, f(y), '百万X', 2020, 'https://example.invalid'],
    [country, industry, '総付加価値（B1G）', 'L', y, f(y) * (y % 2 ? 3 : 0.5), '百万X', 2015, 'https://example.invalid'],
    [country, industry, '総付加価値（B1G）', 'V', y, f(y) * 1.1, '百万X', '', 'https://example.invalid'],
  ]);
const grow = (r: number) => (y: number) => 1000 * r ** (y - 2000);
const oecdTables = (rows: (string | number)[][]): Tables => new Map([...tables, [OECD_FILE, csv('国,産業,指標,価格,年,値,単位,基準年,出典URL', rows)]]);
const jpFlat = (y: number) => 1000 * 1.02 ** (Math.min(y, 2013) - 2000);
const oecd = oecdTables([
  ...oecdRows('JPN', 'J', jpFlat), ...oecdRows('JPN', 'I', jpFlat),
  ...['AUS', 'FRA', 'ITA', 'KOR'].flatMap((c, i) => oecdRows(c, 'J', grow(1.018 + i * 0.002))),
  ...['AUS', 'FRA', 'ITA'].flatMap((c, i) => oecdRows(c, 'I', grow(1.018 + i * 0.002))),
  ...oecdRows('CAN', 'J', grow(1.02), { from: 2007 }),
]);

describe('OECD 表6の産業別付加価値で計算する分野', () => {
  it('日本も比較国も LR（2020年基準）で比べ、名目は日本の V（百万円）で換算する。L は使わない', () => {
    const [row] = evaluateLosses(oecd, [impactRow('T1', '通信業の付加価値', '2015-04-01', '段階3', '悪影響')]);
    const b = row.built!;
    expect(b.input.treated.find(p => p.asOf === '2012-12-31')!.value).toBeCloseTo(jpFlat(2012), 6);
    expect(b.input.baseNominalYen).toBeCloseTo(jpFlat(2014) * 1.1 * 1e6, 0);
    expect(b.input.controls.map(c => c.country)).toEqual(['AUS', 'CAN', 'FRA', 'ITA', 'KOR']);
    expect(b.input.controls[0].points.at(-1)!.value).toBeCloseTo(grow(1.018)(2024), 6);
    expect(row.result!.lossYen!.median).toBeGreaterThan(0);
    expect(row.result!.publishable).toBe(false);
    expect(lossRow(row)[LOSS_HEADER.indexOf('計算式の要素')]).toContain('AUS は年度');
  });

  it('窓が2010年をまたぐ法律では ITA を比較国から外す（またがなければ使う）', () => {
    const [crossing] = evaluateLosses(oecd, [impactRow('T2', '通信業の付加価値', '2014-04-01', '段階3', '悪影響')]);
    expect(crossing.built!.input.controls.map(c => c.country)).toEqual(['AUS', 'CAN', 'FRA', 'KOR']);
    expect(crossing.built!.elements.join('／')).toContain('除外：ITA');
    const [notCrossing] = evaluateLosses(oecd, [impactRow('T3', '通信業の付加価値', '2015-04-01', '段階3', '悪影響')]);
    expect(notCrossing.built!.input.controls.map(c => c.country)).toContain('ITA');
  });

  it('窓の年をすべて持たない国は使わない（CAN は2007年から）', () => {
    const [row] = evaluateLosses(oecd, [impactRow('T4', '通信業の付加価値', '2011-04-01', '段階3', '悪影響')]);
    expect(row.built!.input.controls.map(c => c.country)).toEqual(['AUS', 'FRA', 'KOR']);
  });

  it('宿泊・飲食（I）は系列の無い KOR を補わずに外し、3か国に足りなければ判定ルールが保留にする', () => {
    const [row] = evaluateLosses(oecd, [impactRow('S1', '宿泊者数', '2014-04-01', '段階3', '悪影響')]);
    // ITA は2010年をまたぐので外れ、KOR は系列が無いので AUS・FRA の2か国だけ。
    expect(row.built!.input.controls.map(c => c.country)).toEqual(['AUS', 'FRA']);
    expect(row.built!.elements.join('／')).toContain('KOR は宿泊・飲食（I）の系列が無い');
    expect(row.result!.lossYen).toBeNull();
    expect(row.result!.reason).toContain('比較国が2か国で、3か国に足りません');
    expect(lossRow(row)[LOSS_HEADER.indexOf('損失または便益の額')]).toBe('');
  });

  it('額の向きが影響段階の向きと逆なら、判定ルールのとおり保留にする', () => {
    const [row] = evaluateLosses(oecd, [impactRow('T5', '通信業の付加価値', '2015-04-01', '段階3', '貢献')]);
    expect(row.result!.lossYen).toBeNull();
    expect(row.result!.reason).toContain('一致しない');
  });
});

describe('field-expansion-v1 の新分野：OECD の節が未取得なら保留', () => {
  const stage1 = (indicator: string) => impactRow('N1', indicator, '2015-04-01', '段階1', '上昇');

  it('新分野の指標ごとに OECD の節と日本の経済活動が決まっている。代理の指標は参考、直接は参考でない', () => {
    expect(EXPANSION_LOSS_SOURCES).toHaveLength(14);
    for (const s of EXPANSION_LOSS_SOURCES) {
      expect(s.reference).toBe(s.indicator.endsWith('（代理）'));
      expect(s.oecd).toBeTruthy();
      expect(s.sector!.length).toBeGreaterThan(0);
      expect(LOSS_SOURCES).toContain(s);
    }
    const sections = Object.fromEntries(EXPANSION_LOSS_SOURCES.map(s => [s.indicator, (s.oecd!.parts ?? [s.oecd!.industry]).join('+')]));
    expect(sections).toMatchObject({
      '農林水産業の付加価値': 'A', '建設業の付加価値': 'F', '不動産業の付加価値（代理）': 'L', '教育の付加価値（代理）': 'P', '保健衛生・社会事業の付加価値（代理）': 'Q',
      '製造業の付加価値': 'C', '卸売・小売業の付加価値': 'G', '専門・科学技術、業務支援サービス業の付加価値': 'M+N', 'その他のサービス業の付加価値（代理）': 'R+S',
    });
  });

  it('節が industry_va.csv に無いときは、エラーにせず「国際比較の系列が未取得」で保留にする（今ある H・I・J・K・_T だけの表）', () => {
    const only = oecdTables([...oecdRows('JPN', 'J', jpFlat), ...oecdRows('AUS', 'J', grow(1.02))]);
    for (const indicator of ['建設業の付加価値', '教育の付加価値（代理）', '専門・科学技術、業務支援サービス業の付加価値']) {
      const [row] = evaluateLosses(only, [stage1(indicator)], undefined, { includeStage1: true });
      expect(row.result).toBeNull();
      expect(row.built!.blocked).toContain('国際比較の系列が未取得');
      const cells = lossRow(row);
      expect(cells[LOSS_HEADER.indexOf('理由')]).toContain('国際比較の系列が未取得');
      expect(cells[LOSS_HEADER.indexOf('損失または便益の額')]).toBe('');
    }
  });

  it('合算する節の片方だけ無いときも保留（M だけあって N が無い）', () => {
    const only = oecdTables([...oecdRows('JPN', 'M', jpFlat), ...oecdRows('AUS', 'M', grow(1.02))]);
    const [row] = evaluateLosses(only, [stage1('専門・科学技術、業務支援サービス業の付加価値')], undefined, { includeStage1: true });
    expect(row.built!.blocked).toContain('N');
    expect(row.result).toBeNull();
  });

  it('表そのものが無くても（OECD の CSV が空）止まらず保留', () => {
    const empty: Tables = new Map([...tables, [OECD_FILE, []]]);
    const [row] = evaluateLosses(empty, [stage1('農林水産業の付加価値')], undefined, { includeStage1: true });
    expect(row.built!.blocked).toContain('国際比較の系列が未取得');
  });

  it('節がそろえば計算し、代理は参考フラグ・向きは上昇／低下。M と N は足し合わせる', () => {
    const rows = [
      ...oecdRows('JPN', 'M', jpFlat), ...oecdRows('JPN', 'N', jpFlat),
      ...['AUS', 'FRA', 'KOR'].flatMap((c, i) => [...oecdRows(c, 'M', grow(1.018 + i * 0.002)), ...oecdRows(c, 'N', grow(1.018 + i * 0.002))]),
    ];
    const [row] = evaluateLosses(oecdTables(rows), [stage1('専門・科学技術、業務支援サービス業の付加価値（代理）')], undefined, { includeStage1: true });
    expect(row.built!.blocked).toBeUndefined();
    expect(row.built!.input.treated.find(p => p.asOf === '2012-12-31')!.value).toBeCloseTo(2 * jpFlat(2012), 6);
    expect(row.built!.input.controls.map(c => c.country)).toEqual(['AUS', 'FRA', 'KOR']);
    expect(row.built!.reference).toBe(true);
    const cells = lossRow(row);
    expect(cells[LOSS_HEADER.indexOf('参考フラグ')]).toBe('参考');
    expect(cells[LOSS_HEADER.indexOf('向き')]).toBe('上昇');
    expect(cells[LOSS_HEADER.indexOf('計算式の要素')]).toContain('M+N');
  });

  it('直接の指標は参考フラグを付けない（段階2以上なら通常扱い）', () => {
    const rows = [...oecdRows('JPN', 'F', jpFlat), ...['AUS', 'FRA', 'KOR'].flatMap((c, i) => oecdRows(c, 'F', grow(1.018 + i * 0.002)))];
    const [row] = evaluateLosses(oecdTables(rows), [impactRow('N2', '建設業の付加価値', '2015-04-01', '段階3', '悪影響')]);
    expect(row.built!.reference).toBe(false);
    expect(lossRow(row)[LOSS_HEADER.indexOf('参考フラグ')]).toBe('');
    expect(lossRow(row)[LOSS_HEADER.indexOf('向き')]).toBe('悪影響');
  });

  it('impact.csv の向きが上昇／低下の行は、額の向きの判定では貢献／悪影響と同じ側に読み、neutral を付ける', () => {
    expect(toLossLaw(impactRow('a', 'x', '2015-04-01', '段階1', '上昇'))).toMatchObject({ direction: 'benefit', neutral: true });
    expect(toLossLaw(impactRow('b', 'x', '2015-04-01', '段階1', '低下'))).toMatchObject({ direction: 'harm', neutral: true });
    expect(toLossLaw(impactRow('c', 'x', '2015-04-01', '段階3', '貢献')).neutral).toBeUndefined();
  });
});

describe('独立でない観測のまとまり', () => {
  it('同じ指標で窓が重なる法律は同じまとまり、離れていれば別、指標が違えば別', () => {
    const g = observationGroups([
      { id: 'a', indicator: 'X', start: '1999-03-01' }, { id: 'b', indicator: 'X', start: '2001-06-01' },
      { id: 'c', indicator: 'X', start: '2020-05-01' }, { id: 'd', indicator: 'Y', start: '2001-06-01' },
    ]);
    expect([g.get('a'), g.get('b'), g.get('c'), g.get('d')]).toEqual(['X-1', 'X-1', 'X-2', 'Y-1']);
  });
});

describe('人物を扱わない', () => {
  it('出力の列に人物・採決・役職の列がない', () => {
    expect(LOSS_HEADER.join(',')).not.toMatch(/議員|人物|氏名|採決|賛否|役職|person/i);
  });
});
