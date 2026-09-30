import type { PersonSummary as PersonSummaryData } from './person-summary';

export function PersonSummary({ summary, context }: { summary: PersonSummaryData; context: string }) {
  const score = (value: number | null) => value === null ? '未評価' : value.toFixed(2);
  return <section className="person-summary-overview" aria-label="両面評価">
    <h3>収録範囲の両面評価</h3>
    <p className="fine-note">{context}</p>
    <dl className="summary-scores">
      <div className="summary-score benefit" data-evaluated={summary.benefit !== null}><dt>貢献点</dt><dd>{score(summary.benefit)}</dd></div>
      <div className="summary-score harm" data-evaluated={summary.harm !== null}><dt>悪影響点</dt><dd>{score(summary.harm)}</dd></div>
    </dl>
    <p className="summary-trend" data-trend={summary.trend}>収録範囲の傾向：{summary.label}</p>
    <p className="fine-note">両面は独立した点数です。差し引き総合点や人格評価ではありません。未評価は影響なしを意味しません。</p>
  </section>;
}
