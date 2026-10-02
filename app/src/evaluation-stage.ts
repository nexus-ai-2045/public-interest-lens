import type { EvidenceEvaluationResult } from './evidence-evaluation';

export type EvaluationStage = { kind: 'unloaded' | 'matching' | 'held' | 'saved'; label: string; explanation: string };

/** 保存JSONの状態から読込・計算の段階だけを導出します。公開承認や独立検証の成功は導出しません。 */
export function evaluationStage(result: EvidenceEvaluationResult | null): EvaluationStage {
  if (!result) return { kind: 'unloaded', label: '実評価データ未読込', explanation: '保存した非公開実評価版のファイルを開くと、人物・行動・根拠を確認できます。' };
  if (!result.rows.length) return { kind: 'matching', label: '人物・行動の照合待ち', explanation: '照合済みの人物と行動がまだ表示用の評価版にありません。人間の公開レビューを待っている状態ではありません。' };
  if (!result.coverage.assessedActions || !result.rows.some(row => row.score !== null)) return { kind: 'held', label: '根拠不足・評価保留', explanation: '収録された人物や行動は確認できますが、採点に必要な照合・引用・影響根拠が揃っていません。未評価を0点にはしません。' };
  return { kind: 'saved', label: '保存評価版・独立検証要確認', explanation: '保存された機械計算を表示しています。ファイルのハッシュ一致だけでは、人物照合・独立検証・公開承認を証明できません。' };
}
