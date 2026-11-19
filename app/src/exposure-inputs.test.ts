// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { parseCsv } from './impact-batch';
import { buildExposureInputs, type ExposureSources } from './exposure-inputs';
import { buildExposureRanking, DEFAULT_ROLE_RATIO, type ExposureRanking, type Involvement } from './exposure-ranking';
import { SCORING_CONSTANTS } from './scoring-constants';

const csv = (head: string[], rows: Record<string, string>[]) =>
  [head.join(','), ...rows.map(r => head.map(h => r[h] ?? '').join(','))].join('\n') + '\n';

const MACRO_HEAD = ['id', '題名', '分野', '分野の由来', '産業', '施行日', '施行日の由来', '窓', '中央値', '第1四分位', '第3四分位', '比較国', '計算式の要素', '結果', '理由'];
const macroRow = (id: string, 産業: string, 中央値 = '100', q1 = '50', q3 = '300', 結果 = '額') => ({
  id, 題名: 'テスト', 産業, 窓: '1998〜2007年', 中央値, 第1四分位: q1, 第3四分位: q3, 比較国: 'AUS・FRA',
  計算式の要素: `OECD 表6 JPN ${産業}の名前（${産業}）LR、比較国：2か国`, 結果,
});
const ENACTED_HEAD = ['回次', '種別', '提出回次', '番号', '付託日_衆'];
const CAB_HEAD = ['内閣名', '区分', '氏名', '役職', '就任日_西暦', '退任日_西暦'];
const cab = (氏名: string, 役職: string, from: string, to = '', 区分 = '閣僚') => ({ 内閣名: 'テスト内閣', 区分, 氏名, 役職, 就任日_西暦: from, 退任日_西暦: to });
const INV_HEAD = ['法律ID', '氏名', '行動', '算入', '人物ID'];
const inv = (法律ID: string, 行動: string, 人物ID: string, 算入 = 'はい') => ({ 法律ID, 氏名: '氏名', 行動, 算入, 人物ID });
const OPP_HEAD = ['法律ID', '投票ID', '氏名', '人物ID', '算入'];

// 回次2（1998年）は総理大臣が同じ。回次3（2000年）は会期の途中で総理大臣が替わる。
const enacted = csv(ENACTED_HEAD, [
  { 回次: '2', 種別: '閣法', 提出回次: '2', 番号: '1', 付託日_衆: '平成10年 1月10日' },
  { 回次: '2', 種別: '閣法', 提出回次: '2', 番号: '2', 付託日_衆: '平成10年 3月10日' },
  { 回次: '3', 種別: '閣法', 提出回次: '3', 番号: '1', 付託日_衆: '平成12年 1月10日' },
  { 回次: '3', 種別: '閣法', 提出回次: '3', 番号: '2', 付託日_衆: '平成12年 5月10日' },
]);
const CABINET_ROWS = [
  cab('首相 一', '内閣総理大臣', '1995-01-01', '2000-03-01'),
  cab('首相 二', '内閣総理大臣', '2000-03-01'),
  cab('大臣 甲', '法務大臣', '1995-01-01'),
  cab('大臣 乙', '外務大臣', '1995-01-01'),
  cab('大臣 途中', '財務大臣', '1998-02-01'),
  cab('副長 官', '内閣官房副長官', '1995-01-01'),
];
const cabinet = csv(CAB_HEAD, CABINET_ROWS);
// 「山田花子」は台帳に同姓同名が2人いて結べない。
const cabinetWithUnresolved = csv(CAB_HEAD, [...CABINET_ROWS, cab('山田 花子', '文部大臣', '1995-01-01')]);
const persons = csv(['人物ID', '氏名', '読み', '院', '選挙区', '別表記'], [
  { 人物ID: '山田花子（衆・東京1）', 氏名: '山田花子', 院: '衆議院', 選挙区: '東京1' },
  { 人物ID: '山田花子（参・比例）', 氏名: '山田花子', 院: '参議院', 選挙区: '比例' },
]);
const base = (over: Partial<ExposureSources> = {}): ExposureSources => ({
  macro: csv(MACRO_HEAD, [
    macroRow('衆法-1-1', 'A'), macroRow('衆法-1-2', 'A'),
    macroRow('閣法-2-1', 'B', '1000', '900', '1100'), macroRow('閣法-2-2', 'B', '1000', '900', '1100'),
    macroRow('閣法-3-1', 'C'),
    macroRow('閣法-2-9', 'COVID'), macroRow('閣法-2-8', 'B', '', '', '', '理由'),
  ]),
  enacted, cabinet, persons, roster: '',
  involvements: [csv(INV_HEAD, [])], opposing: csv(OPP_HEAD, []), ...over,
});
const sortedKeys = (xs: Involvement[]) => xs.map(x => `${x.lawId}|${x.role}|${x.actorId}`).sort();

