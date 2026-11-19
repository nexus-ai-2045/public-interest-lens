// @ts-nocheck
// @vitest-environment node
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { parseCsv } from './impact-batch';
import { buildExposureInputs, withLedgerPeople, type ExposureSources } from './exposure-inputs';
import { buildExposureRanking, DEFAULT_ROLE_RATIO, type ExposureRanking, type Involvement } from './exposure-ranking';
import { SCORING_CONSTANTS } from './scoring-constants';

const csv = (head: string[], rows: Record<string, string>[]) =>
  [head.join(','), ...rows.map(r => head.map(h => r[h] ?? '').join(','))].join('\n') + '\n';

const MACRO_HEAD = ['id', '題名', '分野', '分野の由来', '産業', '施行日', '施行日の由来', '窓', '中央値', '第1四分位', '第3四分位', '比較国', '計算式の要素', '結果', '理由'];
const macroRow = (id: string, 産業: string, 窓 = '1998〜2000年', 結果 = '額') => ({ id, 題名: 'テスト', 産業, 窓, 結果 });
const IY_HEAD = ['産業', '年', 'low', 'median', 'high', '比較国', '前年の名目付加価値_百万円'];
const iy = (産業: string, 年: number, median = 100, low = 50, high = 300) => ({ 産業, 年: String(年), low: String(low), median: String(median), high: String(high), 比較国: 'AUS・FRA・KOR', '前年の名目付加価値_百万円': '1000' });
const ENACTED_HEAD = ['回次', '種別', '提出回次', '番号', '題名', '提出者', '付託日_衆', '議決日_参', '賛成会派_衆', '反対会派_衆'];
const CAB_HEAD = ['内閣名', '区分', '氏名', '役職', '就任日_西暦', '退任日_西暦'];
const cab = (氏名: string, 役職: string, from: string, to = '', 区分 = '閣僚') => ({ 内閣名: 'テスト内閣', 区分, 氏名, 役職, 就任日_西暦: from, 退任日_西暦: to });
const INV_HEAD = ['法律ID', '氏名', '行動', '算入', '人物ID'];
const inv = (法律ID: string, 行動: string, 人物ID: string, 算入 = 'はい') => ({ 法律ID, 氏名: '氏名', 行動, 算入, 人物ID });
const VOTES_HEAD = ['投票ID', '回次', '投票日', '議案名', '集計_賛成', '集計_反対'];
const MEMBER_HEAD = ['議員ID', '回次', '議員名', '会派'];
const BALLOT_HEAD = ['投票ID', '議員ID', '賛否'];

