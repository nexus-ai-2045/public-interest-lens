import { describe, expect, it } from 'vitest';
import { allocatable, allocateAll, allocateExact, applyVariant, distributeLargestRemainder, lawTotals, parseAmount, personTotals, rankSensitivity, ranks, toLossCredit, type Law } from './allocation-batch';
import { allocateLoss, type Involvement } from './loss-rule';

// 名前はすべて架空。
const url = 'https://example.test/minutes/1';
const lossLaw: Law = { lawId: '閣法-1-1', title: '架空の規制法案', side: 'loss', publishable: false, group: 'G-1', amount: { low: 800, median: 1000, high: 1200 } };
const benefitLaw: Law = { lawId: '衆法-1-2', title: '架空の解禁法案', side: 'benefit', publishable: true, group: 'H-1', amount: { low: -1200, median: -1000, high: -600 } };
const inv = new Map<string, Involvement[]>([
  ['閣法-1-1', [
    { personId: '甲野太郎', action: 'decide', position: 'minister_or_party_exec', evidenceUrl: url },
    { personId: '乙川花子', action: 'chair', position: 'vice_minister_or_chair', evidenceUrl: url },
    { personId: '乙川花子', action: 'vote', position: 'vice_minister_or_chair', evidenceUrl: url },
    { personId: '丙山次郎', action: 'vote', position: 'other', evidenceUrl: url },
    { personId: '丁田三郎', action: 'question', position: 'other', evidenceUrl: '' },
  ]],
  ['衆法-1-2', [
    { personId: '丙山次郎', action: 'amend', position: 'other', evidenceUrl: url },
    { personId: '戊井四郎', action: 'vote', position: 'prime_minister', evidenceUrl: url },
  ]],
]);
const laws = [lossLaw, benefitLaw];