describe('曝露ランキングの入力（群）', () => {
  it('結果=額 で産業≠COVID の行を (産業, 窓) の群にし、額の欄を diff に写す', () => {
    const { groups, counts } = buildExposureInputs(base());
    expect(groups.map(g => g.id)).toEqual(['A|1998〜2007年', 'B|1998〜2007年', 'C|1998〜2007年']);
    const a = groups[0];
    expect(a).toMatchObject({ kind: 'group-diff', group: 'A', window: '1998〜2007年', lawCount: 2, diff: { low: 50, median: 100, high: 300 } });
    expect(a.benchmark).toContain('Aの名前');
    expect(a.benchmark).toContain('AUS・FRA');
    expect(groups[1].lawCount).toBe(2);
    expect(counts).toMatchObject({ groups: 3, laws: 5 });
  });

  it('同じ群で額が食い違う、または幅の順序が不正なら止める', () => {
    expect(() => buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'A'), macroRow('衆法-1-2', 'A', '101')]) }))).toThrow('食い違う');
    expect(() => buildExposureInputs(base({ macro: csv(MACRO_HEAD, [{ ...macroRow('衆法-1-1', 'A'), 比較国: 'AUS' }, macroRow('衆法-1-2', 'A')]) }))).toThrow('食い違う');
    expect(() => buildExposureInputs(base({ macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'A', '100', '200', '300')]) }))).toThrow('low≤median≤high');
  });
});

