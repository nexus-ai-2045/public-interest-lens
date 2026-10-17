import { describe, expect, it } from 'vitest';
import { buildMembers, confidenceLabel } from './members-build';

const header = '法律ID,題名,氏名,氏名_原表記,院,行動,当時の肩書,立場区分,立場の根拠,日付,証拠URL,系統A,系統B,参院本会議の賛否,算入,除外理由';
const row = (law: string, name: string, action: string, position: string, counted = 'はい', url = 'https://kokkai.ndl.go.jp/txt/1/1') => `${law},題,${name},${name},参議院,${action},,${position},,2018-01-01,${url},,,,${counted},`;
const publish = ['id,題名,側,損失または便益,便益の状態,判定表の行,公開可否,理由',
  '閣法-1-1,損の法律,国賊側（悪影響）,中央値=1000;第1四分位=800;第3四分位=1200,,R3,公開不可,コロナ',
  '閣法-1-2,益の法律,国士側（貢献）,下限：中央値=-400;第1四分位=-600;第3四分位=-200,,R6,公開可,',
  '閣法-1-3,参考の法律,国賊側（悪影響）,中央値=999;第1四分位=999;第3四分位=999,,R1,公開不可,参考'].join('\n');
const loss = ['id,損失または便益の額,参考フラグ,観測グループ', '閣法-1-1,1000,,G1', '閣法-1-2,-400,,G2', '閣法-1-3,999,参考,G1'].join('\n');
const enacted = ['種別,提出回次,番号,経過URL', ...['1', '2', '3'].map(n => `閣法,1,${n},https://www.shugiin.go.jp/x/${n}.htm`)].join('\n');

const input = (rows: string[]) => ({ involvements: [header, ...rows].join('\n'), publish, loss, enacted });

describe('議員ページのデータ', () => {
  it('額×帰属率×重み÷重みの合計で配り、純額の小さい順に並べる', () => {
    const data = buildMembers(input([
      row('閣法-1-1', '甲', 'decide', 'minister_or_party_exec'),
      row('閣法-1-1', '乙', 'vote', 'other'),
      row('閣法-1-1', '乙', 'question', 'other'),
      row('閣法-1-2', '乙', 'vote', 'other'),
      row('閣法-1-1', '丙', 'vote', 'other', 'いいえ'),
      row('閣法-1-3', '甲', 'decide', 'other'),
    ]));
    expect(data.laws.map(l => l.id)).toEqual(['閣法-1-1', '閣法-1-2']);
    const [first, second] = data.members;
    expect(first.name).toBe('甲');
    // 1000 × 0.5 × 10 ÷ (10 + 2)
    expect(first.laws[0].share.median).toBe(417);
    expect(first.net.median).toBe(-417);
    expect(second.name).toBe('乙');
    expect(second.laws.find(l => l.lawId === '閣法-1-1')!.weight).toBe(2);
    expect(second.credit.median).toBe(200);
    expect(data.members.some(m => m.name === '丙')).toBe(false);
    expect(data.laws[0].confidence).toContain('コロナ期と重なる');
    expect(data.laws[1].confidence).toContain('下限');
    expect(data.laws[0].attributed.median).toBe(500);
    expect(data.counts).toMatchObject({ members: 2, excluded: 1 });
  });

  it('数える行動に一次資料の URL が無ければ止める', () => {
    expect(() => buildMembers(input([row('閣法-1-1', '甲', 'decide', 'other', 'はい', 'https://example.com/a')]))).toThrow('一次資料');
  });

  it('確かさの印', () => {
    expect(confidenceLabel('R4', '')).toContain('未測定');
    expect(confidenceLabel('R6', '中央値=1')).toBe('公開判定どおり');
  });
});