// 回次2（1998年）は総理大臣が同じ。回次3（2000年）は会期の途中で総理大臣が替わる。
const enacted = csv(ENACTED_HEAD, [
  { 回次: '2', 種別: '閣法', 提出回次: '2', 番号: '1', 付託日_衆: '平成10年 1月10日' },
  { 回次: '2', 種別: '閣法', 提出回次: '2', 番号: '2', 付託日_衆: '平成10年 3月10日' },
  { 回次: '3', 種別: '閣法', 提出回次: '3', 番号: '1', 付託日_衆: '平成12年 1月10日' },
  { 回次: '3', 種別: '閣法', 提出回次: '3', 番号: '2', 付託日_衆: '平成12年 5月10日' },
  { 回次: '1', 種別: '衆法', 提出回次: '1', 番号: '1', 題名: 'テスト一号法案', 議決日_参: '平成10年 3月10日', 賛成会派_衆: '会派甲; 会派乙', 反対会派_衆: '会派丙' },
  { 回次: '1', 種別: '衆法', 提出回次: '1', 番号: '2', 題名: 'テスト二号法案', 議決日_参: '平成10年 3月10日' },
]);
const cabinet = csv(CAB_HEAD, [
  cab('首相 一', '内閣総理大臣', '1995-01-01', '2000-03-01'),
  cab('首相 二', '内閣総理大臣', '2000-03-01'),
  cab('大臣 甲', '法務大臣', '1995-01-01'),
  cab('大臣 乙', '外務大臣', '1995-01-01'),
  cab('大臣 途中', '財務大臣', '1998-02-01'),
  cab('副長 官', '内閣官房副長官', '1995-01-01'),
]);
const cabinetWithUnresolved = csv(CAB_HEAD, [...parseCsv(cabinet).map(r => r), cab('山田 花子', '文部大臣', '1995-01-01')].map(r => ({ ...r })));
// 「山田花子」は台帳に同姓同名が2人いて結べない。
const persons = csv(['人物ID', '氏名', '読み', '院', '選挙区', '別表記'], [
  { 人物ID: '山田花子（衆・東京1）', 氏名: '山田花子', 院: '衆議院', 選挙区: '東京1' },
  { 人物ID: '山田花子（参・比例）', 氏名: '山田花子', 院: '参議院', 選挙区: '比例' },
]);
const votesIndex = csv(VOTES_HEAD, [
  { 投票ID: 'v1', 回次: '1', 投票日: '1998-03-10', 議案名: '日程第１ テスト一号法案', 集計_賛成: '3', 集計_反対: '1' },
  { 投票ID: 'v9', 回次: '1', 投票日: '1998-03-10', 議案名: '日程第２ 別の法案', 集計_賛成: '3', 集計_反対: '1' },
]);
const sangiinMembers = csv(MEMBER_HEAD, [
  { 議員ID: '1', 回次: '1', 議員名: '議員 一', 会派: 'X' }, { 議員ID: '2', 回次: '1', 議員名: '議員 二', 会派: 'X' },
  { 議員ID: '3', 回次: '1', 議員名: '議員 三', 会派: 'X' }, { 議員ID: '4', 回次: '1', 議員名: '山田花子', 会派: 'X' },
  { 議員ID: '5', 回次: '1', 議員名: '議員 五', 会派: 'X' },
]);
// 議員1・2・4（山田花子＝台帳に結べない）が賛成、3が反対、5は棄権（A）。
const ballots = [csv(BALLOT_HEAD, [
  { 投票ID: 'v1', 議員ID: '1', 賛否: 'Y' }, { 投票ID: 'v1', 議員ID: '2', 賛否: 'Y' }, { 投票ID: 'v1', 議員ID: '4', 賛否: 'Y' },
  { 投票ID: 'v1', 議員ID: '3', 賛否: 'N' }, { 投票ID: 'v1', 議員ID: '5', 賛否: 'A' },
])];
const base = (over: Partial<ExposureSources> = {}): ExposureSources => ({
  macro: csv(MACRO_HEAD, [
    macroRow('衆法-1-1', 'A'), macroRow('衆法-1-2', 'A'),
    macroRow('閣法-2-1', 'B'), macroRow('閣法-2-2', 'B'),
    macroRow('閣法-3-1', 'C'),
    macroRow('閣法-2-9', 'COVID'), macroRow('閣法-2-8', 'B', '', '理由'),
  ]),
  // A は 2000 年の行が無い（群を作れない）。
  industryYear: csv(IY_HEAD, [iy('A', 1998), iy('A', 1999, 200), iy('B', 1998, 1000, 900, 1100), iy('B', 1999, 1000, 900, 1100), iy('B', 2000, 1000, 900, 1100), iy('C', 1998), iy('C', 1999), iy('C', 2000), iy('_T', 1998), iy('_T', 1999), iy('_T', 2000)]),
  enacted, cabinet, persons, roster: '',
  involvements: [csv(INV_HEAD, [])], votesIndex, sangiinMembers, ballots, ...over,
});
const sortedKeys = (xs: Involvement[]) => xs.map(x => `${x.lawId}|${x.role}|${x.house ?? ''}|${x.actorId}`).sort();
const params = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 1 };
const rankOf = (b: { groups; involvements }) => buildExposureRanking(b.groups, b.involvements, params);