describe('曝露ランキングの入力（関与）', () => {
  const run = (invs: Record<string, string>[], opp: Record<string, string>[] = [], second: Record<string, string>[] = []) =>
    buildExposureInputs(base({ involvements: [csv(INV_HEAD, invs), csv(INV_HEAD, second)], opposing: csv(OPP_HEAD, opp) }));
  const nonCabinet = (xs: Involvement[]) => xs.filter(x => !x.lawId.startsWith('閣法'));

  it('vote は yes、衆法・参法の decide は proposer、反対は no（人・重み1・群に結ぶ）', () => {
    const out = run(
      [inv('衆法-1-1', 'vote', '賛成者'), inv('衆法-1-1', 'decide', '提出者')],
      [{ 法律ID: '衆法-1-2', 投票ID: 'v', 氏名: '反対', 人物ID: '反対者', 算入: 'はい' }]);
    expect(nonCabinet(out.involvements)).toEqual([
      { actorKind: 'person', actorId: '賛成者', groupId: 'A|1998〜2007年', lawId: '衆法-1-1', role: 'yes', weight: 1 },
      { actorKind: 'person', actorId: '提出者', groupId: 'A|1998〜2007年', lawId: '衆法-1-1', role: 'proposer', weight: 1 },
      { actorKind: 'person', actorId: '反対者', groupId: 'A|1998〜2007年', lawId: '衆法-1-2', role: 'no', weight: 1 },
    ]);
    expect(out.counts).toMatchObject({ yesRows: 1, proposerRows: 1, noRows: 1 });
  });

  it('算入=はい でない行、人物ID が空の行、使わない行動は置かず、件数に出す', () => {
    const out = run([
      inv('衆法-1-1', 'vote', '甲', 'いいえ'), inv('衆法-1-1', 'vote', ''),
      inv('衆法-1-1', 'chair', '乙'), inv('衆法-1-1', 'amend', '乙'), inv('衆法-1-1', 'question', '乙'), inv('衆法-1-1', 'その他', '乙'),
      inv('閣法-2-1', 'decide', '閣法の提出者'),
      inv('衆法-99-9', 'vote', '群に無い法律'),
    ]);
    expect(nonCabinet(out.involvements)).toEqual([]);
    expect(out.involvements.some(x => x.actorId === '閣法の提出者' || x.actorId === '群に無い法律')).toBe(false);
    expect(out.counts.skipped).toEqual({ notInGroup: 1, notCounted: 1, cabinetDecide: 1, chair: 1, amend: 1, question: 1, otherAction: 1, noPersonId: 1, committeeProposer: 0, singleLawGroup: 0, duplicates: 0 });
  });

  it('同じ（法律・役割・人）の重複は1つにする（2つのファイルにまたがっても）', () => {
    const out = run([inv('衆法-1-1', 'vote', '甲'), inv('衆法-1-1', 'vote', '甲')], [], [inv('衆法-1-1', 'vote', '甲')]);
    expect(nonCabinet(out.involvements)).toHaveLength(1);
    expect(out.counts.yesRows).toBe(1);
    expect(out.counts.skipped.duplicates).toBe(2);
  });

  it('閣法は、提出した回次の最初から最後まで在任した閣僚全員に cabinet と proposer を置く（記録の有無に依らない）', () => {
    const out = run([]);
    const l1 = out.involvements.filter(x => x.lawId === '閣法-2-1');
    // 総理大臣・法務・外務。会期の途中で就任した大臣・副長官は入らない。
    expect(sortedKeys(l1)).toEqual([
      '閣法-2-1|cabinet|大臣甲', '閣法-2-1|cabinet|大臣乙', '閣法-2-1|cabinet|首相一',
      '閣法-2-1|proposer|大臣甲', '閣法-2-1|proposer|大臣乙', '閣法-2-1|proposer|首相一',
    ].sort());
    expect(l1.every(x => x.weight === 1 && x.groupId === 'B|1998〜2007年')).toBe(true);
    expect(out.counts).toMatchObject({ cabinetLaws: 3, cabinetLawsUndetermined: 1, cabinetLawsUnresolved: 0, cabinetUnresolvedMinisters: 0, cabinetRows: 6, lawsWithAnyInvolvement: 2 });
  });

  it('閣僚の1人でも台帳に結べない閣法には cabinet と proposer を置かない（ほかの閣僚へ寄せない）', () => {
    const out = buildExposureInputs(base({ cabinet: cabinetWithUnresolved }));
    expect(out.involvements.filter(x => x.lawId.startsWith('閣法'))).toEqual([]);
    expect(out.counts).toMatchObject({ cabinetLawsUnresolved: 2, cabinetUnresolvedMinisters: 2, cabinetRows: 0 });
  });

  it('法律が1本だけの群には関与を置かない／委員会提出の法律には proposer を置かない', () => {
    const one = buildExposureInputs(base({
      macro: csv(MACRO_HEAD, [macroRow('衆法-1-1', 'A'), macroRow('衆法-1-2', 'D'), macroRow('衆法-1-3', 'D')]),
      enacted: csv([...ENACTED_HEAD, '提出者'], [{ 回次: '1', 種別: '衆法', 提出回次: '1', 番号: '2', 提出者: '内閣委員長' }, { 回次: '1', 種別: '衆法', 提出回次: '1', 番号: '3', 提出者: '甲 太郎君外二名' }]),
      involvements: [csv(INV_HEAD, [inv('衆法-1-1', 'vote', '甲'), inv('衆法-1-2', 'decide', '乙'), inv('衆法-1-2', 'vote', '乙'), inv('衆法-1-3', 'decide', '丙')])],
    }));
    expect(sortedKeys(one.involvements)).toEqual(['衆法-1-2|yes|乙', '衆法-1-3|proposer|丙']);
    expect(one.counts.singleLawGroups).toBe(1);
    expect(one.counts.skipped).toMatchObject({ singleLawGroup: 1, committeeProposer: 1 });
  });

  it('総理大臣が会期中に替わる回次の閣法には関与を置かず、数える', () => {
    const out = run([]);
    expect(out.involvements.some(x => x.lawId === '閣法-3-1')).toBe(false);
    expect(out.counts.cabinetLawsUndetermined).toBe(1);
  });

  it('会派（party）への配りは作らない', () => {
    const out = run([inv('衆法-1-1', 'vote', '甲')]);
    expect(out.involvements.every(x => x.actorKind === 'person')).toBe(true);
    const ranking = buildExposureRanking(out.groups, out.involvements, { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1 });
    expect(ranking.parties).toEqual([]);
  });

  it('集計器に通すと検算が合う（記録の無い法律の枠は未配分）', () => {
    const out = run([inv('衆法-1-1', 'vote', '甲')]);
    const r = buildExposureRanking(out.groups, out.involvements, { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1 });
    expect(r.unallocated.some(u => u.role === null && u.reason.includes('関与の記録が無い法律'))).toBe(true);
  });
});

