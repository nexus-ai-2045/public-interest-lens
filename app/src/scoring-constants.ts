/**
 * 点数設計 v2.1 の固定定数（設計確定 v2.1 §2）。ここが唯一の置き場所。
 *
 * - 設定ファイル・環境変数・画面からは変えられない。変えるときは method-spec の版を上げて、この値を直す（理由と影響を ADR に書く）。
 * - 的中率の合格線は、つまみにすると通りやすい値に合わせて調整してしまうため固定する。値を変える場合もここ1か所だけ。
 */
export const SCORING_CONSTANTS = Object.freeze({
  /** 符号の的中率の合格線。最終評価用の標本で1回だけ測る。 */
  hitRateFloor: 0.8,
  /**
   * 関与法律数の下限。未満の人は点を出さず、群と本数だけを出す。
   * 因果の点では「法律単位の額を持つ関与法律」の本数、曝露ランキングでは法律単位の額を作らないので「関与した法律」の本数として使う（設計決定0028 の決定8。値は同じ）。
   */
  minContributingLaws: 5,
  /** 上位3本の占有率の上限。超える人（1本で決まる人）は点を出さない。 */
  topThreeShareCap: 0.5,
  /** 順位と配分に使う確かさの下限。低・参考は使わない。 */
  certaintyFloor: '中',
} as const);

const RANK: Record<string, number> = { 参考: 0, 低: 1, 中: 2, 高: 3 };

/** 確かさの印が下限（中）以上か。未知の印は通さない。 */
export function meetsCertaintyFloor(certainty: string): boolean {
  return (RANK[certainty] ?? -1) >= RANK[SCORING_CONSTANTS.certaintyFloor];
}