describe('曝露ランキングの入力（群＝産業×年）', () => {
  it('窓を年に展開し、産業×年の群にする。額・比較国・年を industry-year.csv から写す', () => {
    const { industry, wholeEconomy, counts } = buildExposureInputs(base());
    expect(industry.groups.map(g => g.id)).toEqual(['A|1998', 'A|1999', 'B|1998', 'B|1999', 'B|2000', 'C|1998', 'C|1999', 'C|2000']);
    const a = industry.groups[1];
    expect(a).toMatchObject({ kind: 'group-diff', group: 'A', window: '1999年', lawCount: 2, diff: { low: 50, median: 200, high: 300 } });
    expect(a.benchmark).toContain('AUS・FRA・KOR');
    expect(a.benchmark).toContain('その年の実質の伸びの差×前年の名目付加価値');
    expect(industry.groups.every(g => g.id.split('|')[0] !== '_T')).toBe(true);
    // 法律が無いので全産業の群は作らない。
    expect(wholeEconomy.groups).toEqual([]);
    // A の 2000 年は industry-year.csv に行が無いので群を作らず、数える。
    expect(counts).toMatchObject({ groups: 8, groupsWithoutGap: 1, laws: 5 });
  });

  it('全産業（_T）は別欄の群にする（産業別に入れない）', () => {
    const out = buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', '_T'), macroRow('衆法-1-2', '_T'), macroRow('衆法-1-3', 'A', '1998〜1998年')]) }));
    expect(out.wholeEconomy.groups.map(g => g.id)).toEqual(['_T|1998', '_T|1999', '_T|2000']);
    expect(out.industry.groups.map(g => g.id)).toEqual(['A|1998']);
    expect(out.counts).toMatchObject({ groups: 1, wholeEconomyGroups: 3 });
  });

  it('同じ法律の窓が複数の行に分かれていても、覆う年は同じ（窓の分け方で変わらない）', () => {
    const one = buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'B', '1998〜2000年'), macroRow('衆法-1-2', 'B')]) }));
    const split = buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'B', '1998〜1999年'), macroRow('衆法-1-1', 'B', '2000〜2000年'), macroRow('衆法-1-2', 'B')]) }));
    expect(JSON.stringify(split.industry.groups)).toBe(JSON.stringify(one.industry.groups));
    expect(JSON.stringify(split.industry.involvements)).toBe(JSON.stringify(one.industry.involvements));
    const a = rankOf(one.industry), b = rankOf(split.industry);
    expect(JSON.stringify(b.totals)).toBe(JSON.stringify(a.totals));
  });

  it('窓が違う法律は、覆う年ごとに lawCount を数える', () => {
    const out = buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'B', '1998〜1999年'), macroRow('衆法-1-2', 'B', '1999〜2000年')]) }));
    expect(out.industry.groups.map(g => [g.id, g.lawCount])).toEqual([['B|1998', 1], ['B|1999', 2], ['B|2000', 1]]);
  });

  it('同じ法律が別の産業にある、窓の形が不正、額の幅が不正、産業×年が重複するときは止める', () => {
    const b = (rows) => base({ macro: csv(MACRO_HEAD, rows) });
    expect(() => buildExposureInputs(b([macroRow('衆法-1-1', 'A'), macroRow('衆法-1-1', 'B')]))).toThrow('別の産業');
    expect(() => buildExposureInputs(b([macroRow('衆法-1-1', 'A', '1998年')]))).toThrow('窓の形');
    expect(() => buildExposureInputs(base({ industryYear: csv(IY_HEAD, [iy('A', 1998, 100, 200, 300)]) }))).toThrow('low≤median≤high');
    expect(() => buildExposureInputs(base({ industryYear: csv(IY_HEAD, [iy('A', 1998), iy('A', 1998)]) }))).toThrow('重複');
  });

  it('産業別の合計（totals.expected）に _T の額が入らない', () => {
    const out = buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', '_T'), macroRow('衆法-1-2', '_T'), macroRow('衆法-1-3', 'B'), macroRow('衆法-1-4', 'B')]) }));
    const ind = rankOf(out.industry), whole = rankOf(out.wholeEconomy);
    // B の3年（各1000）だけ。比率の符号つき合計0.6。
    expect(ind.totals.expected.median).toBeCloseTo(3 * 1000 * 0.6);
    expect(whole.totals.expected.median).toBeCloseTo(3 * 100 * 0.6);
  });
});

