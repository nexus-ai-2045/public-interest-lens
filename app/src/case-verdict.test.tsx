import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { computeCaseVerdict, TABLE1_NPL_RATIO } from './case-verdict';
import { CaseVerdictView } from './CaseVerdictPanel';

describe('金融再生プログラムの判定結果（公開表示用）', () => {
  it('判定ルールの版・影響段階1・人物ごとの点数と保留を、既存の関数から算出する', async () => {
    const v = await computeCaseVerdict();
    expect(v.judgement).toMatchObject({ ruleVersion: 'impact-rule-v1', stage: 1, direction: 'benefit' });
    expect(v.judgement.effect).toBeCloseTo(-2.6565, 4);
    expect(v.judgement.spread).toBeCloseTo(1.280519, 5);
    const by = (id: string) => v.persons.find(p => p.personId === id)!;
    expect(by('takenaka-heizo')).toMatchObject({ status: 'scored', score: 1, direction: 'benefit' });
    expect(by('ito-fsa')).toMatchObject({ status: 'held', score: null, heldReason: '人物照合が未検証です' });
    expect(by('okamoto-fsa')).toMatchObject({ status: 'held', score: null });
  });

  it('差の差は記録された公表値（8.4→2.9、8.0→5.5）から計算し、−3.0ポイントになる', async () => {
    const v = await computeCaseVerdict();
    expect(TABLE1_NPL_RATIO).toMatchObject({ major: { from: 8.4, to: 2.9 }, regional: { from: 8.0, to: 5.5 } });
    expect(v.table1).toEqual({ majorChange: -5.5, regionalChange: -2.5, diffInDiff: -3 });
    expect(v.series.preYears).toBe(5);
  });

  it('画面は段階・版・点数・保留・式・限界を出し、「採点済みではない」とは言わない', async () => {
    const verdict = await computeCaseVerdict();
    const html = renderToStaticMarkup(<CaseVerdictView verdict={verdict} />);
    for (const text of ['影響段階 1（限定的）', 'impact-rule-v1', '竹中平蔵', '+1点（貢献）', '保留（在職記録が未確認のため保留', '伊藤',
      '差の差の式', '8.4%→2.9%', '8.0%→5.5%', '−3.0pt', '−2.66pt', '帳簿上の不良債権比率', '経済全体（GDP・貸出・雇用）への効果は確立していません', '戻り', '独立検証と原本の読み戻しは未実施']) expect(html).toContain(text);
    expect(html).not.toContain('採点済みではありません');
    expect(html).not.toContain('まだ人物の点数には加算していません');
  });

  it('保留の人物に点数を出さない', async () => {
    const verdict = await computeCaseVerdict();
    const html = renderToStaticMarkup(<CaseVerdictView verdict={verdict} />);
    expect(html).not.toMatch(/伊藤[^<]*<\/strong>：[^<]*点/);
  });
});