describe('allocation-v1', () => {
  it('publish.csv の額の書き方を読む', () => {
    expect(parseAmount('便益：中央値=-19;第1四分位=-22;第3四分位=-9（円）')).toEqual({ median: -19, low: -22, high: -9 });
    expect(parseAmount('保留')).toBeNull();
  });

  it('基準の変種は allocateLoss と同じ重み・順で、1円以内の差だけ', () => {
    const rows = allocateAll(laws, inv).filter(r => r.lawId === '閣法-1-1' && r.variant === 'base' && r.rate === 0.5);
    const direct = allocateLoss(lossLaw.amount, inv.get('閣法-1-1')!, 0.5);
    expect(rows.map(r => [r.personId, r.weight])).toEqual(direct.map(a => [a.personId, a.weight]));
    rows.forEach((r, i) => expect(Math.abs(r.share.median - direct[i].shareYen.median)).toBeLessThanOrEqual(1));
    // 甲野 5×2=10、乙川 3×1.5=4.5（最大の行動だけ）、丙山 1、丁田は証拠URLが無いので数えない。
    expect(direct.map(a => [a.personId, a.weight])).toEqual([['甲野太郎', 10], ['乙川花子', 4.5], ['丙山次郎', 1]]);
  });

  it('行動重視は立場の重みを1に、立場重視は行動の重みを1にする', () => {
    const l = inv.get('閣法-1-1')!;
    expect(allocateLoss(lossLaw.amount, applyVariant(l, 'action_only'), 0.5).map(a => a.weight)).toEqual([5, 3, 1]);
    expect(allocateLoss(lossLaw.amount, applyVariant(l, 'position_only'), 0.5).map(a => a.weight)).toEqual([2, 1.5, 1]);
  });

  it('帰属額と未帰属額の合計は元の額に戻る', () => {
    const totals = lawTotals(laws, allocateAll(laws, inv));
    for (const t of totals) {
      const law = laws.find(l => l.lawId === t.lawId)!;
      expect(t.attributed.median + t.unattributed.median).toBe(law.amount.median);
      expect(t.attributed.median).toBe(Math.round(law.amount.median * t.rate));
      expect(t.attributed.low).toBe(Math.round(law.amount.low * t.rate));
      expect(t.attributed.high).toBe(Math.round(law.amount.high * t.rate));
    }
  });

  it('便益は正の貢献にし、幅の小さい方を low にする', () => {
    expect(toLossCredit('benefit', { low: -300, median: -250, high: -150 })).toEqual({ loss: { low: 0, median: 0, high: 0 }, credit: { low: 150, median: 250, high: 300 } });
  });

  it('人ごとの純額・公開不可への依存・順位', () => {
    const totals = personTotals(laws, allocateAll(laws, inv));
    const hei = totals.find(t => t.personId === '丙山次郎' && t.variant === 'base' && t.rate === 0.5)!;
    expect(hei.laws.sort()).toEqual(['衆法-1-2', '閣法-1-1']);
    expect(hei.nonPublishableLaws).toEqual(['閣法-1-1']);
    expect(hei.net.median).toBe(hei.credit.median - hei.loss.median);
    expect(hei.net.low).toBe(hei.credit.low - hei.loss.high);
    const r = ranks(totals, 'base', 0.5);
    expect(r.get('甲野太郎')).toBe(1);
    expect(rankSensitivity(totals).every(x => x.flagged === x.maxMove >= 5)).toBe(true);
  });

  it('最大剰余法：合計がぴったり一致し、負の額でも符号を保つ', () => {
    const items = [{ personId: 'あ', weight: 1 }, { personId: 'い', weight: 1 }, { personId: 'う', weight: 1 }];
    const d = distributeLargestRemainder(100, items);
    expect([...d.values()].reduce((a, b) => a + b, 0)).toBe(100);
    expect([...d.values()].sort()).toEqual([33, 33, 34]);
    expect(d.get('あ')).toBe(34); // 余りが同じなら氏名順
    const n = distributeLargestRemainder(-100, items);
    expect([...n.values()].reduce((a, b) => a + b, 0)).toBe(-100);
    expect(distributeLargestRemainder(10, [{ personId: 'あ', weight: 4.5 }, { personId: 'い', weight: 1 }]).get('あ')).toBe(8);
    expect(distributeLargestRemainder(5, []).size).toBe(0);
  });

  it('多数の関与者でも、各法律・変種・帰属率の配分合計が帰属額と一致する', () => {
    const many: Involvement[] = Array.from({ length: 213 }, (_, i) => ({ personId: `架空${String(i).padStart(3, '0')}`, action: i % 7 === 0 ? 'question' : 'vote', position: i % 11 === 0 ? 'minister_or_party_exec' : 'other', evidenceUrl: url }));
    const amount = { low: -22263659558556, median: -19446249328385, high: -9405880918004 };
    for (const rate of [0.3, 0.5, 0.7]) {
      const rows = allocateExact(amount, many, rate);
      expect(rows.reduce((s, r) => s + r.share.median, 0)).toBe(Math.round(amount.median * rate));
      expect(rows.reduce((s, r) => s + r.share.low, 0)).toBe(Math.round(amount.low * rate));
      expect(rows.reduce((s, r) => s + r.share.high, 0)).toBe(Math.round(amount.high * rate));
    }
  });
});

describe('参考の行（貸出残高）と確かさ低の行（段階1）は配分しない', () => {
  const referenceLaw: Law = { ...lossLaw, lawId: '閣法-1-3', reference: true, publishable: false };
  const withRef = new Map(inv).set('閣法-1-3', [{ personId: '甲野太郎', action: 'decide', position: 'prime_minister', evidenceUrl: url }]);

  it('allocatable は参考の行を除く', () => {
    expect(allocatable([lossLaw, referenceLaw, benefitLaw]).map(l => l.lawId)).toEqual(['閣法-1-1', '衆法-1-2']);
  });

  it('allocatable は確かさ低（段階1）の行も除く。公開可でも配分しない', () => {
    const low: Law = { ...lossLaw, lawId: '閣法-1-4', lowConfidence: true, publishable: true };
    expect(allocatable([lossLaw, low, benefitLaw]).map(l => l.lawId)).toEqual(['閣法-1-1', '衆法-1-2']);
    expect(allocateAll([low], new Map([['閣法-1-4', inv.get('閣法-1-1') ?? []]]))).toEqual([]);
  });

  it('allocateAll は参考の行の関与があっても行を作らず、人ごとの合計にも入らない', () => {
    const all = [lossLaw, referenceLaw, benefitLaw];
    const rows = allocateAll(all, withRef);
    expect(rows.some(r => r.lawId === '閣法-1-3')).toBe(false);
    expect(rows).toEqual(allocateAll(laws, inv));
    expect(personTotals(all, rows).every(p => !p.laws.includes('閣法-1-3'))).toBe(true);
    expect(lawTotals(all, rows).some(t => t.lawId === '閣法-1-3')).toBe(false);
  });
});
