import { describe, expect, it } from 'vitest';
import { parseCsv, toCsv, type Tables } from './impact-batch';
import type { LossResult } from './loss-rule';
import {
  combineBenefits, cutAtCovid, decidePublication, includedBenefit, judgeCovidSeparation, LOWER_BOUND_LABEL, measureBenefit, netRange, overlapsCovid, sideLabel, SECURITY_KIND, stateLabel, unmeasuredBenefit, unmeasuredSign,
  type BenefitMeasurement, type BenefitSeriesInput, type CovidCheck, type PublishInput,
} from './benefit-rule';
import { classifyA, classifyLaw, pickPurposes, preprocessA } from './benefit-classification';
import { measureKind, type BenefitSource } from './benefit-batch';

// すべて人工のデータです。実在の統計・法律ではありません。
const pts = (from: number, values: number[]) => values.map((value, i) => ({ asOf: `${from + i}-12-31`, value }));
const series = (post: number[], unit: BenefitSeriesInput['unit'] = null, better: 'lower' | 'higher' = 'lower'): BenefitSeriesInput => ({
  kind: '消費者保護', series: '人工の相談件数 対 人工の全体', definition: '人工', start: '2015-04-01', better,
  treated: pts(2010, [100, 101, 99, 100, 100, ...post]), control: pts(2010, Array(5 + post.length).fill(100)), unit, maxYears: 3,
});

describe('便益の状態（measureBenefit は impact-rule-v1 をそのまま使う）', () => {
  it('開始前の観測が無ければ未測定（null）', () => {
    const m = measureBenefit({ ...series([80, 80, 80, 80, 80]), treated: pts(2015, [80, 80, 80, 80, 80]) });
    expect(m.state).toBe('未測定');
    expect(m.yen).toBeNull();
  });

  it('開始後の観測が足りなければ未測定', () => {
    expect(measureBenefit(series([80])).state).toBe('未測定');
  });

  it('測れたが差がばらつきの2倍を超えて続かなければ「検出されず」で便益0（既定1）。表示は「便益は検出されず」', () => {
    const m = measureBenefit(series([100, 101, 99, 100, 100]));
    expect(m.state).toBe('検出されず');
    expect(m.yen).toEqual({ low: 0, median: 0, high: 0 });
    expect(stateLabel(m.state)).toBe('便益は検出されず');
  });

  it('差が出ても公的な単価が無ければ「検出・未換算」で null（既定3）', () => {
    const m = measureBenefit(series([80, 80, 80, 80, 80]));
    expect(m.state).toBe('検出・未換算');
    expect(m.yen).toBeNull();
  });

  it('公的な単価があれば、反実仮想との差の件数×単価を maxYears 年分足す（20件×3年×1000円）', () => {
    const m = measureBenefit(series([80, 80, 80, 80, 80], { yen: 1000, source: '人工の平均既支払額' }));
    expect(m.state).toBe('円換算済み');
    expect(m.yen).toEqual({ low: 60000, median: 60000, high: 60000 });
  });

  it('指標が悪化していれば負の便益（損失が増える）', () => {
    const m = measureBenefit(series([120, 120, 120, 120, 120], { yen: 1000, source: '人工' }));
    expect(m.state).toBe('円換算済み');
    expect(m.yen!.median).toBe(-60000);
  });
});

describe('便益の合計と二重計上', () => {
  const measured = (kind: string, series: string, yen: number): BenefitMeasurement => ({ kind, series, state: '円換算済み', yen: { low: yen, median: yen, high: yen }, effect: 1, spread: 0, reason: '' });
  it('未測定・検出・未換算が1つでもあれば null', () => {
    expect(combineBenefits([includedBenefit('経済（内包）', ''), unmeasuredBenefit('環境', '')])).toBeNull();
  });
  it('同じ系列を指す2つの種類は1回だけ数える', () => {
    expect(combineBenefits([measured('消費者保護', '破産', 5), measured('金融の安定', '破産', 5), measured('安全（事故）', '事故', 2)])!.median).toBe(7);
  });
  it('純額の幅は向きが厳しい側で組む', () => {
    expect(netRange({ low: 10, median: 20, high: 30 }, { low: 1, median: 2, high: 3 })).toEqual({ low: 7, median: 18, high: 29 });
  });
});

const loss = (median: number, low = median * 0.8, high = median * 1.2, publishable = false): LossResult =>
  ({ ruleVersion: 'loss-rule-v1', lossYen: { low: Math.min(low, high), median, high: Math.max(low, high) }, years: 5, publishable, reason: '人工' });

