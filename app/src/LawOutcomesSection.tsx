import { useEffect, useMemo, useState } from 'react';
import { formatYen } from './laws-catalog';
import {
  EVALUATED_RESULTS, RESULT_ORDER, countByResult, enforcedBetween, groupByResult, isReferenceAmount, lawOutcomesUrl, parseLawOutcomes, reasonBreakdown,
  type LawOutcome, type LawOutcomes, type OutcomeResult,
} from './law-outcomes-view';

const FIRST = 60;
const OTHER_RESULTS = RESULT_ORDER.filter(result => !EVALUATED_RESULTS.includes(result));

function OutcomeRow({ item }: { item: LawOutcome }) {
  const reference = isReferenceAmount(item);
  return <details className="law-outcome">
    <summary>
      <span>{item.title}</span>{' '}
      <small>（{item.enforced || '施行日不明'}施行・{item.result}）</small>
      {item.median !== null && <small className={reference ? 'law-outcome-reference' : undefined} style={reference ? { color: 'gray' } : undefined}> {reference ? '参考' : item.side === 'loss' ? '損失' : '便益'} {formatYen(item.median)}{reference ? '（合計に足しません）' : ''}</small>}
    </summary>
    <dl>
      <dt>結果</dt><dd>{item.result}{item.direction && `（向き：${item.direction}）`}</dd>
      <dt>理由</dt><dd>{item.reason}</dd>
      <dt>指標</dt><dd>{item.indicator || '決められていません'}</dd>
      <dt>確かさ</dt><dd>{item.certainty || '評価していません'}{item.stage && `（${item.stage}）`}</dd>
      <dt>経路</dt><dd>{item.route}</dd>
      <dt>分野・種類</dt><dd>{item.field}・{item.kind || '種類なし'}</dd>
      {item.median !== null && <><dt>額</dt><dd>{item.side === 'loss' ? '損失' : '便益'}の中央値 {formatYen(item.median)}（{item.unit}）{reference ? '。参考の額で、合計・順位・配分には使いません。' : ''}</dd></>}
      <dt>評価方法</dt><dd><a href="/methodology">計算方法（評価のしかた）</a></dd>
      <dt>出典</dt><dd><a href={`/ranking#${encodeURIComponent(item.id)}`}>元の法律（{item.id}）：法律ランキングで因果の鎖と一次資料を見る</a></dd>
    </dl>
  </details>;
}

function ResultList({ items, label }: { items: LawOutcome[]; label: string }) {
  const [shown, setShown] = useState(FIRST);
  return <>
    <ul aria-label={label} style={{ listStyle: 'none', padding: 0 }}>{items.slice(0, shown).map(item => <li key={item.id}><OutcomeRow item={item} /></li>)}</ul>
    {items.length > shown && <button type="button" onClick={() => setShown(value => value + FIRST)}>もっと見る（あと{items.length - shown}件）</button>}
  </>;
}

/** 選択した期間（施行年が from〜to）に施行された法律・政策と、1本ごとの評価。結果が出ているものを先に、保留などは畳む。 */
export function LawOutcomesSection({ from, to }: { from: number; to: number }) {
  const [data, setData] = useState<LawOutcomes | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(lawOutcomesUrl, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('missing');
      setData(parseLawOutcomes(await response.text()));
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);
  const { groups, counts, total, unknownDate } = useMemo(() => {
    const { inRange, unknownDate: unknown } = enforcedBetween(data?.items ?? [], from, to);
    return { groups: groupByResult(inRange), counts: countByResult(inRange), total: inRange.length, unknownDate: unknown };
  }, [data, from, to]);
  const evaluated = EVALUATED_RESULTS.reduce((sum, key) => sum + counts[key], 0);
  return <section className="lower-panel" aria-label="この期間に施行された法律・政策と評価">
    <h3>この期間に施行された法律・政策と評価（{from}〜{to}年）</h3>
    {error && <p role="alert">全法律の評価一覧を読み込めませんでした。</p>}
    {!data && !error && <p>読み込み中です。</p>}
    {data && <>
      <p>施行年が{from}〜{to}年の法律は{total.toLocaleString('ja-JP')}本です。そのうち評価が出ているのは{evaluated}本（額あり{counts['額あり']}本・効果なし（定例）{counts['効果なし（定例）']}本）で、残りは結果を出せていません。</p>
      <p className="fine-note">件数が少なく見えるのは、保留・測定できない・評価対象外が大半で、額が出た法律が全体で{data.counts['額あり']}本だけだからです。どの法律にも結果か理由を付けており、黙って落としてはいません。施行日が分からない{unknownDate.toLocaleString('ja-JP')}本は、期間に入るか決められないためここには出しません。</p>
      {EVALUATED_RESULTS.map(result => groups[result].length > 0 && <div key={result}><h4>{result}（{groups[result].length}本）</h4><ResultList items={groups[result]} label={result} /></div>)}
      {evaluated === 0 && <p>この期間には、評価が出ている法律はありません。</p>}
      <details>
        <summary>その他（結果を出せていない法律）{total - evaluated}本の内訳を見る</summary>
        {OTHER_RESULTS.map((result: OutcomeResult) => groups[result].length > 0 && <div key={result}>
          <details>
            <summary>{result}（{groups[result].length}本）</summary>
            <p>主な理由：{reasonBreakdown(groups[result]).map(entry => `${entry.reason}（${entry.count}本）`).join('、')}</p>
            <ResultList items={groups[result]} label={result} />
          </details>
        </div>)}
      </details>
    </>}
  </section>;
}
