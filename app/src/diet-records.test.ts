import { describe, expect, it } from 'vitest';
import { blocOf, kanjiNumber, normName, parseProposer, pickVote, warekiDate } from './diet-records';

describe('国会の記録を読む', () => {
  it('提出者の欄を代表者と人数に分け、氏名の空白・敬称・脚注の印を取る', () => {
    expect(parseProposer('熊代 昭彦君外四名')).toEqual({ lead: '熊代昭彦', others: 4 });
    expect(parseProposer('島村 宜伸君外十二名')).toEqual({ lead: '島村宜伸', others: 12 });
    expect(parseProposer('山田 太郎君')).toEqual({ lead: '山田太郎', others: 0 });
    expect(kanjiNumber('二十三')).toBe(23);
    expect(normName('鈴木　一郎君')).toBe('鈴木一郎');
    expect(normName('安住 淳*')).toBe('安住淳');
  });
  it('成立した日の投票から、題名が一致して可決したものを1つ選ぶ', () => {
    const v = (id: string, name: string, y = 200, n = 10) => ({ 投票ID: id, 議案名: name, 集計_賛成: String(y), 集計_反対: String(n) });
    expect(pickVote('商法等の一部を改正する法律案', [v('a', '日程第３ 商法等の一部を改正する法律案（内閣提出）'), v('b', '日程第４ 商法等の一部を改正する法律の施行に伴う関係法律の整備に関する法律案（内閣提出）')])?.投票ID).toBe('a');
    expect(pickVote('X法案', [v('a', 'X法案「修正案」', 50, 150), v('b', 'X法案「原案」')])?.投票ID).toBe('b');
    expect(pickVote('X法案', [])).toBeNull();
  });
  // 既知の不具合。題名の部分一致で、より長い法案の可決票を返す。直すとこのテストは成功し、it.fails のままでは赤になる。
  it.fails('短い題名は、より長い法案の可決票に一致しない', () => {
    const v = (id: string, name: string) => ({ 投票ID: id, 議案名: name, 集計_賛成: '200', 集計_反対: '10' });
    expect(pickVote('旅行業法の一部を改正する法律案', [
      v('long', '日程第１ 通訳案内士法及び旅行業法の一部を改正する法律案（内閣提出）'),
    ])).toBeNull();
  });
  // 既知の不具合。漢数字「百」を 0 人にして、名前のある代表が発議枠を総取りする。直すとこのテストは成功し、it.fails のままでは赤になる。
  it.fails('「外百名」を0人にしない', () => {
    expect(parseProposer('山田太郎君外百名')).toEqual({ lead: '山田太郎', others: 100 });
  });
  // 既知の不具合。全角数字を 0 人にして、名前のある代表が発議枠を総取りする。直すとこのテストは成功し、it.fails のままでは赤になる。
  it.fails('全角の「外２名」を0人にしない', () => {
    expect(parseProposer('山田太郎君外２名')).toEqual({ lead: '山田太郎', others: 2 });
  });
  it('和暦の日付を西暦にする', () => {
    expect(warekiDate('平成30年 4月18日')).toBe('2018-04-18');
    expect(warekiDate('令和元年 5月 1日')).toBe('2019-05-01');
    expect(warekiDate('')).toBe('');
  });
  it('会派名を系統に寄せる（国民民主・立憲・社民を民主系や社民と取り違えない）', () => {
    expect(blocOf('自由民主党・国民の声')).toBe('自民');
    expect(blocOf('国民民主党・新緑風会')).toBe('国民民主');
    // 希望の会（自由党・社民党、2019年）は社民党の会派ではない。ほかの会派に名前が入るもの（立憲民主党・民友会・希望の会）は元の系統のまま。
    expect(blocOf('希望の会（自由・社民）')).toBe('その他');
    expect(blocOf('立憲民主党・民友会・希望の会')).toBe('立憲');
    expect(blocOf('立憲民主・社民')).toBe('立憲');
    expect(blocOf('社会民主党・護憲連合')).toBe('社民');
    expect(blocOf('民主党・新緑風会')).toBe('民主系');
    expect(blocOf('みんなの党')).toBe('その他');
    expect(blocOf('中道改革連合・無所属')).toBe('中道改革連合');
    expect(blocOf('チームみらい・無所属の会')).toBe('チームみらい');
    expect(blocOf('日本保守党')).toBe('日本保守党');
  });
});
