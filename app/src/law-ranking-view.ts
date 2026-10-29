import type { Certainty, PublicRankingLaw, PublicRankingOther } from './public-distribution';

export const PAGE_SIZE = 50;

/** 確かさの表示名。参考は「貸出残高を多いほど良いとみなす機械的仮定」など、確認がとれていない額。 */
export const certaintyLabels: Record<Certainty, string> = {
  高: '高（段階3）',
  中: '中（段階2）',
  低: '低（段階1：経済全体で未確認）',
  参考: '参考（貸出残高を多いほど良いとみなす機械的仮定）',
};

/** 全体指標（macro-v1）の額の観測グループの頭。影響の段階を経ていない参考の額。 */
export const MACRO_GROUP = '全体指標';
export const isMacro = (law: PublicRankingLaw) => law.group.startsWith(MACRO_GROUP);

/** 確かな額（高・中）、確かさ低（段階1。確かな額に入れない）、参考の額、全体指標の参考の額を分ける。どれも額の大きい順。 */
export function splitLaws(laws: PublicRankingLaw[]): { confirmed: PublicRankingLaw[]; low: PublicRankingLaw[]; reference: PublicRankingLaw[]; macro: PublicRankingLaw[] } {
  const bySize = (a: PublicRankingLaw, b: PublicRankingLaw) => b.amountMedianYen - a.amountMedianYen || a.id.localeCompare(b.id);
  return {
    confirmed: laws.filter(law => law.certainty === '高' || law.certainty === '中').sort(bySize),
    low: laws.filter(law => law.certainty === '低').sort(bySize),
    reference: laws.filter(law => law.certainty === '参考' && !isMacro(law)).sort(bySize),
    macro: laws.filter(isMacro).sort(bySize),
  };
}

/** 全体指標の額を側と検索語（題名・id・分野）で絞る。 */
export function filterMacro(laws: PublicRankingLaw[], side: '' | 'loss' | 'benefit', query: string): PublicRankingLaw[] {
  const words = query.normalize('NFKC').toLowerCase().split(/\s+/u).filter(Boolean);
  return laws.filter(law => {
    if (side && law.side !== side) return false;
    const text = `${law.id} ${law.title} ${law.field}`.normalize('NFKC').toLowerCase();
    return words.every(word => text.includes(word));
  });
}

/** 結果ごとの本数（多い順）。 */
export function outcomeCounts(items: PublicRankingOther[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.outcome, (counts.get(item.outcome) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** 結果と検索語（題名・id・理由）で絞る。空白で区切った語をすべて含むものだけ残す単純な部分一致。 */
export function filterOthers(items: PublicRankingOther[], outcome: string, query: string): PublicRankingOther[] {
  const words = query.normalize('NFKC').toLowerCase().split(/\s+/u).filter(Boolean);
  return items.filter(item => {
    if (outcome && item.outcome !== outcome) return false;
    const text = `${item.id} ${item.title} ${item.reason}`.normalize('NFKC').toLowerCase();
    return words.every(word => text.includes(word));
  });
}

export function pageCount(total: number, size = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size));
}

export function pageSlice<T>(items: T[], page: number, size = PAGE_SIZE): T[] {
  const index = Math.min(Math.max(1, page), pageCount(items.length, size)) - 1;
  return items.slice(index * size, (index + 1) * size);
}
