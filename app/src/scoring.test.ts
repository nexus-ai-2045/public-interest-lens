import { describe, expect, it } from "vitest";
import { calculateReferenceScore, evidenceLabel } from "./scoring";

describe("calculateReferenceScore", () => {
  it("重み付き平均を整数へ丸める", () => {
    expect(
      calculateReferenceScore(
        { deliberation: 80, proposals: 60, transparency: 100 },
        { deliberation: 2, proposals: 1, transparency: 1 },
      ),
    ).toBe(80);
  });

  it("軸オブジェクトのキーの並びを変えても同じ整数になる", () => {
    const values = { deliberation: 5.1, proposals: 55.2, transparency: 55.3 };
    const weights = { deliberation: 3.5, proposals: 0.25, transparency: 5.125 };
    const reversedValues = { transparency: 55.3, proposals: 55.2, deliberation: 5.1 };
    const reversedWeights = { transparency: 5.125, proposals: 0.25, deliberation: 3.5 };
    // 宣言順（deliberation, proposals, transparency）で足して四捨五入した値。
    expect(calculateReferenceScore(values, weights)).toBe(35);
    expect(calculateReferenceScore(reversedValues, reversedWeights)).toBe(35);
  });

  it("重みがすべて0なら0を返す", () => {
    expect(
      calculateReferenceScore(
        { deliberation: 80, proposals: 60, transparency: 100 },
        { deliberation: 0, proposals: 0, transparency: 0 },
      ),
    ).toBe(0);
  });
});

describe("evidenceLabel", () => {
  it.each([
    ["verified", "確認済み事実"],
    ["computed", "機械計算"],
    ["ai", "AI解釈"],
    ["unknown", "未確認"],
  ] as const)("%s を %s と表示する", (kind, label) => {
    expect(evidenceLabel(kind)).toBe(label);
  });
});
