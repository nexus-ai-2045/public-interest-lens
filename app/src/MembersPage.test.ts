import { describe, expect, it } from 'vitest';
import { filterMembers, partyLabel, signedYen, sortBlocs, topBars, visibleMembers } from './MembersPage';
import { blocOf, type PublicMember } from './members-build';

const member = (name: string, rank: number, low: number, median: number, high: number, id = name) => ({ id, name, rank, net: { low, median, high }, laws: [{}] }) as unknown as PublicMember;

it('上位の横棒は側ごとに大きい順で、幅が0をまたぐときは0から出す', () => {
  const members = [member('甲', 1, -300, -200, -100), member('乙', 2, -50, -10, 20), member('丙', 3, 5, 30, 60), member('丁', 4, 10, 90, 120)];
  expect(topBars(members, 'loss').map(b => [b.label, b.value, b.low, b.high])).toEqual([['甲', 200, 100, 300], ['乙', 10, 0, 50]]);
  expect(topBars(members, 'benefit').map(b => b.label)).toEqual(['丁', '丙']);
  expect(topBars(members, 'benefit')[0].href).toBe(`/members?name=${encodeURIComponent('丁')}`);
});

it('同じ氏名の別人は人物IDで分け、リンクは人物IDで結ぶ', () => {
  const same = '鬼木誠（衆・福岡2）';
  const members = [member('鬼木誠', 1, -300, -200, -100, same), member('鬼木誠', 2, -50, -10, -5, '鬼木誠（参・比例）')];
  const bars = topBars(members, 'loss');
  expect(bars.map(b => [b.id, b.label])).toEqual([[same, '鬼木誠'], ['鬼木誠（参・比例）', '鬼木誠']]);
  expect(bars[0].href).toBe(`/members?name=${encodeURIComponent(same)}`);
});

it('符号つきの額', () => {
  expect(signedYen(-2e11)).toBe('−2,000億円');
  expect(signedYen(0)).toBe('0円');
});

it('一覧は上から limit 人まで並べ、指された人は下でも必ず並べる', () => {
  const members = Array.from({ length: 10 }, (_, i) => member(`名${i}`, i + 1, -10, -5, -1));
  expect(visibleMembers(members, 3, '').map(m => m.id)).toEqual(['名0', '名1', '名2']);
  expect(visibleMembers(members, 3, '名7').map(m => m.id)).toEqual(['名0', '名1', '名2', '名7']);
  expect(visibleMembers(members, 10, '名7')).toBe(members);
});

describe('政党ランキング', () => {
  it('会派名を系統に寄せる（国民民主・立憲・社民を民主系や社民と取り違えない）', () => {
    expect(blocOf('自由民主党・国民の声')).toBe('自民');
    expect(blocOf('国民民主党・新緑風会')).toBe('国民民主');
    expect(blocOf('立憲民主・社民')).toBe('立憲');
    expect(blocOf('社会民主党・護憲連合')).toBe('社民');
    expect(blocOf('民主党・新緑風会')).toBe('民主系');
    expect(blocOf('みんなの党')).toBe('その他');
    expect(blocOf('中道改革連合・無所属')).toBe('中道改革連合');
    expect(blocOf('チームみらい・無所属の会')).toBe('チームみらい');
    expect(blocOf('日本保守党')).toBe('日本保守党');
  });
  it('並べ方を変えると順位が変わり、総額は参考として選べる', () => {
    const b = (bloc: string, net: number, people: number, laws: number) => ({ bloc, parties: [bloc], people, laws, yesLaws: laws, noLaws: 0, lossShareOfYes: 1, certainty: { 低: laws },
      bad: { low: 0, median: 0, high: 0 }, good: { low: 0, median: 0, high: 0 }, net: { low: net, median: net, high: net }, votes: people * laws,
      perPerson: net / people, perLaw: net / laws, perVote: net / people / laws });
    const ranking = { blocs: [b('大', -1000, 100, 10), b('小', -100, 2, 10)], from: '', to: '', unmatched: { people: 0, net: { low: 0, median: 0, high: 0 } } };
    expect(sortBlocs(ranking, 'total').map(x => x.bloc)).toEqual(['大', '小']);
    expect(sortBlocs(ranking, 'perPerson').map(x => x.bloc)).toEqual(['小', '大']);
  });
});

it('一覧の所属政党：現職は政党名、元職は参議院の最後の会派つきで「元職」、表が読めるまでは空', () => {
  const now = new Map([['甲', '自民']]);
  const last = new Map([['乙', '立憲']]);
  expect(partyLabel('甲', now, true, last)).toBe('自民');
  expect(partyLabel('乙', now, true, last)).toBe('元職・立憲');
  expect(partyLabel('丙', now, true, last)).toBe('元職');
  expect(partyLabel('甲', new Map(), false)).toBe('');
});


it('人物IDの指定は側・政党の絞り込みより優先し、解除後は元の順位一覧へ戻る', () => {
  const members = [member('甲', 1, -30, -20, -10, 'person-a'), member('乙', 2, 10, 20, 30, 'person-b')];
  const parties = new Map([['person-a', 'A'], ['person-b', 'B']]);
  expect(filterMembers(members, 'benefit', 'person-a', 'B', parties).map(m => m.id)).toEqual(['person-a']);
  expect(filterMembers(members, 'loss', 'person-b', 'A', parties).map(m => m.id)).toEqual(['person-b']);
  expect(filterMembers(members, 'benefit', '', 'B', parties).map(m => m.id)).toEqual(['person-b']);
  expect(filterMembers(members, 'benefit', '甲', '', parties)).toEqual([]);
});


it('人物リンクは算定条件と表示側を保ち、無関係なクエリを引き継がない', () => {
  const search = '?r=50&p=30&chair=1&office=1&house=voters&tone=benefit&tab=party&utm_source=share';
  const link = topBars([member('甲', 1, -30, -20, -10, 'person-a')], 'loss', 10, search)[0].href;
  const url = new URL(link!, 'https://example.test');
  expect(url.pathname).toBe('/members');
  expect(Object.fromEntries(url.searchParams)).toEqual({ name: 'person-a', p: '30', house: 'voters', chair: '1', r: '50', office: '1', tone: 'benefit' });
});
