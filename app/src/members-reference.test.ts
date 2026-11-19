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
    expect(normName('安住 淳*')).toBe('安住淳');
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
      cabinet: '区分,役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n衆議院,田中 四,,,無,東京1\n',
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

  it('額なし（noAmount）の法律は、額が残っていても人に配らない', () => {
    const law = (id, median) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: median, amountMedianYen: median, amountHighYen: median });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n150,衆法,150,1,甲法案,山田 太郎君,,,,平成12年 3月 1日\n150,衆法,150,2,乙法案,山田 太郎君,,,,平成12年 3月 1日\n';
    const base = {
      enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n', ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n',
      cabinet: '区分,役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n衆議院,田中 四,,,無,東京1\n',
    };
    const laws = [law('衆法-150-1', 100), law('衆法-150-2', 100)];
    const withNone = buildReferenceMembers({ ...base, ranking: { laws, generatedFrom: { parameters: { noAmount: ['衆法-150-2'] } } } });
    const without = buildReferenceMembers({ ...base, ranking: { laws } });
    const total = (o) => o.members.reduce((s, m) => s + m.loss.median, 0);
    expect(withNone.counts.laws).toBe(1);
    expect(without.counts.laws).toBe(2);
    // 同じ群・期間の相棒が減るので、残る法律の取り分の分母は1になる（既存の共有額・降格の除外と同じ扱い）。
    expect(total(without)).toBeGreaterThan(0);
    expect(withNone.attributions.some(a => a.lawId === '衆法-150-1')).toBe(true);
    expect(withNone.attributions.every(a => a.lawId !== '衆法-150-2')).toBe(true);
  });

  it('閣法は首相1人に付けず、会期の最初から最後まで在任した閣僚に均等に配る。途中で替わった閣僚には配らない', () => {
    const law = (id: string) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n'
      + '171,閣法,171,1,甲法案,,,平成21年 1月 5日,,\n171,閣法,171,2,乙法案,,,平成21年 6月 5日,,\n';
    const cabinet = '区分,役職,氏名,就任日_西暦,退任日_西暦\n'
      + '閣僚,内閣総理大臣,首相 一,2008-09-24,\n閣僚,財務大臣,財務 二,2008-09-24,\n閣僚,法務大臣,法務 三,2008-09-24,2009-03-01\n閣僚,法務大臣,法務 四,2009-03-01,\n'
      + '副大臣,財務副大臣,副 五,2008-09-24,\n'
      + '閣僚,内閣官房副長官,官房 六,2008-09-24,\n閣僚,内閣法制局長官,法制 七,2008-09-24,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('閣法-171-1')] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet, roster: '院,氏名,本名,読み,会派,選挙区\n',
    } as never);
    const names = out.attributions.map(a => a.name).sort();
    // 付託日が1月と6月の両端 → 在任が両端にまたがるのは首相一と財務二だけ。副大臣・副長官・法制局長官は閣僚ではない。
    expect(names).toEqual(['財務二', '首相一']);
    const shares = out.attributions.map(a => a.median);
    expect(shares[0]).toBeCloseTo(shares[1], 6);
    // 首相1人だけに配った旧方式の半分になる（均等配分）。
    const pm = out.attributions.find(a => a.name === '首相一')!;
    expect(out.attributions.reduce((s, a) => s + a.median, 0)).toBeCloseTo(pm.median * 2, 6);
  });

  it('総理大臣が会期中に替わる回次の閣法は、交代より前に付託された法律だけ、付託日に在任した閣僚に配る', () => {
    const law = (id: string) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n'
      + '171,閣法,171,1,甲法案,,,平成21年 1月 5日,,\n171,閣法,171,2,乙法案,,,平成21年 6月 5日,,\n';
    const cabinet = '区分,役職,氏名,就任日_西暦,退任日_西暦\n'
      + '閣僚,内閣総理大臣,首相 一,2008-09-24,2009-03-01\n閣僚,内閣総理大臣,首相 二,2009-03-01,\n閣僚,財務大臣,財務 三,2008-09-24,\n'
      + '閣僚,法務大臣,法務 四,2008-09-24,2009-03-01\n閣僚,法務大臣,法務 五,2009-03-01,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('閣法-171-1'), law('閣法-171-2')] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet, roster: '院,氏名,本名,読み,会派,選挙区\n',
    } as never);
    // 1月に付託された法律は、提出がそれより前なので前の内閣の提出と決まる。6月（交代より後）に付託された法律は、
    // 前の内閣が出して付託が遅れたのか後の内閣が出したのか付託日では決められないので、誰にも配らない。
    const of = (lawId: string) => out.attributions.filter(a => a.lawId === lawId).map(a => a.name).sort();
    expect(of('閣法-171-1')).toEqual(['法務四', '財務三', '首相一']);
    expect(of('閣法-171-2')).toEqual([]);
    expect(out.members.map(m => m.id).sort()).toEqual(['法務四', '財務三', '首相一']);
  });

  it('名簿が会期の途中から脚注の印（*）つきで書く閣僚も、同じ人として通して在任に数える', () => {
    const law = (id: string) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n'
      + '180,閣法,180,1,甲法案,,,平成24年 2月 1日,,\n180,閣法,180,2,乙法案,,,平成24年 8月 1日,,\n';
    const cabinet = '区分,役職,氏名,就任日_西暦,退任日_西暦\n'
      + '閣僚,内閣総理大臣,首相 一,2011-09-02,\n閣僚,財務大臣,財務 二,2011-09-02,2012-06-04\n閣僚,財務大臣,財務 二*,2012-06-04,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('閣法-180-1')] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet, roster: '院,氏名,本名,読み,会派,選挙区\n',
    } as never);
    expect(out.attributions.map(a => a.name).sort()).toEqual(['財務二', '首相一']);
    expect(out.members.map(m => m.id).sort()).toEqual(['財務二', '首相一']);
  });

  it('向きが未確定の法律は、side がどちらでも人に配らず、関わった人に理由を付ける', () => {
    const NOTE = '向きは未確定（損失・便益の区別は産業と比較国の差の符号で、この法律の効果の向きを示す証拠ではない）';
    const law = (id: string, side: string, notes: string[]) => ({ id, title: id, side, certainty: '参考', notes, group: 'g', window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n'
      + '150,衆法,150,1,甲法案,山田 太郎君,,,,平成12年 3月 1日\n150,衆法,150,2,乙法案,山田 太郎君,,,,平成12年 3月 1日\n150,衆法,150,3,丙法案,川上 花子君,,,,\n150,衆法,150,4,丁法案,山田 太郎君,,,,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('衆法-150-1', 'loss', [NOTE]), law('衆法-150-2', 'benefit', ['全体指標で測った参考の額', NOTE]), law('衆法-150-3', 'loss', [NOTE]), law('衆法-150-4', 'loss', [])] }, enacted,
      votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\nv1,150,2000-03-01,日程第１ 甲法案（衆議院提出）,2,1\n',
      ballots: ['投票ID,議員ID,賛否\nv1,1,Y\nv1,2,Y\nv1,3,N\n'], sangiinMembers: '議員ID,回次,議員名,会派\n1,150,佐藤 一,自民\n2,150,鈴木 二,自民\n3,150,高橋 三,民主\n',
      cabinet: '区分,役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n衆議院,田中 四,,,無,東京1\n',
    });
    const by = new Map(out.members.map(m => [m.name, m]));
    // 額を配るのは印の無い4本目だけ。同じ観測（group・window）を共有する本数には向きが未確定の3本も数える（配らない分を4本目に寄せない）：90÷4本×1/3。
    const given = out.attributions.filter(a => a.side !== 'undetermined');
    expect(new Set(given.map(a => a.lawId))).toEqual(new Set(['衆法-150-4']));
    expect(out.counts).toMatchObject({ laws: 1, observations: 1, lawsDirectionUndetermined: 3, unresolved: 0 });
    expect(by.get('山田太郎')).toMatchObject({ laws: 1, credit: { median: 0 }, withheldLaws: 2 });
    expect(by.get('山田太郎')!.loss.median).toBeCloseTo(7.5, 6);
    expect(by.get('山田太郎')!.reason).toContain('法律2本は、向きが未確定');
    // 配らなかった関わりは、額0・向き未確定の行として照合用の一覧に残る（公開ファイルの額には入らない）。
    const held = out.attributions.filter(a => a.side === 'undetermined');
    expect(held.every(a => a.median === 0)).toBe(true);
    expect(held.map(a => `${a.name}/${a.lawId}/${a.role}`).sort()).toEqual(['佐藤一/衆法-150-1/vote', '山田太郎/衆法-150-1/proposer', '山田太郎/衆法-150-2/proposer', '川上花子/衆法-150-3/proposer', '鈴木二/衆法-150-1/vote']);
    expect(out.members.reduce((s, m) => s + m.loss.median + m.credit.median, 0)).toBeCloseTo(7.5, 6);
    // 額が無い人も、関わった記録があれば載せて理由を付ける（提出者・参議院の賛成）。反対した人と関わりの無い人には付けない。
    for (const name of ['川上花子', '佐藤一', '鈴木二']) {
      expect(by.get(name)).toMatchObject({ laws: 0, loss: { median: 0 }, credit: { median: 0 }, top: [], withheldLaws: 1 });
      expect(by.get(name)!.reason).toContain('法律1本は、向きが未確定');
    }
    expect(by.get('高橋三')).toBeUndefined();
    expect(by.get('田中四')).toMatchObject({ withheldLaws: 0 });
    expect(by.get('田中四')!.reason).not.toContain('向きが未確定');
  });

  it('閣法は提出した回次の総理大臣に配り、継続審査で後の付託日になっても後任に付けない。会期中に替わった回次は、交代より前に付託された法律を付託日の総理大臣に配る', () => {
    const law = (id: string) => ({ id, title: id, side: 'loss', certainty: '参考', group: id, window: '2000〜2009年', amountLowYen: 90, amountMedianYen: 90, amountHighYen: 90 });
    const enacted = '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n'
      + '169,閣法,169,1,甲法案,,,平成20年 2月 1日,,\n169,閣法,169,2,乙法案,,,平成20年 5月 1日,,\n'
      + '170,閣法,169,3,丙法案,,,平成20年 9月24日,,\n'
      + '171,閣法,171,1,丁法案,,,平成21年 1月 5日,,\n171,閣法,171,2,戊法案,,,平成21年 9月20日,,\n172,閣法,171,3,己法案,,,平成21年10月 1日,,\n';
    const cabinet = '区分,役職,氏名,就任日_西暦,退任日_西暦\n閣僚,内閣総理大臣,前 首相,2007-09-26,2008-09-24\n閣僚,内閣総理大臣,後 首相,2008-09-24,2009-09-16\n閣僚,内閣総理大臣,次 首相,2009-09-16,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [law('閣法-169-3'), law('閣法-171-1'), law('閣法-171-3')] }, enacted, votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet, roster: '院,氏名,本名,読み,会派,選挙区\n',
    } as never);
    const by = new Map(out.members.map(m => [m.name, m]));
    expect(by.get('前首相')?.top.map(t => t.lawId)).toEqual(['閣法-169-3']);
    // 第171回は会期中に替わるので、交代より前の1月に付託された法律は付託日の総理大臣に。継続審査で次の回次に付託された法律（閣法-171-3）は、どの内閣の提出か決められないので配らない。
    expect(by.get('後首相')?.top.map(t => t.lawId)).toEqual(['閣法-171-1']);
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
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet: '区分,役職,氏名,就任日_西暦,退任日_西暦\n閣僚,内閣総理大臣,山田 太郎,1999-01-01,\n', roster, persons,
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
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet: '区分,役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n',
    });
    expect(out.members.find(m => m.name.startsWith('平田'))).toBeUndefined();
    expect(out.attributions).toEqual([]);
  });
  it('人物台帳の全員を、額が無くても0円で載せる（元職も。台帳の空行は除く）', () => {
    const persons = '人物ID,氏名,読み,院,選挙区,別表記\n,,,,,\n元職太郎,元職太郎,もとしょく たろう,衆議院,東京1,\n';
    const out = buildReferenceMembers({
      ranking: { laws: [] }, enacted: '回次,種別,提出回次,番号,題名,提出者,提出者一覧,付託日_衆,議決日_衆,議決日_参\n', votesIndex: '投票ID,回次,投票日,議案名,集計_賛成,集計_反対\n',
      ballots: [], sangiinMembers: '議員ID,回次,議員名,会派\n', cabinet: '区分,役職,氏名,就任日_西暦,退任日_西暦\n', roster: '院,氏名,本名,読み,会派,選挙区\n', persons,
    });
    expect(out.members.map(m => m.id)).toEqual(['元職太郎']);
    expect(out.members[0]).toMatchObject({ current: null, laws: 0 });
    expect(out.counts).toMatchObject({ members: 1, current: 0, withAmount: 0, ledger: 1 });
  });
});
