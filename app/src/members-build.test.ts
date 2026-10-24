import { describe, expect, it } from 'vitest';
import { allocatedAmount, buildMembers, confidenceLabel } from './members-build';
import { adjustMembers } from './members-knobs';
import { DEFAULT_KNOBS } from './causal-allocation';

const header = '法律ID,題名,氏名,氏名_原表記,院,行動,当時の肩書,立場区分,立場の根拠,日付,証拠URL,系統A,系統B,参院本会議の賛否,算入,除外理由';
const row = (law: string, name: string, action: string, position: string, counted = 'はい', url = 'https://kokkai.ndl.go.jp/txt/1/1') => `${law},題,${name},${name},参議院,${action},,${position},,2018-01-01,${url},,,,${counted},`;
const publish = ['id,題名,側,損失または便益,便益の状態,判定表の行,公開可否,理由',
  '衆法-1-1,損の法律,国賊側（悪影響）,中央値=1000;第1四分位=800;第3四分位=1200,,R4,公開不可,未測定',
  '衆法-1-2,益の法律,国士側（貢献）,下限：中央値=-400;第1四分位=-600;第3四分位=-200,,R6,公開可,',
  '衆法-1-3,参考の法律,国賊側（悪影響）,中央値=999;第1四分位=999;第3四分位=999,,R1,公開不可,参考'].join('\n');
const loss = ['id,損失または便益の額,参考フラグ,観測グループ', '衆法-1-1,1000,,G1', '衆法-1-2,-400,,G2', '衆法-1-3,999,参考,G1'].join('\n');
const enacted = ['種別,提出回次,番号,経過URL', ...['1', '2', '3'].map(n => `衆法,1,${n},https://www.shugiin.go.jp/x/${n}.htm`)].join('\n');

const votes = ['法律ID,投票ID,日付,賛成,反対,URL', '衆法-1-1,1,2018-01-01,3,1,https://www.sangiin.go.jp/v/1.htm', '衆法-1-2,2,2018-01-01,3,1,https://www.sangiin.go.jp/v/2.htm'].join('\n');
const input = (rows: string[]) => ({ involvements: [header, ...rows].join('\n'), publish, loss, enacted, votes });

