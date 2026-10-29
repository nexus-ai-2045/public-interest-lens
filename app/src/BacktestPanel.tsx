import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { backtestUrl, foreignSignLabel, formatPercent, formatRate, parseBacktest, signLabel, type Backtest, type BacktestRun } from './backtest';

function RunView({ run }: { run: BacktestRun }) {
  const l2 = run.levels[2];
  return <section className="backtest-run" id={`backtest-${run.label}`}>
    <h4>{run.label}（{run.date}、計算式 {run.spec_version}）</h4>
    <p className="fine-note">{run.note}</p>
    <table className="spec-symbols">
      <thead><tr><th scope="col">段</th><th scope="col">条件</th><th scope="col">向きの一致</th><th scope="col">一致率（95%区間）</th><th scope="col">判定</th></tr></thead>
      <tbody>{run.levels.map(lv => <tr key={lv.level}><td>{lv.level} {lv.name}</td><td>{lv.definition}</td><td>{lv.hits}/{lv.n}</td><td>{formatRate(lv)}</td><td><strong>{lv.verdict}</strong></td></tr>)}</tbody>
    </table>
    <p>合格の線は一致率{Math.round(run.target * 100)}%以上、かつ{run.min_n}件以上。件数が足りないときは「判定不能」と書き、届いたとも届かないとも言いません。</p>
    <p>事例{run.cases_total}件のうち採点できなかった理由：{Object.entries(run.funnel.excluded_by_reason).map(([k, v]) => `${k} ${v}件`).join('、')}。</p>
    <p><strong>額の誤差・予測区間が正解を含む割合：{run.amount_and_interval.status}。</strong>{run.amount_and_interval.reason}</p>
    {run.aligned_levels && run.alignment_gap && <>
      <h5>指標をそろえた測り直し（v1.1）</h5>
      <p>研究の結果指標と同じ指標で、法律ごとの影響の判定（段階1以上）の向きを読みます。計算が判定を出していないものは外し、外れとは数えません。</p>
      <table className="spec-symbols">
        <thead><tr><th scope="col">段</th><th scope="col">条件</th><th scope="col">向きの一致</th><th scope="col">一致率（95%区間）</th><th scope="col">判定</th></tr></thead>
        <tbody>{run.aligned_levels.map(lv => <tr key={lv.level}><td>{lv.level} {lv.name}</td><td>{lv.definition}</td><td>{lv.hits}/{lv.n}</td><td>{formatRate(lv)}</td><td><strong>{lv.verdict}</strong></td></tr>)}</tbody>
      </table>
      <p>日本の研究で法律と結べた{run.alignment_gap.japan_linked_cases}件の指標の対応：{Object.entries(run.alignment_gap.by_alignment).map(([k, v]) => `${k} ${v}件`).join('、')}。計算に同じ指標が無かった事例の結果指標：{Object.entries(run.alignment_gap.none_by_outcome_class).map(([k, v]) => `${k} ${v}件`).join('、')}。{run.alignment_gap.reading}</p>
    </>}
    {run.transplant && <>
      <h5>外国の研究から日本の向きを当てる（v2）</h5>
      <p>日本の研究（向きが便益か損失で定まるもの）を正解にして、外国の同種の政策の研究だけから日本の向きを当てられるかを測ります。現行の計算は使いません。同種かどうかの判定とラベルは、日本の結果を見せない2系統が独立に付け、一致したものだけ使います。外国の研究は{run.transplant.pool.entries}件（うち使えるのは{run.transplant.pool.usable}件）です。</p>
      <table className="spec-symbols">
        <thead><tr><th scope="col">段</th><th scope="col">条件</th><th scope="col">向きの一致</th><th scope="col">一致率（95%区間）</th><th scope="col">予測を出せた割合</th><th scope="col">政策グループ</th><th scope="col">基準</th><th scope="col">判定</th></tr></thead>
        <tbody>{run.transplant.levels.map(lv => <tr key={lv.level}><td>{lv.level} {lv.name}</td><td>{lv.definition}</td><td>{lv.hits}/{lv.n}</td><td>{formatRate(lv)}</td><td>{lv.n}/{lv.targets}</td><td>{lv.groups}</td><td>{formatPercent(lv.baseline)}</td><td><strong>{lv.verdict}</strong></td></tr>)}</tbody>
      </table>
      <p>合格は一致率{Math.round(run.transplant.target * 100)}%以上、かつ予測を出せた事例が{run.transplant.min_n}件以上・政策が{run.transplant.min_groups}グループ以上。基準は、毎回最頻の向きを答えたときの一致率です。一致率が高くても件数が少なければ、また基準と同じなら、見立てに技術があるとは言いません。{run.transplant.note}</p>
      <details>
        <summary>日本の事例ごとの予測（本命T0）</summary>
        <table className="spec-symbols">
          <thead><tr><th scope="col">日本の事例</th><th scope="col">研究</th><th scope="col">正解の向き</th><th scope="col">予測</th><th scope="col">使った外国の研究（向き）</th></tr></thead>
          <tbody>{run.transplant.levels[0].cases.map(c => <tr key={c.id}><td>{c.policy.split('（')[0]}</td><td>{c.source}</td><td>{signLabel(c.truth)}</td><td>{c.predicted === null ? `出せない（${c.reason}）` : foreignSignLabel(c.predicted)}</td><td>{c.foreign.map(f => `${f.authors.split(/[,;]/)[0]} ${f.year}（${foreignSignLabel(f.sign)}）`).join('、') || '—'}</td></tr>)}</tbody>
        </table>
      </details>
    </>}
    <details>
      <summary>採点した事例（条件を緩めた参考2の{l2.n}件）</summary>
      <table className="spec-symbols">
        <thead><tr><th scope="col">事例</th><th scope="col">研究</th><th scope="col">正解の向き</th><th scope="col">計算の向き</th><th scope="col">一致</th></tr></thead>
        <tbody>{l2.cases.map(c => <tr key={c.id}><td>{c.policy}</td><td>{c.source}</td><td>{signLabel(c.truth)}</td><td>{signLabel(c.predicted)}</td><td>{c.hit ? '○' : '×'}</td></tr>)}</tbody>
      </table>
    </details>
  </section>;
}