describe('曝露ランキングの入力（実データの性質）', () => {
  const file = (p: string) => readFileSync(fileURLToPath(new URL(`../../data/${p}`, import.meta.url)), 'utf8');
  const src: ExposureSources = {
    macro: file('derived/macro-v1/macro.csv'),
    enacted: file('acquired/bill-census-full/enacted.csv'),
    cabinet: file('acquired/office-holders/cabinet.csv'),
    persons: file('derived/person-ids/persons.csv'),
    roster: file('acquired/diet-roster/current.csv'),
    involvements: [file('derived/allocation-v1/involvements.csv'), file('derived/allocation-v1/involvements-auto.csv')],
    opposing: file('derived/allocation-v1/opposing.csv'),
  };
  const params = { roleRatio: DEFAULT_ROLE_RATIO, minLaws: SCORING_CONSTANTS.minContributingLaws };
  const build = () => {
    const inputs = buildExposureInputs(src);
    return { inputs, ranking: buildExposureRanking(inputs.groups, inputs.involvements, params) };
  };
  const { inputs, ranking } = build();
  const rel = (a: number, b: number) => Math.abs(a - b) / Math.max(1, Math.abs(b));

  it('検算：人＋会派＋未配分が expected と low・median・high とも相対誤差 1e-9 以内', () => {
    const t = ranking.totals;
    for (const k of ['low', 'median', 'high'] as const) expect(rel(t.people[k] + t.parties[k] + t.unallocated[k], t.expected[k])).toBeLessThan(1e-9);
  });

  it('出力に法律の ID が無い', () => {
    expect(JSON.stringify({ ranking, groups: inputs.groups.map(g => ({ ...g })) })).not.toMatch(/(閣法|衆法|参法)-\d+-\d+/);
  });

  it('閣法だけの群では、人ごとの cabinet と proposer の額の比が 0.2:0.4', () => {
    // 群の法律がすべて閣法の群だけを選ぶ（閣法の本数を macro.csv の行から数える）。
    const cabinetLaws = new Map<string, number>();
    for (const r of parseCsv(src.macro)) {
      if (r['結果'] !== '額' || r['産業'] === 'COVID' || !r['id'].startsWith('閣法')) continue;
      const gid = `${r['産業']}|${r['窓']}`;
      cabinetLaws.set(gid, (cabinetLaws.get(gid) ?? 0) + 1);
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
    for (const i of inputs.involvements) {
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

  it('法律が1本だけの群には関与を置かない（群の差がその法律の額になるため）', () => {
    const single = new Set(inputs.groups.filter(g => g.lawCount === 1).map(g => g.id));
    expect(single.size).toBe(inputs.counts.singleLawGroups);
    expect(single.size).toBeGreaterThan(0);
    expect(inputs.involvements.filter(i => single.has(i.groupId))).toEqual([]);
  });

  it('委員会提出の法律には proposer を置かない', () => {
    expect(inputs.involvements.filter(i => i.lawId === '衆法-193-20' && i.role === 'proposer')).toEqual([]);
    expect(inputs.counts.skipped.committeeProposer).toBeGreaterThan(0);
  });

  it('params.minLaws が SCORING_CONSTANTS.minContributingLaws、claim が descriptive、parties が空', () => {
    expect(ranking.params.minLaws).toBe(SCORING_CONSTANTS.minContributingLaws);
    expect(ranking.claim).toBe('descriptive');
    expect(ranking.parties).toEqual([]);
  });

  it('2回作って同じ', () => {
    const again = build();
    expect(JSON.stringify(again.ranking)).toBe(JSON.stringify(ranking));
    expect(JSON.stringify(again.inputs)).toBe(JSON.stringify(inputs));
  });
});
