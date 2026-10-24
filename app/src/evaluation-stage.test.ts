import { describe, expect, it } from 'vitest';
import type { EvidenceEvaluationResult } from './evidence-evaluation';
import { evaluationStage } from './evaluation-stage';

function result(scores: (number | null)[], assessedActions = 0): EvidenceEvaluationResult {
  return { mode: 'real', rows: scores.map((score, index) => ({ person: { id: `p${index}`, name: '試験人物' }, score, rank: score === null ? null : index + 1, eligibleCount: 0, heldCount: 0, contributions: [] })), held: [], coverage: { inputActions: 0, assessedActions, readableMaterials: 0 }, publicationStatus: 'requires_human_review' };
}
describe('実評価画面の段階表示', () => {
  it('読込前にはレビュー待ちを表示しません', () => expect(evaluationStage(null).kind).toBe('unloaded'));
  it('人物が0件なら照合待ちです', () => expect(evaluationStage(result([])).kind).toBe('matching'));
  it('採用行動0件または全員未評価なら保留です', () => {
    expect(evaluationStage(result([1], 0)).kind).toBe('held');
    expect(evaluationStage(result([null], 1)).kind).toBe('held');
  });
  it('評価可能な0点を未評価とは扱いません', () => expect(evaluationStage(result([0], 1)).kind).toBe('saved'));
  it('保存点数やpublicationStatusから公開レビュー待ちへ昇格しません', () => {
    expect(evaluationStage(result([1, null], 1)).label).toBe('保存評価版・独立検証要確認');
    expect(evaluationStage(result([1], 1)).label).not.toContain('レビュー待ち');
  });
});
