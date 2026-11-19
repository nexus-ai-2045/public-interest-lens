// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { INDUSTRY_NAMES, exposureGroupNames, industryName, normalizeReading } from './exposure-labels';
import { personReadingsOf } from './exposure-inputs';

describe('曝露ランキングの表示名と読み', () => {
  it('群のデータにある産業の記号は、全部日本語の名前になる', () => {
    const csv = readFileSync(fileURLToPath(new URL('../../data/derived/exposure-v1/industry-year.csv', import.meta.url)), 'utf8');
    const codes = new Set<string>(csv.trim().split('\n').slice(1).map(line => line.split(',')[0]));
    expect(codes.size).toBeGreaterThan(10);
    for (const code of codes) expect(INDUSTRY_NAMES[code], code).toBeTruthy();
    expect(industryName('不明')).toBe('不明');
  });

  it('内訳の ID（産業）は産業名、未配分の ID（産業×年）は「産業名（年）」にする', () => {
    expect(exposureGroupNames([{ id: 'A|1998', group: 'A', window: '1998年' }, { id: 'M+N|2005', group: 'M+N', window: '2005年' }])).toEqual({
      A: '農林水産業', 'A|1998': '農林水産業（1998年）', 'M+N': '専門・科学技術、業務支援サービス', 'M+N|2005': '専門・科学技術、業務支援サービス（2005年）',
    });
  });

  it('読みは空白を除いたひらがなだけ。それ以外は読みなし', () => {
    expect(normalizeReading('あいさわ いちろう')).toBe('あいさわいちろう');
    expect(normalizeReading('アイサワ')).toBe('');
    expect(normalizeReading('逢沢')).toBe('');
    expect(normalizeReading('')).toBe('');
  });

  it('読みは台帳を先に使い、空なら会議録で埋め、どちらにも無い人は載せない', () => {
    const persons = '人物ID,氏名,読み,院,選挙区,別表記\n,,,,,\n甲,甲,こう いち,衆議院,,\n乙,乙,,,,\n丙,丙,,,,\n';
    const kokkai = '人物ID,氏名,読み,一致した発言数,理由,出典URL,取得日時\n甲,甲,ちがう,1,,,\n乙,乙,おつ,3,,,\n丙,丙,,0,一致なし,,\n';
    expect(personReadingsOf(persons, kokkai, ['甲', '乙', '丙', '丁'])).toEqual({ 甲: 'こういち', 乙: 'おつ' });
  });
});