describe('曝露ランキングの入力（関与）', () => {
  const run = (invs: Record<string, string>[], second: Record<string, string>[] = [], over: Partial<ExposureSources> = {}) =>
    buildExposureInputs(base({ involvements: [csv(INV_HEAD, invs), csv(INV_HEAD, second)], ...over }));
  const nonCabinet = (xs: Involvement[]) => xs.filter(x => !x.lawId.startsWith('閣法'));
  const nonVotes = (xs: Involvement[]) => nonCabinet(xs).filter(x => x.role === 'proposer');

  it('衆法・参法の decide は proposer。法律×年ごとに置く（年の数だけ）', () => {
    const out = run([inv('衆法-1-1', 'decide', '提出者')]);
    expect(nonVotes(out.industry.involvements)).toEqual([
      { actorKind: 'person', actorId: '提出者', groupId: 'A|1998', lawId: '衆法-1-1', role: 'proposer', weight: 1 },
      { actorKind: 'person', actorId: '提出者', groupId: 'A|1999', lawId: '衆法-1-1', role: 'proposer', weight: 1 },
    ]);
    expect(out.counts.proposerRows).toBe(1);
  });

  it('involvements の vote 行は使わない（投票の一次資料と二重に置かない）。算入=はい でない行・人物ID が空の行・使わない行動は数える', () => {
    const out = run([
      inv('衆法-1-1', 'vote', '票だけの人'), inv('衆法-1-1', 'decide', '甲', 'いいえ'), inv('衆法-1-1', 'decide', ''),
      inv('衆法-1-1', 'chair', '乙'), inv('衆法-1-1', 'amend', '乙'), inv('衆法-1-1', 'question', '乙'), inv('衆法-1-1', 'その他', '乙'),
      inv('閣法-2-1', 'decide', '閣法の提出者'),
      inv('衆法-99-9', 'decide', '群に無い法律'),
    ]);
    const all = [...out.industry.involvements, ...out.wholeEconomy.involvements];
    expect(all.some(x => ['票だけの人', '甲', '乙', '閣法の提出者', '群に無い法律'].includes(x.actorId))).toBe(false);
    expect(out.counts.skipped).toEqual({ notInGroup: 1, notCounted: 1, cabinetDecide: 1, voteRowIgnored: 1, chair: 1, amend: 1, question: 1, otherAction: 1, noPersonId: 1, committeeProposer: 0, singleLawGroup: 0, duplicates: 0 });
  });

  it('同じ（法律・役割・配り先）の重複は1つにする（2つのファイルにまたがっても。年ごとには増やさない）', () => {
    const out = run([inv('衆法-1-1', 'decide', '甲'), inv('衆法-1-1', 'decide', '甲')], [inv('衆法-1-1', 'decide', '甲')]);
    expect(nonVotes(out.industry.involvements).filter(x => x.actorId === '甲')).toHaveLength(2); // A|1998 と A|1999
    expect(out.counts.proposerRows).toBe(1);
    expect(out.counts.skipped.duplicates).toBe(2);
  });

  it('参議院は投票の個人票：Y は yes、N は no、A（棄権）は置かない。同姓同名で結べない人は配り先なしで置く', () => {
    const out = run([]);
    const l1 = out.industry.involvements.filter(x => x.lawId === '衆法-1-1' && x.groupId === 'A|1998' && x.house === 'upper');
    expect(sortedKeys(l1)).toEqual(['衆法-1-1|no|upper|議員三', '衆法-1-1|yes|upper|議員一', '衆法-1-1|yes|upper|議員二', '衆法-1-1|yes|upper|'].sort());
    expect(l1.find(x => x.actorKind === 'none')).toMatchObject({ role: 'yes', actorId: '', weight: 1 });
    expect(l1.every(x => x.weight === 1)).toBe(true);
    expect(out.counts).toMatchObject({ votesLaws: 2, votesMatched: 1, votesNotFound: 1, yesRows: 3, noRows: 1, unresolvedVoteRows: 1 });
  });

  it('衆議院は賛成会派・反対会派を会派（party）に、weight 1 で、記録の表記のまま置く', () => {
    const out = run([]);
    const lower = out.industry.involvements.filter(x => x.lawId === '衆法-1-1' && x.groupId === 'A|1998' && x.house === 'lower');
    expect(sortedKeys(lower)).toEqual(['衆法-1-1|no|lower|会派丙', '衆法-1-1|yes|lower|会派乙', '衆法-1-1|yes|lower|会派甲']);
    expect(lower.every(x => x.actorKind === 'party' && x.weight === 1)).toBe(true);
    expect(out.counts).toMatchObject({ lowerYesLaws: 1, lowerNoLaws: 1, lowerYesRows: 2, lowerNoRows: 1 });
  });

  it('賛成・反対の関与には院が必ず付く／同じ法律・役割・院の枠は人と会派に混ざらない', () => {
    const out = run([]);
    const by = new Map<string, Set<string>>();
    for (const x of out.industry.involvements) {
      if (x.role !== 'yes' && x.role !== 'no') continue;
      expect(['lower', 'upper']).toContain(x.house);
      const k = `${x.lawId}|${x.role}|${x.house}`;
      by.set(k, (by.get(k) ?? new Set()).add(x.actorKind === 'party' ? 'party' : 'individual'));
    }
    expect(by.size).toBeGreaterThan(0);
    for (const v of by.values()) expect(v.size).toBe(1);
  });

  it('参議院の個人票が決まらない法律（衆法-1-2）は参議院の枠が未配分のまま。衆議院の賛否が無い法律では参議院の人の額が増えない', () => {
    const out = run([]);
    const r = rankOf(out.industry);
    expect(out.industry.involvements.some(x => x.lawId === '衆法-1-2' && (x.role === 'yes' || x.role === 'no'))).toBe(false);
    expect(r.unallocated.some(u => u.reason === '参議院の賛否の記録が無い法律の枠')).toBe(true);
    // 衆議院の記録を消しても、参議院の人の額は変わらず、消えた半分は未配分に積まれる。
    const noLower = buildExposureInputs(base({ enacted: enacted.replace('会派甲; 会派乙', '').replace('会派丙', '') }));
    const r2 = rankOf(noLower.industry);
    for (const p of r.people) expect(r2.people.find(q => q.actorId === p.actorId)!.exposureYen.median).toBeCloseTo(p.exposureYen.median, 6);
    expect(r2.totals.people.median).toBeCloseTo(r.totals.people.median, 6);
    // （賛成の枠と反対の枠は符号が逆なので、額の合計は打ち消し合う。本数で比べる。）
    const lowerMissing = (x) => x.unallocated.filter(u => u.reason === '衆議院の賛否の記録が無い法律の枠').reduce((n, u) => n + u.laws, 0);
    expect(lowerMissing(r2)).toBeGreaterThan(lowerMissing(r));
    expect(r2.totals.people.median + r2.totals.parties.median + r2.totals.unallocated.median).toBeCloseTo(r2.totals.expected.median, 3);
  });

  it('閣法は、提出した回次の最初から最後まで在任した閣僚全員に cabinet と proposer を置く（記録の有無に依らない）', () => {
    const out = run([]);
    const l1 = out.industry.involvements.filter(x => x.lawId === '閣法-2-1' && x.groupId === 'B|1998');
    expect(sortedKeys(l1)).toEqual([
      '閣法-2-1|cabinet||大臣甲', '閣法-2-1|cabinet||大臣乙', '閣法-2-1|cabinet||首相一',
      '閣法-2-1|proposer||大臣甲', '閣法-2-1|proposer||大臣乙', '閣法-2-1|proposer||首相一',
    ].sort());
    expect(out.industry.involvements.filter(x => x.lawId === '閣法-2-1').length).toBe(6 * 3); // B は 3 年
    expect(out.counts).toMatchObject({ cabinetLaws: 3, cabinetLawsUndetermined: 1, cabinetLawsUnresolved: 0, cabinetUnresolvedMinisters: 0, cabinetRows: 6 });
  });

  it('閣僚の1人でも台帳に結べない閣法には cabinet と proposer を置かない（ほかの閣僚へ寄せない）', () => {
    const out = buildExposureInputs(base({ cabinet: cabinetWithUnresolved }));
    expect(out.industry.involvements.filter(x => x.lawId.startsWith('閣法'))).toEqual([]);
    expect(out.counts).toMatchObject({ cabinetLawsUnresolved: 2, cabinetUnresolvedMinisters: 2, cabinetRows: 0 });
  });

  it('法律が1本だけの産業×年の群には関与を置かない／委員会提出の法律には proposer を置かない', () => {
    const one = buildExposureInputs(base({
      macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'A', '1998〜1998年'), macroRow('衆法-1-2', 'B', '1998〜1998年'), macroRow('衆法-1-3', 'B', '1998〜1998年')]),
      enacted: csv(ENACTED_HEAD, [{ 回次: '1', 種別: '衆法', 提出回次: '1', 番号: '2', 提出者: '内閣委員長' }, { 回次: '1', 種別: '衆法', 提出回次: '1', 番号: '3', 提出者: '甲 太郎君外二名' }]),
      involvements: [csv(INV_HEAD, [inv('衆法-1-1', 'decide', '甲'), inv('衆法-1-2', 'decide', '乙'), inv('衆法-1-3', 'decide', '丙')])],
    }));
    expect(sortedKeys(one.industry.involvements)).toEqual(['衆法-1-3|proposer||丙']);
    expect(one.counts.singleLawGroups).toBe(1);
    expect(one.counts.skipped).toMatchObject({ singleLawGroup: 1, committeeProposer: 1 });
  });

  it('総理大臣が会期中に替わる回次の閣法には関与を置かず、数える', () => {
    const out = run([]);
    expect(out.industry.involvements.some(x => x.lawId === '閣法-3-1')).toBe(false);
    expect(out.counts.cabinetLawsUndetermined).toBe(1);
  });

  it('ある閣法の窓を2つに分けた入力でも、合計とその法律だけに関与する人の額が変わらない', () => {
    const rows = (windows: string[]) => csv(MACRO_HEAD, [...windows.map(w => macroRow('閣法-2-1', 'B', w)), macroRow('閣法-2-2', 'B')]);
    const a = buildExposureInputs(base({ macro: rows(['1998〜2000年']) }));
    const b = buildExposureInputs(base({ macro: rows(['1998〜1999年', '2000〜2000年']) }));
    const ra = rankOf(a.industry), rb = rankOf(b.industry);
    for (const k of ['low', 'median', 'high']) expect(rb.totals.expected[k]).toBeCloseTo(ra.totals.expected[k], 6);
    expect(ra.people.length).toBeGreaterThan(0);
    for (const p of ra.people) for (const k of ['low', 'median', 'high']) expect(rb.people.find(q => q.actorId === p.actorId)!.exposureYen[k]).toBeCloseTo(p.exposureYen[k], 6);
  });

  it('集計器に通すと検算が合う（記録の無い法律の枠は未配分）', () => {
    const out = run([inv('衆法-1-1', 'decide', '甲')]);
    for (const b of [out.industry, out.wholeEconomy]) {
      const t = rankOf(b).totals;
      for (const k of ['low', 'median', 'high']) expect(t.people[k] + t.parties[k] + t.unallocated[k]).toBeCloseTo(t.expected[k], 3);
    }
  });

  it('配り先なしの票の分は未配分に積まれる（理由つき）', () => {
    const r = rankOf(run([]).industry);
    const u = r.unallocated.find(x => x.reason === '同姓同名で人物台帳に結べない票');
    expect(u).toBeTruthy();
    expect(u.house).toBe('upper');
  });
});

