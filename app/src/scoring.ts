export type AxisKey = "deliberation" | "proposals" | "transparency";
export type AxisValues = Record<AxisKey, number>;
export type EvidenceKind = "verified" | "computed" | "ai" | "unknown";

export function calculateReferenceScore(
  values: AxisValues,
  weights: AxisValues,
): number {
  const keys = Object.keys(values) as AxisKey[];
  const weightTotal = keys.reduce((sum, key) => sum + weights[key], 0);
  if (weightTotal === 0) return 0;
  const total = keys.reduce(
    (sum, key) => sum + values[key] * weights[key],
    0,
  );
  return Math.round(total / weightTotal);
}

export function evidenceLabel(kind: EvidenceKind): string {
  return {
    verified: "確認済み事実",
    computed: "機械計算",
    ai: "AI解釈",
    unknown: "未確認",
  }[kind];
}
