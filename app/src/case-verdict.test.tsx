import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import caseSource from '../../data/distribution/case-source.json';
import { canonical, sha256Hex } from '../../scripts/verification_binding.mjs';
import { buildCaseEvaluationInput, FINANCIAL_REVIVAL_DRAFT, type CaseMaterialText, type CaseSource } from './case-evaluation';
import { assessmentRevision } from './evidence-evaluation';
import { computeCaseVerdict, TABLE1_NPL_RATIO, type EvidenceReceipt } from './case-verdict';
import { CaseVerdictView } from './CaseVerdictPanel';

const source = caseSource as CaseSource;

function storedTexts(change: (id: string, text: CaseMaterialText) => CaseMaterialText = (_id, text) => text): Map<string, CaseMaterialText> {
  const quotes = [...source.citations, ...FINANCIAL_REVIVAL_DRAFT.assessments.flatMap(a => a.comparison?.citations ?? [])];
  return new Map(quotes.map(c => [c.id, change(c.id, { text: `保存原本の本文。${c.quote}。後続。`, observedAt: '2026-10-09T00:00:00Z', publishedAt: null })]));
}

async function matchingReceipt(texts: Map<string, CaseMaterialText>, omit: string[] = []): Promise<EvidenceReceipt> {
  const { input } = await buildCaseEvaluationInput(source, FINANCIAL_REVIVAL_DRAFT, texts);
  return {
    inputHash: sha256Hex(canonical(input)),
    verifierId: 'case-evaluation-readback',
    verifierVersion: '1',
    resolvedPersonIds: input.people.map(p => p.id).filter(id => !omit.includes(id)),
    actionRevisions: input.actions.map(a => ({ id: a.actionId, revisionId: a.revisionId })),
    assessmentRevisions: await Promise.all(input.assessments.map(async a => ({ id: a.id, revisionId: await assessmentRevision(a) }))),
  };
}