export default function BacktestPanel() {
  const [data, setData] = useState<Backtest | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(backtestUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        setData(parseBacktest(await response.text()));
      } catch { if (!controller.signal.aborted) setError('バックテストのデータを読み込めませんでした。'); }
    })();
    return () => controller.abort();
  }, []);
  return <section aria-labelledby="backtest">
    <h3 id="backtest">7. 精度（バックテスト）</h3>
    <p>答えの分かっている事例（学術文献の事後評価で、原文と数値が一致した49件）を正解にして、今の計算の向きがどれだけ合うかを測っています。目標は95%以上です。結果は良く見えるように選ばず、届かないときは届かないと書きます。実装が一通り済んだら、同じ仕組みでもう一度測ります。</p>
    <p className="fine-note"><Info size={14} /> 計算の「向き」は、法律ごとに全産業または産業の付加価値を比較国と比べた結果論で、その法律だけの効果ではありません。正解は特定の集団・指標への効果です。同じものを測っていない分も、合わなさに含まれます（定義と限界は<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/adr/0020-backtest-accuracy-definition.md" target="_blank" rel="noopener noreferrer">設計決定0020</a>、全件の表は<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/バックテスト.md" target="_blank" rel="noopener noreferrer">docs/バックテスト.md</a>）。</p>
    {error && <p className="empty-state">{error}</p>}
    {!data && !error && <p className="empty-state">読み込み中…</p>}
    {data?.runs.map(run => <RunView key={run.label} run={run} />)}
  </section>;
}