describe('withLedgerPeople', () => {
  it('全産業の別欄にだけ関与がある人は、理由を「産業別の群への関与の記録が無い（全産業の別欄にある）」にする', () => {
    const personsCsv = csv(['人物ID', '氏名', '読み', '院', '選挙区', '別表記'], [
      { 人物ID: '甲', 氏名: '甲', 院: '衆議院' }, { 人物ID: '乙', 氏名: '乙', 院: '衆議院' }, { 人物ID: '丙', 氏名: '丙', 院: '衆議院' },
    ]);
    const out = buildExposureInputs(base({
      macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', '_T'), macroRow('衆法-1-2', '_T'), macroRow('衆法-1-3', 'B'), macroRow('衆法-1-4', 'B')]),
      involvements: [csv(INV_HEAD, [inv('衆法-1-1', 'decide', '甲'), inv('衆法-1-3', 'decide', '乙')])],
    }));
    const whole = rankOf(out.wholeEconomy);
    const { ranking } = withLedgerPeople(rankOf(out.industry), personsCsv, whole);
    const reason = (id: string) => ranking.people.find(p => p.actorId === id)!.unrankedReason;
    expect(reason('甲')).toBe('産業別の群への関与の記録が無い（全産業の別欄にある）');
    expect(reason('丙')).toBe('群に属する法律への関与の記録が無い');
    expect(ranking.people.find(p => p.actorId === '乙')!.laws).toBe(1);
  });
});