describe('新型コロナの窓（既定2）', () => {
  const base = { window: { from: 2012, to: 2026 }, original: { stage: 3 as const, direction: 'harm' as const }, recomputed: { stage: 3 as const, direction: 'harm' as const }, originalLoss: loss(100), truncatedLoss: loss(40), postYearsAfterCut: 3 };
  it('窓が2020〜2022年と重ならなければ対象外', () => {
    expect(overlapsCovid(2000, 2014)).toBe(false);
    expect(judgeCovidSeparation({ ...base, window: { from: 2000, to: 2014 } }).applies).toBe(false);
  });
  it('2019年で切ると2023年以降もつながない', () => {
    expect(cutAtCovid(pts(2017, [1, 2, 3, 4, 5, 6, 7])).map(p => p.asOf.slice(0, 4))).toEqual(['2017', '2018', '2019']);
  });
  it('開始後が2年未満なら分離できない', () => {
    const c = judgeCovidSeparation({ ...base, postYearsAfterCut: 1 });
    expect([c.applies, c.separable]).toEqual([true, false]);
    expect(c.reason).toMatch(/コロナ期と分離できない/);
  });
  it('切った窓で段階か向きが変われば分離できない', () => {
    expect(judgeCovidSeparation({ ...base, recomputed: { stage: 1, direction: 'benefit' } }).separable).toBe(false);
    expect(judgeCovidSeparation({ ...base, recomputed: null }).separable).toBe(false);
  });
  it('切った窓で損失額の向きが変われば分離できない', () => {
    expect(judgeCovidSeparation({ ...base, truncatedLoss: loss(-5) }).separable).toBe(false);
  });
  it('すべて再現すれば分離できる', () => {
    expect(judgeCovidSeparation(base)).toMatchObject({ applies: true, separable: true });
  });
});

describe('公開の判定表 R1〜R6（上から順に、最初に当たった行）', () => {
  const noCovid: CovidCheck = { applies: false, separable: true, reason: '' };
  const ok: PublishInput = {
    reference: false, lossBlocked: null, originalLoss: loss(100), directionConflict: false, covid: noCovid,
    benefits: [includedBenefit('経済（内包）', '')], grossLoss: loss(100), finalLoss: loss(100, 80, 120, true),
  };
  it('R1：参考の行、loss-v1 の保留', () => {
    expect(decidePublication({ ...ok, reference: true }).row).toBe('R1');
    expect(decidePublication({ ...ok, lossBlocked: '系列の断絶' }).row).toBe('R1');
    expect(decidePublication({ ...ok, originalLoss: { ...loss(1), lossYen: null } }).row).toBe('R1');
  });
  it('R1：段階1の参考の行は、他がすべて満たされていても公開不可', () => {
    const d = decidePublication({ ...ok, reference: true, stage1Reference: true });
    expect(d).toMatchObject({ row: 'R1', publishable: false });
    expect(d.reason).toContain('段階1');
  });
  it('R2：向きの矛盾', () => {
    expect(decidePublication({ ...ok, directionConflict: true })).toMatchObject({ row: 'R2', publishable: false });
  });
  it('R3：新型コロナと分離できない', () => {
    expect(decidePublication({ ...ok, covid: { applies: true, separable: false, reason: 'コロナ期と分離できない：人工' } })).toMatchObject({ row: 'R3', publishable: false });
  });
  it('R4：便益に未測定か検出・未換算がある', () => {
    expect(decidePublication({ ...ok, benefits: [includedBenefit('経済（内包）', ''), unmeasuredBenefit('安全（犯罪）', '系列なし')] }).row).toBe('R4');
    expect(decidePublication({ ...ok, benefits: [{ ...unmeasuredBenefit('環境', ''), state: '検出・未換算' }] }).row).toBe('R4');
  });
  it('R5：純額の幅が0をまたぐ', () => {
    const b: BenefitMeasurement = { kind: '消費者保護', series: 's', state: '円換算済み', yen: { low: 90, median: 90, high: 90 }, effect: 1, spread: 0, reason: '' };
    const d = decidePublication({ ...ok, benefits: [b], finalLoss: loss(10, -10, 30, true) });
    expect(d.row).toBe('R5');
    expect(d.net).toEqual({ low: -10, median: 10, high: 30 });
  });
  it('R6：内包・検出されず・円換算済みだけで純額の向きが定まれば公開可（候補）', () => {
    const d = decidePublication({ ...ok, benefits: [includedBenefit('経済（内包）', ''), { ...includedBenefit('消費者保護', ''), state: '検出されず' }] });
    expect(d).toMatchObject({ row: 'R6', publishable: true });
    expect(d.reason).toMatch(/純損失.*便益は検出されず/);
  });
  it('R6 の純便益（損失額が負）', () => {
    expect(decidePublication({ ...ok, originalLoss: loss(-100), grossLoss: loss(-100), finalLoss: loss(-100, -80, -120, true) }).reason).toMatch(/純便益/);
  });
});

