// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { buildReferenceMembers, kanjiNumber, normName, parseProposer, pickVote } from './members-reference';

describe('全議員の参考の額', () => {
  it('提出者の欄を代表者と人数に分ける', () => {
    expect(parseProposer('熊代 昭彦君外四名')).toEqual({ lead: '熊代昭彦', others: 4 });
    expect(parseProposer('島村 宜伸君外十二名')).toEqual({ lead: '島村宜伸', others: 12 });
    expect(parseProposer('山田 太郎君')).toEqual({ lead: '山田太郎', others: 0 });
    expect(kanjiNumber('二十三')).toBe(23);
    expect(normName('鈴木　一郎君')).toBe('鈴木一郎');
  });
  it('成立した日の投票から、題名が一致して可決したものを1つ選ぶ', () => {
    const v = (id, name, y = 200, n = 10) => ({ 投票ID: id, 議案名: name, 集計_賛成: String(y), 集計_反対: String(n) });
    expect(pickVote('商法等の一部を改正する法律案', [v('a', '日程第３ 商法等の一部を改正する法律案（内閣提出）'), v('b', '日程第４ 商法等の一部を改正する法律の施行に伴う関係法律の整備に関する法律案（内閣提出）')])?.投票ID).toBe('a');
    expect(pickVote('X法案', [v('a', 'X法案「修正案」', 50, 150), v('b', 'X法案「原案」')])?.投票ID).toBe('b');
    expect(pickVote('X法案', [])).toBeNull();
  });
  it('同じ観測の法律は額を本数で割り、提出者と参議院の賛成者に配る。名簿の人は0円でも載る', () => {
    const law = (id, median) => ({ id, title: id, side: 'loss', certainty: '参考', group: 'g', window: '2000〜2009年', amountLowYen: median, amountMedianYen: median, amountHighYen: median });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n150,衆法,150,1,甲法案,山田 太郎君,,,,平成12年 3月 1日\n150,衆法,150,2,乙法案,山田 太郎君,,,,平成12年 3月 1日\n';
    const votesIndex = '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\nv1,150,2000-03-01,日程第１ 甲法案（衆議院提出）,2,1\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('衆法-150-1', 100), law('衆法-150-2', 100)] }, enacted, votesIndex,
      ballots: ['投票ID,議員ID,賛否\nv1,1,Y\nv1,2,Y\nv1,3,N\n'], sangiinMembers: '議員ID,回次,議員名,会派\n1,150,佐藤 一,自民\n2,150,鈴木 二,自民\n3,150,高橋 三,民主\n',
      cabinet: '役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n衆議院,田中 四,,,無,東京1\n',
    });
    const by = new Map(out.members.map(m => [m.name, m]));
    // 1本目（投票あり）：額100÷2本＝50 を配る。2本目（投票なし）は提出者に 1/3。
    expect(by.get('佐藤一').loss.median).toBeGreaterThan(0);
    expect(by.get('高橋三')).toBeUndefined();
    expect(by.get('山田太郎').laws).toBe(2);
    expect(by.get('田中四').net.median).toBe(0);
    expect(by.get('田中四').reason).toContain('衆議院');
    const total = out.members.reduce((s, m) => s + m.loss.median, 0);
    expect(total).toBeLessThanOrEqual(100 + 1e-9);
    expect(out.counts).toMatchObject({ laws: 2, lawsWithVotes: 1, lawsPartyOnly: 1, observations: 1 });
  });

  it('閣法は提出した回次の総理大臣に配り、継続審査で後の付託日になっても後任に付けない。会期中に替わった回次は配らない', () => {
    const law = (id: string) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n'
      + '169,閣法,169,1,甲法案,,,平成20年 2月 1日,,\n169,閣法,169,2,乙法案,,,平成20年 5月 1日,,\n'
      + '170,閣法,169,3,丙法案,,,平成20年 9月24日,,\n'
      + '171,閣法,171,1,丁法案,,,平成21年 1月 5日,,\n171,閣法,171,2,戊法案,,,平成21年 9月20日,,\n';
    const cabinet = '役職,氏名,就任日_西暦,退任日_西暦\n内閣総理大臣,前 首相,2007-09-26,2008-09-24\n内閣総理大臣,後 首相,2008-09-24,2009-09-16\n内閣総理大臣,次 首相,2009-09-16,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('閣法-169-3'), law('閣法-171-1')] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet, roster: '院,氏名,本名,読み,会派,選挙区\n',
    } as never);
    const by = new Map(out.members.map(m => [m.name, m]));
    expect(by.get('前首相')?.top.map(t => t.lawId)).toEqual(['閣法-169-3']);
    expect(by.get('後首相')).toBeUndefined();
    expect(by.get('次首相')).toBeUndefined();
  });

  it('同姓同名は院では決めず、配らない', () => {
    const law = (id: string) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const header = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n';
    const enacted = header + '150,衆法,150,1,甲法案,山田 太郎君,,,,\n150,参法,150,2,乙法案,山田 太郎君,,,,\n150,閣法,150,3,丙法案,,,平成12年 3月 1日,,\n';
    const persons = '人物ID,氏名,読み,院,選挙区,別表記\n山田太郎（衆・東京1）,山田太郎,やまだ たろう,衆議院,東京1,\n山田太郎（参・比例）,山田太郎,やまだ たろう,参議院,比例,\n';
    const roster = '院,氏名,本名,読み,会派,選挙区\n衆議院,山田 太郎,,やまだ たろう,自民,東京1\n参議院,山田 太郎,,やまだ たろう,立憲,比例\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('衆法-150-1'), law('参法-150-2'), law('閣法-150-3')] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet: '役職,氏名,就任日_西暦,退任日_西暦\n内閣総理大臣,山田 太郎,1999-01-01,\n', roster, persons,
    });
    const by = new Map(out.members.map(m => [m.id, m]));
    // 台帳は今の院しか持たない（院を移った人がいる）ので、衆法・参法・閣法のどれでも、院では決めずに配らない。
    expect(by.get('山田太郎（衆・東京1）')!.top).toEqual([]);
    expect(by.get('山田太郎（参・比例）')!.top).toEqual([]);
    expect(out.attributions).toEqual([]);
    expect(out.counts.unresolved).toBe(3);
    expect(out.members.length).toBe(2);
  });

  it('委員会提出の法律は、提出者一覧に委員長の名前があっても人に配らない', () => {
    const law = { id: '衆法-145-21', title: '甲法案', side: 'loss', certainty: '参考', group: 'g', window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 };
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n145,衆法,145,21,甲法案,建設委員長,平田米男君,,,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet: '役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n',
    });
    expect(out.members.find(m => m.name.startsWith('平田'))).toBeUndefined();
    expect(out.attributions).toEqual([]);
  });
});