describe('議員ページのデータ', () => {
  it('成立への寄与（Shapley 値）で額を配り、純額の小さい順に並べる', () => {
    const data = buildMembers(input([
      row('衆法-1-1', '甲', 'decide', 'minister_or_party_exec'),
      row('衆法-1-1', '乙', 'vote', 'other'),
      row('衆法-1-1', '乙', 'question', 'other'),
      row('衆法-1-1', '戊', 'question', 'other'),
      row('衆法-1-2', '甲', 'decide', 'other'),
      row('衆法-1-2', '乙', 'vote', 'other'),
      row('衆法-1-1', '丙', 'vote', 'other', 'いいえ'),
      row('衆法-1-3', '甲', 'decide', 'other'),
    ]));
    expect(data.laws.map(l => l.id)).toEqual(['衆法-1-1', '衆法-1-2']);
    const law = data.laws[0];
    // 拒否権者2つ・賛成3人・可決に3票：全員が欠かせないので、5者が 0.2 ずつ。
    expect(law.game.vetoShare).toBeCloseTo(0.2, 10);
    expect(law.game.voteShare).toBeCloseTo(0.2, 10);
    expect(law.game.party.median).toBe(200);
    expect(law.game.unidentified.median).toBe(400);
    const first = data.members.find(m => m.name === '甲')!;
    // 甲 −200＋80、乙 −200＋80 で同じ純額。並びは名前順、0円の戊が最後。
    expect(data.members.map(m => m.net.median)).toEqual([-120, -120, 0]);
    expect(first.laws.find(l => l.lawId === '衆法-1-1')!.share.median).toBe(200);
    expect(first.laws.find(l => l.lawId === '衆法-1-2')!.share.median).toBe(80);
    const second = data.members.find(m => m.name === '乙')!;
    expect(second.laws.find(l => l.lawId === '衆法-1-1')!.share.median).toBe(200);
    expect(second.laws.find(l => l.lawId === '衆法-1-1')!.context.map(e => e.action)).toEqual(['question']);
    const zero = data.members.find(m => m.name === '戊')!;
    expect(zero.net.median).toBe(0);
    expect(data.members.some(m => m.name === '丙')).toBe(false);
    expect(law.confidence).toContain('未測定');
    expect(data.laws[1].confidence).toContain('下限');
    expect(law.attributed.median + law.game.party.median + law.game.unidentified.median).toBe(1000);
    expect(data.counts).toMatchObject({ members: 3, zero: 1, excluded: 1 });
  });

  it('同じ氏名の別人は人物IDで分け、人物IDが無い行は氏名に戻る', () => {
    const idHeader = `${header},人物ID`;
    const idRow = (law: string, name: string, id: string, action: string) => `${row(law, name, action, 'other')},${id}`;
    const data = buildMembers({ ...input([]), involvements: [idHeader,
      idRow('衆法-1-1', '甲', '甲（衆・東京1）', 'decide'), idRow('衆法-1-1', '甲', '甲（参・比例）', 'vote'), idRow('衆法-1-1', '乙', '', 'vote')].join('\n') });
    expect(data.members.map(m => [m.id, m.name]).sort()).toEqual([['乙', '乙'], ['甲（参・比例）', '甲'], ['甲（衆・東京1）', '甲']].sort());
    expect(data.laws[0].game.names).toMatchObject({ proposers: ['甲（衆・東京1）'], voters: ['甲（参・比例）', '乙'] });
    // 同じ氏名でも、それぞれの人の行動だけがその人の欄に入る。
    const house = data.members.find(m => m.id === '甲（衆・東京1）')!;
    expect(house.laws[0].evidence.map(e => e.action)).toEqual(['decide']);
    expect(data.members.find(m => m.id === '甲（参・比例）')!.laws[0].evidence.map(e => e.action)).toEqual(['vote']);
  });

  it('同じ観測を共有する法律は、観測の額を本数で割ってから配る（同じ差を二重に数えない）', () => {
    const shared = {
      ...input([row('衆法-1-1', '甲', 'decide', 'other'), row('衆法-1-4', '甲', 'decide', 'other'), row('衆法-1-1', '乙', 'vote', 'other'), row('衆法-1-4', '乙', 'vote', 'other')]),
      publish: publish + '\n衆法-1-4,同じ観測の法律,国賊側（悪影響）,中央値=1000;第1四分位=800;第3四分位=1200,,R4,公開可,',
      loss: loss + '\n衆法-1-4,1000,,G1',
      enacted: enacted + '\n衆法,1,4,https://www.shugiin.go.jp/x/4.htm',
      votes: votes + '\n衆法-1-4,4,2018-01-01,3,1,https://www.sangiin.go.jp/v/4.htm',
    };
    const data = buildMembers(shared);
    const laws = data.laws.filter(l => l.group === 'G1');
    expect(laws.map(l => [l.id, l.amount.median, l.observationLaws, allocatedAmount(l).median])).toEqual([['衆法-1-1', 1000, 2, 500], ['衆法-1-4', 1000, 2, 500]]);
    for (const law of laws) expect(law.attributed.median + law.game.party.median + law.game.unidentified.median).toBe(500);
    // 公開ランキングに残った法律だけを数える（出典チェックで外した法律は共有本数に入れない）。
    expect(buildMembers({ ...shared, listed: ['衆法-1-1', '衆法-1-2'] }).laws.find(l => l.id === '衆法-1-1')!.observationLaws).toBe(1);
    // 同じ観測グループ・同じ中央値でも、期間が違えば別の観測として数える。
    const other = buildMembers({ ...shared, publish: shared.publish.replace('衆法-1-4,同じ観測の法律,国賊側（悪影響）,中央値=1000;第1四分位=800;第3四分位=1200', '衆法-1-4,同じ観測の法律,国賊側（悪影響）,中央値=1000;第1四分位=800;第3四分位=1200（円、2014〜2019年の6年）') });
    expect(other.laws.filter(l => l.group === 'G1').map(l => l.observationLaws)).toEqual([1, 1]);
    const first = data.members.find(m => m.name === '甲')!;
    // 2本で同じ観測を共有するので、甲の損失は観測の額 1000 の 0.2（1本分のときと同じ）。
    expect(first.loss.median).toBe(200);
    // つまみの初期値以外でも、配る額は分けた額から計算する。
    const adjusted = adjustMembers(data, { ...DEFAULT_KNOBS, proposer: 2 });
    for (const m of adjusted) for (const e of m.laws) expect(e.share.median).toBeLessThanOrEqual(500);
  });

  it('コロナ期と分離できない法律（R3）は配らない', () => {
    const data = buildMembers({ ...input([row('衆法-1-1', '甲', 'decide', 'other'), row('衆法-1-2', '甲', 'decide', 'other')]),
      publish: publish.replace(',,R4,公開不可,未測定', ',,R3,公開不可,コロナ') });
    expect(data.laws.map(l => l.id)).toEqual(['衆法-1-2']);
  });

  it('閣法の提出者（担当の大臣）の分は役職の帳簿に置き、点数に入れない', () => {
    const cabinet = (t: string) => t.replace(/衆法-1-1/g, '閣法-1-1');
    const data = buildMembers({ ...input([row('衆法-1-1', '甲', 'decide', 'minister_or_party_exec'), row('衆法-1-1', '乙', 'vote', 'other')].map(cabinet)),
      publish: cabinet(publish), loss: cabinet(loss), votes: cabinet(votes), enacted: enacted.replace('衆法,1,1,', '閣法,1,1,') });
    const minister = data.members.find(m => m.name === '甲')!;
    expect(minister.loss.median).toBe(0);
    expect(minister.office.loss.median).toBe(200);
    expect(minister.laws[0].office.median).toBe(200);
    expect(data.laws[0].game.cabinet).toBe(true);
    // 配った額の合計（役職の帳簿を含む）は法律の額のまま。
    expect(data.laws[0].attributed.median + data.laws[0].game.party.median + data.laws[0].game.unidentified.median).toBe(1000);
    // つまみで担当の大臣の分を点数に入れられる。
    expect(adjustMembers(data, { ...DEFAULT_KNOBS, office: true }).find(m => m.name === '甲')!.loss.median).toBe(200);
    expect(adjustMembers(data, { ...DEFAULT_KNOBS, rate: 0.5 }).find(m => m.name === '甲')!.loss.median).toBe(0);
  });

  it('参議院本会議で反対した人には、賛成1票と同じ割合を向きを逆にして配る', () => {
    const opposing = ['法律ID,投票ID,氏名,人物ID,証拠URL,算入,除外理由',
      '衆法-1-1,1,丁,丁,https://www.sangiin.go.jp/v/1.htm,はい,', '衆法-1-2,2,丁,丁,https://www.sangiin.go.jp/v/2.htm,はい,',
      '衆法-1-2,2,己,,https://www.sangiin.go.jp/v/2.htm,いいえ,同姓同名で人物を決められない'].join('\n');
    const data = buildMembers({ ...input([row('衆法-1-1', '甲', 'decide', 'other'), row('衆法-1-2', '甲', 'decide', 'other')]), opposing });
    const no = data.members.find(m => m.name === '丁')!;
    // 損失の法律（1000）に反対 → 国士側に 1000×0.2、便益の法律（400）に反対 → 国賊側に 400×0.2。
    expect(no.credit.median).toBe(200);
    expect(no.loss.median).toBe(80);
    expect(no.laws.map(l => [l.lawId, l.direction, l.effect])).toEqual([['衆法-1-1', 'against', 'good'], ['衆法-1-2', 'against', 'bad']]);
    expect(no.laws[0].evidence[0].url).toBe('https://www.sangiin.go.jp/v/1.htm');
    expect(data.members.some(m => m.name === '己')).toBe(false);
    // 反対票は法律の額の配分（合計1）とは別に数える。
    expect(data.laws[0].attributed.median + data.laws[0].game.party.median + data.laws[0].game.unidentified.median).toBe(1000);
    expect(data.laws[0].game.names.opposers).toEqual(['丁']);
  });

  it('数える行動に一次資料の URL が無ければ止める', () => {
    expect(() => buildMembers(input([row('衆法-1-1', '甲', 'decide', 'other', 'はい', 'https://example.com/a')]))).toThrow('一次資料');
  });

  it('確かさの印', () => {
    expect(confidenceLabel('R4', '')).toContain('未測定');
    expect(confidenceLabel('R6', '中央値=1')).toBe('公開判定どおり');
  });
});