describe('v1.1 の R4：便益の側では、加算のみの未測定は止めず下限として出す', () => {
  const noCovid: CovidCheck = { applies: false, separable: true, reason: '' };
  // 便益の側：影響段階が貢献で、損失額が負（得た額）。
  const benefitSide: PublishInput = {
    reference: false, lossBlocked: null, originalLoss: loss(-100), directionConflict: false, covid: noCovid,
    benefits: [includedBenefit('経済（内包）', ''), unmeasuredBenefit('安全（犯罪）', '系列なし')],
    grossLoss: loss(-100), finalLoss: loss(-100, -80, -120, true), direction: 'benefit',
  };
  it('便益の側で、未測定が加算のみ（安全（犯罪））だけなら公開可。額は「下限（未測定の便益あり）」', () => {
    const d = decidePublication(benefitSide);
    expect(d).toMatchObject({ row: 'R6', publishable: true, lowerBound: true });
    expect(d.net).toEqual({ low: -120, median: -100, high: -80 });
    expect(d.reason).toContain(LOWER_BOUND_LABEL);
    expect(d.reason).toMatch(/純便益/);
  });
  it('加算のみの種類が改善の向きで検出・未換算なら、それも止めない', () => {
    const m = measureBenefit({ ...series([80, 80, 80, 80, 80]), kind: '安全（事故）' });
    expect([m.state, m.detected]).toEqual(['検出・未換算', 'benefit']);
    expect(unmeasuredSign(m).sign).toBe('加算のみ');
    expect(decidePublication({ ...benefitSide, benefits: [m] })).toMatchObject({ row: 'R6', lowerBound: true });
  });
  it('便益の側でも、符号が定まらない未測定（対応表外・海外所得）や費用を含む種類（消費者保護）があれば止める', () => {
    for (const kind of ['対応表外（安全保障）', '経済（付加価値の外）', '消費者保護', '金融の安定']) {
      const d = decidePublication({ ...benefitSide, benefits: [unmeasuredBenefit('安全（犯罪）', ''), unmeasuredBenefit(kind, '系列なし')] });
      expect(d).toMatchObject({ row: 'R4', publishable: false, lowerBound: false });
      expect(d.reason).toMatch(new RegExp(`便益を減らしうる未測定がある（${kind.replace(/[()（）]/g, '.')}`));
    }
    expect(unmeasuredSign(unmeasuredBenefit('目的の分類', '保留')).sign).toBe('減らしうる');
  });
  it('加算のみの種類でも、悪化の向きで検出されたものは止める', () => {
    const m = measureBenefit({ ...series([120, 120, 120, 120, 120]), kind: '安全（犯罪）' });
    expect([m.state, m.detected]).toEqual(['検出・未換算', 'harm']);
    expect(decidePublication({ ...benefitSide, benefits: [m] }).row).toBe('R4');
  });
  it('損失の側（悪影響）の法律は今までどおり：未測定があれば加算のみでも止める', () => {
    const lossSide: PublishInput = { ...benefitSide, originalLoss: loss(100), grossLoss: loss(100), finalLoss: loss(100, 80, 120, true), direction: 'harm' };
    expect(decidePublication(lossSide)).toMatchObject({ row: 'R4', publishable: false, lowerBound: false });
    expect(decidePublication({ ...lossSide, benefits: [unmeasuredBenefit('対応表外（安全保障）', '')] }).row).toBe('R4');
  });
  it('向きが無い（省略）か、貢献でも測った純額が損失の側なら止める', () => {
    expect(decidePublication({ ...benefitSide, direction: undefined }).row).toBe('R4');
    expect(decidePublication({ ...benefitSide, originalLoss: loss(100), grossLoss: loss(100) }).row).toBe('R4');
  });
  it('下限でも純額の幅が0をまたげば R5', () => {
    expect(decidePublication({ ...benefitSide, grossLoss: loss(-10, -30, 10) })).toMatchObject({ row: 'R5', publishable: false });
  });
  it('側の表示は法律の影響段階の向きから付ける', () => {
    expect([sideLabel('benefit'), sideLabel('harm'), sideLabel(null)]).toEqual(['国士側（貢献）', '国賊側（悪影響）', '保留（向きなし）']);
  });
});

