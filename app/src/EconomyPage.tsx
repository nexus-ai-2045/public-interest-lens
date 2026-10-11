import { useEffect, useState } from 'react';
import { ProductHeader } from './ProductHeader';
import { parseEconomicSnapshot, selectEconomicPeriod, type EconomicSnapshot } from './economy-view';
import { distributionEconomyUrl } from './public-distribution';

export function EconomyPage() {
  useEffect(() => { document.title = '日本の長期推移｜国賊／国士ランキング'; }, []);
  const read = () => new URLSearchParams(window.location.search);
  const [metric, setMetric] = useState(() => read().get('metric') ?? 'real_gdp');
  const [period, setPeriod] = useState(() => read().get('years') ?? '40');
  const [from, setFrom] = useState(() => read().get('from') ?? '1986');
  const [to, setTo] = useState(() => read().get('to') ?? '2025');
  const [edition, setEdition] = useState(() => read().get('edition') ?? '');
  const [data, setData] = useState<EconomicSnapshot | null>(null);
  const [error, setError] = useState('');
  const [sourceNote, setSourceNote] = useState('');
  useEffect(() => {
    if (edition && data?.snapshotId === edition) return;
    const controller = new AbortController();
    const adopt = (value: EconomicSnapshot, note: string) => {
      if (controller.signal.aborted) return;
      if (edition && value.snapshotId !== edition) throw new Error('mismatch');
      setData(value); setError(''); setSourceNote(note);
      if (!edition && value.snapshotId) { const params = read(); params.set('edition', value.snapshotId); window.history.replaceState(null, '', `/history?${params}`); setEdition(value.snapshotId); }
    };
    void (async () => {
      try {
        const response = await fetch(`/__local__/economy${edition ? `?edition=${encodeURIComponent(edition)}` : ''}`, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('local');
        adopt(parseEconomicSnapshot(await response.text()), 'この画面はローカル保存版です。公開配布版ではありません。');
        return;
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (!(reason instanceof Error) || reason.message !== 'local') { setData(null); setError('長期統計を読み込めませんでした。指定版を別版へ自動では置き換えません。'); setSourceNote(''); return; }
      }
      try {
        const response = await fetch(distributionEconomyUrl(edition), { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        adopt(parseEconomicSnapshot(await response.text()), '公開配布版です。非公開の原本やローカル評価版には接続していません。指定した版が無いときは、別の版へ置き換えません。');
      } catch { if (!controller.signal.aborted) { setData(null); setError('長期統計を読み込めませんでした。指定版を別版へ自動では置き換えません。'); setSourceNote(''); } }
    })();
    return () => controller.abort();
  }, [edition]);
  useEffect(() => {
    const restore = () => { const p = read(); setMetric(p.get('metric') ?? 'real_gdp'); setPeriod(p.get('years') ?? '40'); setFrom(p.get('from') ?? '1986'); setTo(p.get('to') ?? '2025'); setEdition(p.get('edition') ?? ''); };
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  function change(nextMetric: string, nextPeriod: string, nextFrom = from, nextTo = to) {
    setMetric(nextMetric); setPeriod(nextPeriod); setFrom(nextFrom); setTo(nextTo);
    const params = new URLSearchParams({ metric: nextMetric, years: nextPeriod });
    if (data?.snapshotId) params.set('edition', data.snapshotId);
    if (nextPeriod === 'custom') { params.set('from', nextFrom); params.set('to', nextTo); }
    window.history.pushState(null, '', `/history?${params}`);
  }
  const selected = data?.series.find(series => series.id === metric);
  let points: ReturnType<typeof selectEconomicPeriod> = [], periodError = '';
  if (selected) { try { points = selectEconomicPeriod(selected, period, Number(from), Number(to)); } catch { periodError = '開始年と終了年を、収録されている期間内で指定してください。'; } }
  const present = points.filter(point => point.value !== null);
  const max = Math.max(1, ...present.map(point => point.value!));
  const first = present[0], last = present[present.length - 1];
  const format = (value: number) => new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value / (metric.includes('per_capita') ? 10000 : metric === 'population' ? 10000 : 1e12));
  const unit = metric.includes('per_capita') ? '万円／人' : metric === 'population' ? '万人' : '兆円';
  const outcomes = (data?.outcomes ?? []).filter(outcome => points.length > 0 && Number(outcome.observationFrom.slice(0, 4)) <= points[points.length - 1].year && Number(outcome.observationTo.slice(0, 4)) >= points[0].year);
  return <div className="app-shell research-page" data-theme="light"><ProductHeader title="日本の長期推移" label="政策と結果を調べる"><nav aria-label="主なページ"><a href="/history">長期推移</a><a href="/policies">政策と結果</a><a href="/actors">人物・団体</a><a href="/ranking">ランキング</a></nav></ProductHeader><main>
    <h2>日本の経済は、どう変わりましたか？</h2><p>まず観測された変化を確認し、政策・制度・人物の関与を別に調べます。グラフの増減だけで誰かの責任とは判定しません。</p>
    <section className="real-intake"><label>見る指標<select value={metric} onChange={event => change(event.target.value, period)}>{data?.series.map(series => <option key={series.id} value={series.id}>{series.label}</option>)}</select></label><label>見る期間<select value={period} onChange={event => change(metric, event.target.value)}>{[40, 30, 8, 4, 2].map(years => <option key={years} value={years}>{years}年</option>)}<option value="custom">任意の期間</option></select></label>{period === 'custom' && <><label>開始年<input type="number" value={from} onChange={event => change(metric, period, event.target.value, to)} /></label><label>終了年<input type="number" value={to} onChange={event => change(metric, period, from, event.target.value)} /></label></>}</section>
    {(error || periodError) && <p role="alert">{error || periodError}</p>}
    {sourceNote && <p className="state-banner" role="status">{sourceNote}</p>}
    {data && !selected && <p role="alert">指定された指標は収録されていません。別の指標へ自動では切り替えません。</p>}
    {selected && points.length > 0 && <section aria-label="長期統計のグラフ"><h3>{selected.label}：{points[0].year}〜{points[points.length - 1].year}年</h3><p>単位：{unit}。{selected.unit}。{selected.basis}</p><svg viewBox="0 0 900 240" role="img" aria-label={`${selected.label}の年次推移`} style={{ width: '100%', height: 'auto' }}>{points.map((point, index) => point.value !== null && <rect key={point.year} x={index * 900 / points.length} y={220 - point.value / max * 200} width={Math.max(1, 900 / points.length - 2)} height={point.value / max * 200} fill="currentColor"><title>{point.year}年：{format(point.value)}{unit}</title></rect>)}</svg><p>{first && last && first.value! > 0 ? `${first.year}年の${format(first.value!)}${unit}から、${last.year}年の${format(last.value!)}${unit}へ、${((last.value! / first.value! - 1) * 100).toFixed(1)}％変化しました。` : '比較に必要な値が不足しています。'}</p><p>欠落している年：{points.filter(point => point.value === null).length}年。未取得値は0へ置き換えていません。</p><details><summary>年ごとの数値を見る</summary><table><thead><tr><th>年</th><th>{selected.label}（{unit}）</th></tr></thead><tbody>{points.map(point => <tr key={point.year}><td>{point.year}</td><td>{point.value === null ? '未取得' : format(point.value)}</td></tr>)}</tbody></table></details><a href={selected.sourceUrl} target="_blank" rel="noopener noreferrer">統計の提供元を確認する</a></section>}
    <section className="lower-panel"><h3>なぜ変わったのでしょうか？</h3><p>人口構造、国内の政策、海外経済、災害、技術変化などを比較して調べます。現在、このGDP系列の変化を説明する原因評価は未登録です。下の政策結果候補をGDP変化の原因と認定したわけではありません。</p><a href="/policies">政策と人物の記録を調べる</a>{data && <p>未取得の関連指標：{data.unavailable.join('、')}。収録統計の提供元：{data.provider}。</p>}</section>
    <section className="lower-panel"><h3>この期間に結果を確認している政策</h3>{!outcomes.length && <p>{data?.outcomes?.length ? '選択した年の範囲と重なる政策結果はありません。重ならない候補は、このグラフの原因としては置きません。' : '選択期間に対応する政策結果の評価候補は、まだ収録されていません。'}</p>}{data?.outcomes && data.outcomes.length > outcomes.length && <p><a href="/policies">期間が重ならない事例を、政策ページで読む</a></p>}{outcomes.map(outcome => <article key={outcome.id}><h4>{outcome.title}</h4><p>結果の観測期間：{outcome.observationFrom}〜{outcome.observationTo}。評価候補・採点未成立です。</p><h5>何が実施されましたか？</h5><p>{outcome.implementation}</p><h5>実際にどう変わりましたか？</h5><p>{outcome.observedResult}</p><h5>政策がどのように関係したと考えられますか？</h5><p>{outcome.contribution}</p><h5>ほかの原因や不利益は？</h5><p>{outcome.counterEvidence}</p><h5>資料に行動が記載されている人物</h5><ul>{outcome.actors.map(actor => <li key={actor.name}>{actor.name}：{actor.action}</li>)}</ul><p>これらの行動記録は、個人別の成果や責任の割合を確定したものではありません。まだ人物の点数には加算していません。</p><p><a href="/policies">実施、比較、不足資料まで読む</a></p><details><summary>説明の出典を確認する</summary><ul>{outcome.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></li>)}</ul></details></article>)}</section>
  </main></div>;
}