describe('金融再生プログラムの判定結果（公開表示用）', () => {
  it('受領書が無いときは実在人物を全員保留し、指標の段階だけを出す', async () => {
    const verdict = await computeCaseVerdict();
    expect(verdict.judgement).toMatchObject({ ruleVersion: 'impact-rule-v1', stage: 1, direction: 'benefit' });
    expect(verdict.judgement.effect).toBeCloseTo(-2.6565, 4);
    expect(verdict.judgement.spread).toBeCloseTo(1.280519, 5);
    expect(verdict.persons.map(p => p.personId)).toEqual(['takenaka-heizo', 'ito-20021030', 'ito-20050525', 'okamoto-fsa']);
    expect(verdict.persons.every(p => p.status === 'held' && p.score === null && p.heldReason === '人物照合が未検証です')).toBe(true);
  });

  it('保存本文があっても受領書が無ければ加点しない', async () => {
    const verdict = await computeCaseVerdict(source, { texts: storedTexts() });
    expect(verdict.persons.every(p => p.score === null && p.heldReason === '人物照合が未検証です')).toBe(true);
  });

  it('差の差は記録された公表値（8.4→2.9、8.0→5.5）から計算し、−3.0ポイントになる', async () => {
    const verdict = await computeCaseVerdict();
    expect(TABLE1_NPL_RATIO).toMatchObject({ major: { from: 8.4, to: 2.9 }, regional: { from: 8.0, to: 5.5 } });
    expect(verdict.table1).toEqual({ majorChange: -5.5, regionalChange: -2.5, diffInDiff: -3 });
    expect(verdict.series.preYears).toBe(5);
  });

  it('一致する再読と受領書があるとき、窓内の竹中だけを1点にし、観測後と係数0は保留する', async () => {
    const texts = storedTexts();
    const verdict = await computeCaseVerdict(source, { texts, receipt: await matchingReceipt(texts) });
    const by = (id: string) => verdict.persons.find(p => p.personId === id)!;
    expect(by('takenaka-heizo')).toMatchObject({ status: 'scored', score: 1, direction: 'benefit' });
    expect(by('ito-20021030')).toMatchObject({ status: 'scored', score: 0.5, direction: 'benefit' });
    expect(by('ito-20050525')).toMatchObject({ status: 'held', score: null, heldReason: '結果観測後の行動は因果寄与へ結べません' });
    expect(by('okamoto-fsa')).toMatchObject({ status: 'held', score: null, heldReason: '行動または引用が未検証です' });
    const html = renderToStaticMarkup(<CaseVerdictView verdict={verdict} />);
    expect(html).toContain('+1点（貢献）');
    expect(html).toContain('+0.5点（貢献）');
    expect(html).toContain('結果観測後の行動は因果寄与へ結べません');
  });

  it('照合から外した候補だけを保留し、別候補と竹中は変えない', async () => {
    const texts = storedTexts();
    const verdict = await computeCaseVerdict(source, { texts, receipt: await matchingReceipt(texts, ['ito-20021030']) });
    const by = (id: string) => verdict.persons.find(p => p.personId === id)!;
    expect(by('ito-20021030')).toMatchObject({ score: null, heldReason: '人物照合が未検証です' });
    expect(by('ito-20050525')).toMatchObject({ score: null, heldReason: '結果観測後の行動は因果寄与へ結べません' });
    expect(by('takenaka-heizo').score).toBe(1);
  });

  it('同じ改訂でも inputHash が違えば加点しない', async () => {
    const texts = storedTexts();
    const receipt = await matchingReceipt(texts);
    const verdict = await computeCaseVerdict(source, { texts, receipt: { ...receipt, inputHash: 'b'.repeat(64) } });
    expect(verdict.persons.every(p => p.status === 'held' && p.score === null && p.heldReason === '人物照合が未検証です')).toBe(true);
  });

  it('検証者の識別が空なら受領書を信頼へ写さない', async () => {
    const texts = storedTexts();
    const receipt = await matchingReceipt(texts);
    const verdict = await computeCaseVerdict(source, { texts, receipt: { ...receipt, verifierId: ' ' } });
    expect(verdict.persons.find(p => p.personId === 'takenaka-heizo')).toMatchObject({ score: null, heldReason: '人物照合が未検証です' });
  });

  it('未知の人物を含む受領書は一部だけ採用しない', async () => {
    const texts = storedTexts();
    const receipt = await matchingReceipt(texts);
    const verdict = await computeCaseVerdict(source, { texts, receipt: { ...receipt, resolvedPersonIds: [...receipt.resolvedPersonIds, 'not-a-person'] } });
    expect(verdict.persons.every(p => p.score === null)).toBe(true);
  });

  it.each([
    ['観測時刻', (text: CaseMaterialText): CaseMaterialText => ({ ...text, observedAt: '2026-10-10T00:00:00Z' })],
    ['公開日', (text: CaseMaterialText): CaseMaterialText => ({ ...text, publishedAt: '2002-10-30' })],
    ['原本ハッシュ', (text: CaseMaterialText): CaseMaterialText => ({ ...text, originalHash: 'c'.repeat(64) })],
  ])('再読の%sが入力と違えば、本文が同じでも加点しない', async (_label, change) => {
    const texts = storedTexts();
    const readback = storedTexts((_id, text) => change(text));
    const verdict = await computeCaseVerdict(source, { texts, readback, receipt: await matchingReceipt(texts) });
    expect(verdict.persons.find(p => p.personId === 'takenaka-heizo')).toMatchObject({ score: null, heldReason: '行動または引用が未検証です' });
  });

  it('再読側に原本ハッシュが無く、入力側にあるときは加点しない', async () => {
    const texts = storedTexts((_id, text) => ({ ...text, originalHash: 'a'.repeat(64) }));
    const readback = storedTexts();
    const verdict = await computeCaseVerdict(source, { texts, readback, receipt: await matchingReceipt(texts) });
    expect(verdict.persons.find(p => p.personId === 'takenaka-heizo')).toMatchObject({ score: null, heldReason: '行動または引用が未検証です' });
  });

  it('同じ保存本文の入力hashは30回構築しても一つで、materialsはid順です', async () => {
    const texts = storedTexts();
    const hashes = new Set<string>();
    for (let i = 0; i < 30; i += 1) {
      const { input } = await buildCaseEvaluationInput(source, FINANCIAL_REVIVAL_DRAFT, texts);
      const ids = input.materials.map(m => m.id);
      expect(ids).toEqual([...ids].sort((a, b) => a < b ? -1 : a > b ? 1 : 0));
      expect(new Set(ids).size).toBe(ids.length);
      hashes.add(sha256Hex(canonical(input)));
    }
    expect(hashes.size).toBe(1);
    const verdict = await computeCaseVerdict(source, { texts, receipt: await matchingReceipt(texts) });
    expect(verdict.persons.find(p => p.personId === 'takenaka-heizo')).toMatchObject({ status: 'scored', score: 1, direction: 'benefit' });
  });

  it('画面の束縛hashはNodeのSHA-256と一致する', async () => {
    const cryptoModule = 'node:crypto';
    const { createHash } = await import(/* @vite-ignore */ cryptoModule);
    const nodeHash = (value: string) => createHash('sha256').update(value).digest('hex');
    for (const sample of ['', 'abc', '日本語', 'a'.repeat(55), 'a'.repeat(56), 'a'.repeat(64), 'a'.repeat(1000)]) expect(sha256Hex(sample)).toBe(nodeHash(sample));
    const texts = storedTexts();
    const { input } = await buildCaseEvaluationInput(source, FINANCIAL_REVIVAL_DRAFT, texts);
    expect(sha256Hex(canonical(input))).toBe(nodeHash(canonical(input)));
  });

  it('再読本文が保存本文と違えば、受領書があっても引用不一致で保留する', async () => {
    const texts = storedTexts();
    const readback = storedTexts(() => ({ text: '引用を含まない別本文', observedAt: '2026-10-09T00:00:00Z', publishedAt: null }));
    const verdict = await computeCaseVerdict(source, { texts, readback, receipt: await matchingReceipt(texts) });
    expect(verdict.persons.find(p => p.personId === 'takenaka-heizo')).toMatchObject({ score: null, heldReason: '行動または引用が未検証です' });
    expect(verdict.persons.every(p => p.score === null)).toBe(true);
  });

  it('引用が保存本文に無い入力は、本文として採用せず変換で止める', async () => {
    const texts = storedTexts((id, text) => id === 'ito20021030' ? { ...text, text: '引用が無い本文' } : text);
    await expect(computeCaseVerdict(source, { texts })).rejects.toThrow('保存原本の本文に見つかりません');
  });

  it('画面の初期表示は段階と保留を出し、自己採用の加点を出さない', async () => {
    const verdict = await computeCaseVerdict();
    const html = renderToStaticMarkup(<CaseVerdictView verdict={verdict} />);
    for (const text of ['影響段階 1（限定的）', 'impact-rule-v1', '竹中平蔵', '伊藤達也・金融担当副大臣', '伊藤達也・金融担当大臣', '岡本（金融危機対応室長）',
      '人物照合の受領書が無いため保留', '差の差の式', '8.4%→2.9%', '8.0%→5.5%', '−3.0pt', '−2.66pt', '帳簿上の不良債権比率', '経済全体（GDP・貸出・雇用）への効果は確立していません', '独立検証と原本の読み戻しは未実施']) expect(html).toContain(text);
    expect(html).not.toContain('伊藤（2002-10-30');
    expect(html).not.toContain('伊藤（2005-05-25');
    expect(html).not.toContain('氏名の推測はしません');
    expect(html).not.toContain('+1点');
    expect(html).not.toContain('点（貢献）');
    expect(html).not.toContain('採点済みではありません');
    expect(html).not.toContain('まだ人物の点数には加算していません');
    expect(html).not.toContain('在職記録が未確認のため保留');
  });
});