describe('v1.2：安全保障の既定（便益の側だけ、第1条の原文で決める）', () => {
  const noCovid: CovidCheck = { applies: false, separable: true, reason: '' };
  const base: PublishInput = {
    reference: false, lossBlocked: null, originalLoss: loss(-100), directionConflict: false, covid: noCovid,
    benefits: [includedBenefit('経済（内包）', ''), unmeasuredBenefit('安全（犯罪）', ''), unmeasuredBenefit(SECURITY_KIND, '系列なし')],
    grossLoss: loss(-100), finalLoss: loss(-100, -80, -120, true), direction: 'benefit',
  };
  const sec = unmeasuredBenefit(SECURITY_KIND, '');
  it('便益の側で、原文に「安全保障」か「セキュリティ」があれば加算のみ', () => {
    expect(unmeasuredSign(sec, { direction: 'benefit', purposeText: '我が国の安全保障に資する' }).sign).toBe('加算のみ');
    expect(unmeasuredSign(sec, { direction: 'benefit', purposeText: 'サイバーセキュリティの確保' }).sign).toBe('加算のみ');
  });
  it('原文に語が無ければ、またはテキストが無ければ今までどおり減らしうる', () => {
    expect(unmeasuredSign(sec, { direction: 'benefit', purposeText: '国民経済の発展に資する' }).sign).toBe('減らしうる');
    expect(unmeasuredSign(sec, { direction: 'benefit' }).sign).toBe('減らしうる');
    expect(unmeasuredSign(sec).sign).toBe('減らしうる');
  });
  it('損失の側・向きなしでは適用しない', () => {
    for (const direction of ['harm', null] as const) expect(unmeasuredSign(sec, { direction, purposeText: '安全保障' }).sign).toBe('減らしうる');
  });
  it('未測定以外（検出・未換算）と、ほかの対応表外の種類には適用しない', () => {
    expect(unmeasuredSign({ ...sec, state: '検出・未換算', detected: 'benefit' }, { direction: 'benefit', purposeText: '安全保障' }).sign).toBe('減らしうる');
    expect(unmeasuredSign(unmeasuredBenefit('対応表外（福祉）', ''), { direction: 'benefit', purposeText: '安全保障' }).sign).toBe('減らしうる');
    expect(unmeasuredSign(unmeasuredBenefit('消費者保護', ''), { direction: 'benefit', purposeText: '安全保障' }).sign).toBe('減らしうる');
  });
  it('公開の判定：語があれば R6（下限）、無ければ R4', () => {
    expect(decidePublication({ ...base, purposeText: 'サイバーセキュリティ' })).toMatchObject({ row: 'R6', publishable: true, lowerBound: true });
    expect(decidePublication({ ...base, purposeText: '経済の発展' })).toMatchObject({ row: 'R4', publishable: false });
    expect(decidePublication({ ...base, direction: 'harm', originalLoss: loss(100), grossLoss: loss(100), purposeText: '安全保障' }).row).toBe('R4');
  });
  it('安全保障だけでなく、ほかの減らしうる未測定が残れば止める', () => {
    const d = decidePublication({ ...base, purposeText: '安全保障', benefits: [unmeasuredBenefit(SECURITY_KIND, ''), unmeasuredBenefit('消費者保護', '')] });
    expect(d.row).toBe('R4');
  });
});

