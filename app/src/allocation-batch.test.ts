import { describe, expect, it } from 'vitest';
import { allocateAll, applyVariant, lawTotals, parseAmount, personTotals, rankSensitivity, ranks, toLossCredit, type Law } from './allocation-batch';
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

  it('基準の変種は allocateLoss をそのまま呼んだ結果と同じ', () => {
    const rows = allocateAll(laws, inv).filter(r => r.lawId === '閣法-1-1' && r.variant === 'base' && r.rate === 0.5);
    const direct = allocateLoss(lossLaw.amount, inv.get('閣法-1-1')!, 0.5);
    expect(rows.map(r => [r.personId, r.weight, r.share])).toEqual(direct.map(a => [a.personId, a.weight, a.shareYen]));
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
      expect(Math.abs(t.attributed.median - law.amount.median * t.rate)).toBeLessThanOrEqual(t.persons);
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
});
