import { describe, expect, it } from 'vitest';
import { parseCsv, toCsv, type Tables } from './impact-batch';
import {
  LOSS_HEADER, LOSS_SOURCES, alignControls, buildLossInput, evaluateLosses, lossRow, lossWindow, observationGroups, qualifies, toLossLaw, type LossSource,
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

  it('系列の定義が変わる年を窓がまたげば、判定ルールを呼ばずに保留にする', () => {
    const built = buildLossInput(tables, law, [loanSource([{ year: 2018, evidence: '人工の断絶' }])])!;
    expect(built.blocked).toContain('2018年をまたぐ');
    const [row] = evaluateLosses(tables, [impactRow('L1', '人工の与信', '2015-04-01', '段階2', '悪影響')], [loanSource([{ year: 2018, evidence: '人工の断絶' }])]);
    expect(row.result).toBeNull();
    expect(lossRow(row)[LOSS_HEADER.indexOf('損失または便益の額')]).toBe('');
  });

  it('比較国の同じ定義の系列が無い分野は、比較国0か国として判定ルールに渡し、保留になる（0で埋めない）', () => {
    const [row] = evaluateLosses(tables, [impactRow('T1', '通信業の付加価値', '2015-04-01', '段階3', '貢献')], LOSS_SOURCES);
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