describe('目的の分類（2系統）', () => {
  const row = (id: string, target: string, version: string, text: string, status = '取得') =>
    ({ id, 法令番号: '', 対象法令ID: target, 版: version, 第1条の原文: text, 出典URL: 'https://example.invalid/', 対象法令名: `人工法${target}`, 対象の関係: '', 版の法令改正履歴ID: '', 取得状況: status, 備考: '' });
  const purpose = '（目的）\n第一条　この法律は、消費者の利益の擁護を図り、もって国民経済の健全な発展に資することを目的とする。';

  it('系統Aは他の法律の題名の引用と「公共の福祉」を除いてから語を当てる', () => {
    expect(preprocessA('（目的）\n第一条　利息制限法（昭和二十九年法律第百号）の特例を定め、公共の福祉を増進する')).not.toMatch(/利息制限法|福祉/);
    expect(classifyA([{ targetId: 'x', lawName: '人工', version: '現行', text: purpose, url: '' }], '人工').kinds).toEqual(['消費者保護', '経済（内包）']);
  });

  it('施行時の版が無ければ現行の版を使って印を付け、目的規定でない第1条にも印を付ける', () => {
    const r = pickPurposes([row('L', 'T1', '施行時', '', '取得できず'), row('L', 'T1', '現行', '（出資金の受入の制限）\n第一条　何人も…してはならない。')], 'L', '人工法の一部を改正する法律及び人工法二の一部を改正する法律案');
    expect(r.texts[0].version).toBe('現行');
    expect(r.flags.join()).toMatch(/施行時の版が無いため現行/);
    expect(r.flags.join()).toMatch(/目的規定でない/);
    expect(r.flags.join()).toMatch(/改正対象2本のうち、第1条があるのは1本/);
  });

  it('2系統が一致すればその種類、一致しなければ保留', () => {
    const rows = [row('L', 'T1', '施行時', purpose)];
    const law = { id: 'L', title: '人工法案', indicator: '人工' };
    const agree = classifyLaw(rows, law, { L: { kinds: ['経済（内包）', '消費者保護'], quotes: [], directionConflict: false, note: '' } });
    expect([agree.agreed, agree.kinds, agree.holdReason]).toEqual([true, ['消費者保護', '経済（内包）'], null]);
    const differ = classifyLaw(rows, law, { L: { kinds: ['経済（内包）'], quotes: [], directionConflict: false, note: '' } });
    expect([differ.agreed, differ.kinds]).toEqual([false, null]);
    expect(differ.holdReason).toMatch(/一致しない/);
  });

  it('第1条が無い、または目的の記述が無ければ保留', () => {
    const law = { id: 'L', title: '人工法案', indicator: '人工' };
    expect(classifyLaw([], law, {}).holdReason).toBe('第1条の原文が無い');
    const empty = classifyLaw([row('L', 'T1', '施行時', '（目的）\n第一条　この法律は、機構の名称等を定めることを目的とする。')], law, { L: { kinds: [], quotes: [], directionConflict: false, note: '' } });
    expect(empty.holdReason).toMatch(/目的の記述が無い/);
  });

  it('向きの矛盾は貸出残高の指標で、2系統が一致したときだけ付く', () => {
    const rows = [row('L', 'T1', '施行時', '（貸付けの制限）\n第一条　何人も、消費者に…貸し付けてはならない。')];
    const law = { id: 'L', title: '人工法案', indicator: '貸出残高' };
    expect(classifyLaw(rows, law, { L: { kinds: ['消費者保護'], quotes: [], directionConflict: true, note: '' } }).directionConflict).toBe(true);
    expect(classifyLaw(rows, law, { L: { kinds: ['消費者保護'], quotes: [], directionConflict: false, note: '' } }).holdReason).toMatch(/向きの矛盾/);
  });
});

describe('種類ごとの測定（measureKind）', () => {
  const csv = (header: string, rows: (string | number)[][]) => parseCsv(toCsv(header.split(','), rows));
  const years = Array.from({ length: 10 }, (_, i) => 2010 + i);
  const tables: Tables = new Map([
    ['x/counts.csv', csv('系列,区分,年,値', years.flatMap(y => [['件数', '対象', y, y < 2015 ? 100 + (y % 2) : 80], ['件数', '比較', y, 100]]))],
    ['x/unit.csv', csv('系列,区分,年,値', years.map(y => ['単価', '全体', y, 1000]))],
  ]);
  const sources: Record<string, BenefitSource> = {
    '消費者保護': { options: [{ name: '人工の件数', definition: '人工', better: 'lower', treated: { file: 'x/counts.csv', where: { 区分: '対象' } }, control: { file: 'x/counts.csv', where: { 区分: '比較' } }, unit: { ref: { file: 'x/unit.csv', where: { 区分: '全体' } }, source: '人工の単価' } }], missing: '' },
    '環境': { options: [], missing: '人工：未取得' },
  };
  it('経済（内包）と移転は測らず0', () => {
    expect(measureKind(tables, '経済（内包）', '2015-04-01', false, 5, sources).state).toBe('内包');
    expect(measureKind(tables, '移転', '2015-04-01', false, 5, sources).yen).toEqual({ low: 0, median: 0, high: 0 });
  });
  it('系列の無い種類と対応表に無い種類は未測定で、足りない出典を書く', () => {
    expect(measureKind(tables, '環境', '2015-04-01', false, 5, sources)).toMatchObject({ state: '未測定', reason: expect.stringMatching(/人工：未取得/) });
    expect(measureKind(tables, '対応表外（人工）', '2015-04-01', false, 5, sources).state).toBe('未測定');
  });
  it('系列と公的な単価があれば円換算済み。新型コロナの規則で切ると年数が減る', () => {
    const full = measureKind(tables, '消費者保護', '2015-04-01', false, 5, sources);
    expect(full.state).toBe('円換算済み');
    expect(full.yen!.median).toBeGreaterThan(0);
    const cut = measureKind(tables, '消費者保護', '2018-04-01', true, 5, sources);
    expect(cut.state).toBe('未測定');
  });
});