describe('曝露ランキングの入力（実データの性質）', { timeout: 180_000 }, () => {
  const file = (p: string) => readFileSync(fileURLToPath(new URL(`../../data/${p}`, import.meta.url)), 'utf8');
  const ballotsDir = '../../data/acquired/sangiin-votes/ballots';
  const ballotFiles = readdirSync(fileURLToPath(new URL(ballotsDir, import.meta.url))).filter(f => f.endsWith('.csv')).sort();
  const src: ExposureSources = {
    macro: file('derived/macro-v1/macro.csv'),
    industryYear: file('derived/exposure-v1/industry-year.csv'),
    votesIndex: file('acquired/sangiin-votes/votes_index.csv'),
    sangiinMembers: file('acquired/sangiin-votes/members.csv'),
    ballots: ballotFiles.map(f => file(`acquired/sangiin-votes/ballots/${f}`)),
    enacted: file('acquired/bill-census-full/enacted.csv'),
    cabinet: file('acquired/office-holders/cabinet.csv'),
    persons: file('derived/person-ids/persons.csv'),
    roster: file('acquired/diet-roster/current.csv'),
    involvements: [file('derived/allocation-v1/involvements.csv'), file('derived/allocation-v1/involvements-auto.csv')],
  };
  const params = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: SCORING_CONSTANTS.minContributingLaws, topThreeShareCap: SCORING_CONSTANTS.topThreeShareCap };
  const build = () => {
    const built = buildExposureInputs(src);
    return {
      built, inputs: built.industry,
      ranking: buildExposureRanking(built.industry.groups, built.industry.involvements, params),
      whole: buildExposureRanking(built.wholeEconomy.groups, built.wholeEconomy.involvements, params),
    };
  };
  const { built, inputs, ranking, whole } = build();
  const rel = (a: number, b: number) => Math.abs(a - b) / Math.max(1, Math.abs(b));
  const lawIdRe = /(閣法|衆法|参法)-\d+-\d+/;

  it('検算：人＋会派＋未配分が expected と low・median・high とも相対誤差 1e-9 以内（産業別・全産業とも）', () => {
    for (const t of [ranking.totals, whole.totals]) {
      for (const k of ['low', 'median', 'high'] as const) expect(rel(t.people[k] + t.parties[k] + t.unallocated[k], t.expected[k])).toBeLessThan(1e-9);
    }
  });

  it('同じ産業×年の群が2つ無い。産業別に _T は入らず、全産業は _T だけ', () => {
    for (const bucket of [built.industry, built.wholeEconomy]) {
      const ids = bucket.groups.map(g => g.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
    expect(built.industry.groups.some(g => g.group === '_T')).toBe(false);
    expect(built.wholeEconomy.groups.length).toBeGreaterThan(0);
    expect(built.wholeEconomy.groups.every(g => g.group === '_T')).toBe(true);
    expect(built.industry.involvements.every(i => !i.groupId.startsWith('_T|'))).toBe(true);
    // 産業別の totals.expected は、産業別の群の額だけから決まる（_T の額が入らない）。
    const sum = built.industry.groups.reduce((x, g) => x + g.diff.median, 0) * 0.6;
    expect(rel(ranking.totals.expected.median, sum)).toBeLessThan(1e-9);
  });

  it('出力に法律の ID が無い', () => {
    expect(JSON.stringify({ ranking, whole, groups: inputs.groups.map(g => ({ ...g })) })).not.toMatch(lawIdRe);
  });

  it('賛成・反対の関与には院が必ず付く。同じ法律・役割・院の枠は人と会派の両方に配られない', () => {
    const kinds = new Map<string, number>(); // 1：会派、2：個人
    let bad = 0;
    for (const b of [built.industry, built.wholeEconomy]) {
      for (const i of b.involvements) {
        if (i.role !== 'yes' && i.role !== 'no') continue;
        if ((i.house !== 'lower' && i.house !== 'upper') || (i.house === 'lower') !== (i.actorKind === 'party')) bad++;
        const k = `${i.lawId}|${i.role}|${i.house}`;
        kinds.set(k, (kinds.get(k) ?? 0) | (i.actorKind === 'party' ? 1 : 2));
      }
    }
    expect(bad).toBe(0);
    expect(kinds.size).toBeGreaterThan(1000);
    for (const v of kinds.values()) expect(v === 1 || v === 2).toBe(true);
  });

  it('参議院の投票が決まった法律が100本を大きく超え、同じ人が同じ法律で yes と no の両方に居ない', () => {
    expect(built.counts.votesMatched).toBeGreaterThan(500);
    expect(built.counts.votesMatched + built.counts.votesNotFound).toBe(built.counts.votesLaws);
    const roles = new Map<string, number>(); // 1：yes、2：no
    for (const b of [built.industry, built.wholeEconomy]) {
      for (const i of b.involvements) {
        if (i.house !== 'upper' || i.actorKind !== 'person') continue;
        const k = `${i.lawId}\u0000${i.actorId}`;
        roles.set(k, (roles.get(k) ?? 0) | (i.role === 'yes' ? 1 : 2));
      }
    }
    expect(roles.size).toBeGreaterThan(10000);
    for (const v of roles.values()) expect(v).not.toBe(3);
  });

  it('1本の法律・1つの群で、全員（人＋会派＋未配分）の受ける割合は比率の合計を超えず、1人の割合はその人の役割の比率の和を超えない', () => {
    const sample = new Map<string, Involvement[]>();
    for (const i of inputs.involvements) {
      if (sample.size >= 40 && !sample.has(`${i.groupId}\u0000${i.lawId}`)) continue;
      const k = `${i.groupId}\u0000${i.lawId}`;
      sample.set(k, [...(sample.get(k) ?? []), i]);
    }
    let checked = 0;
    for (const [k, list] of sample) {
      const g = inputs.groups.find(x => x.id === k.split('\u0000')[0])!;
      if (g.diff.median === 0) continue;
      const one = buildExposureRanking([{ ...g, lawCount: 1 }], list, { ...params, minLaws: 1, topThreeShareCap: 1 });
      const t = one.totals;
      expect(rel(t.people.median + t.parties.median + t.unallocated.median, t.expected.median)).toBeLessThan(1e-9);
      expect(Math.abs(t.expected.median)).toBeLessThanOrEqual(Math.abs(g.diff.median) * 0.6 * (1 + 1e-9));
      for (const row of [...one.people, ...one.parties]) {
        const roles = new Set(list.filter(x => x.actorId === row.actorId && x.actorKind === row.actorKind).map(x => x.role));
        const cap = [...roles].reduce((s, r) => s + DEFAULT_ROLE_RATIO[r], 0);
        expect(Math.abs(row.exposureYen.median)).toBeLessThanOrEqual(Math.abs(g.diff.median) * cap * (1 + 1e-9));
      }
      checked++;
    }
    expect(checked).toBeGreaterThan(10);
  });

  it('閣法だけの群では、人ごとの cabinet と proposer の額の比が 0.2:0.4', () => {
    // 群の法律がすべて閣法の群だけを選ぶ（閣法の本数を macro.csv の窓から数える）。
    const cabinetLaws = new Map<string, number>();
    for (const r of parseCsv(src.macro)) {
      if (r['結果'] !== '額' || r['産業'] === 'COVID' || !r['id'].startsWith('閣法')) continue;
      const m = /(\d+)〜(\d+)年/.exec(r['窓'])!;
      for (let y = Number(m[1]); y <= Number(m[2]); y++) { const gid = `${r['産業']}|${y}`; cabinetLaws.set(gid, (cabinetLaws.get(gid) ?? 0) + 1); }
    }
    const cabinetOnly = inputs.groups.filter(g => cabinetLaws.get(g.id) === g.lawCount).map(g => g.id);
    expect(cabinetOnly.length).toBeGreaterThan(0);
    let checked = 0;
    for (const p of ranking.people) {
      for (const gid of cabinetOnly) {
        const c = p.cells.find(x => x.groupId === gid && x.role === 'cabinet');
        const q = p.cells.find(x => x.groupId === gid && x.role === 'proposer');
        if (!c || !q || q.exposureYen.median === 0) continue;
        expect(rel(c.exposureYen.median / q.exposureYen.median, 0.2 / 0.4)).toBeLessThan(1e-9);
        checked++;
      }
    }
    expect(checked).toBeGreaterThan(0);
  });

  it('閣法は閣僚全員に同じ重みで cabinet と proposer の両方を置く（首相1人に寄せない）', () => {
    const by = new Map<string, { cabinet: Set<string>; proposer: Set<string> }>();
    for (const i of [...inputs.involvements, ...built.wholeEconomy.involvements]) {
      if (!i.lawId.startsWith('閣法') || (i.role !== 'cabinet' && i.role !== 'proposer')) continue;
      expect(i.weight).toBe(1);
      const x = by.get(i.lawId) ?? { cabinet: new Set<string>(), proposer: new Set<string>() };
      x[i.role].add(i.actorId);
      by.set(i.lawId, x);
    }
    expect(by.size).toBeGreaterThan(1000);
    for (const x of by.values()) {
      expect(x.cabinet.size).toBeGreaterThan(1);
      expect([...x.proposer].sort()).toEqual([...x.cabinet].sort());
    }
  });

  it('法律が1本だけの産業×年の群には関与を置かない（群の差がその法律の額になるため）', () => {
    const single = new Set([...built.industry.groups, ...built.wholeEconomy.groups].filter(g => g.lawCount === 1).map(g => g.id));
    expect(single.size).toBe(built.counts.singleLawGroups);
    expect(single.size).toBeGreaterThan(0);
    expect([...inputs.involvements, ...built.wholeEconomy.involvements].filter(i => single.has(i.groupId))).toEqual([]);
  });

  it('委員会提出の法律には proposer を置かない', () => {
    expect(inputs.involvements.filter(i => i.lawId === '衆法-193-20' && i.role === 'proposer')).toEqual([]);
  });

  it('params が定数、claim が descriptive、会派（衆議院の賛否）の行がある', () => {
    expect(ranking.params.minLaws).toBe(SCORING_CONSTANTS.minContributingLaws);
    expect(ranking.params.topThreeShareCap).toBe(SCORING_CONSTANTS.topThreeShareCap);
    expect(ranking.claim).toBe('descriptive');
    expect(ranking.parties.length).toBeGreaterThan(5);
  });

  it('占有率が上限を超える人は階層に入らず、理由が付く。階層に入る人は上限以下', () => {
    let over = 0;
    for (const p of [...ranking.people, ...ranking.parties]) {
      if (p.tier !== null) expect(p.topThreeShare).toBeLessThanOrEqual(SCORING_CONSTANTS.topThreeShareCap);
      else if (p.laws >= SCORING_CONSTANTS.minContributingLaws && p.topThreeShare > SCORING_CONSTANTS.topThreeShareCap) { over++; expect(p.unrankedReason).toContain('上位3本の占有率'); }
    }
    expect(over).toBeGreaterThanOrEqual(0);
  });

  it('人物台帳の全員が、点あり（tier が数）か点なし＋理由のどちらかで1回ずつ載る', () => {
    const { ranking: full, coverage } = withLedgerPeople(ranking, src.persons, whole);
    const ledgerIds = [...new Set(parseCsv(src.persons).map(r => r['人物ID']).filter(Boolean))];
    const seen = new Map<string, number>();
    for (const p of full.people) seen.set(p.actorId, (seen.get(p.actorId) ?? 0) + 1);
    expect(ledgerIds.length).toBeGreaterThan(3000);
    for (const id of ledgerIds) expect(seen.get(id)).toBe(1);
    for (const p of full.people) expect(p.tier !== null ? p.unrankedReason === '' : p.unrankedReason.length > 0).toBe(true);
    expect(coverage.ranked + coverage.unrankedWithAmount + coverage.noInvolvement).toBe(coverage.ledger);
    expect(full.totals).toEqual(ranking.totals);
  });

  it('2回作って同じ', () => {
    const again = build();
    expect(JSON.stringify(again.ranking)).toBe(JSON.stringify(ranking));
    expect(JSON.stringify(again.whole)).toBe(JSON.stringify(whole));
    expect(JSON.stringify(again.built)).toBe(JSON.stringify(built));
  });
});
