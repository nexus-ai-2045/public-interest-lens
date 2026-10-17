import { useEffect, useState } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { ProductHeader } from './ProductHeader';
import { GrowthCauses } from './GrowthCauses';
import {
  WORLD_PERIODS, distributionWorldGdpUrl, formatMetric, formatRate, growthRanking, latestRanking, linearTicks, logTicks, parseWorldGdp, periodLabel, periodRange, pointsInRange,
  type GrowthBasis, type WorldGdpSnapshot, type WorldMetric, type WorldPeriod,
} from './world-gdp';

const METRIC_KEYS: Record<string, WorldMetric> = { nominal: 'nominalUsd', growth: 'realGrowth', ppp: 'perCapitaPpp' };
const METRIC_PARAM: Record<WorldMetric, string> = { nominalUsd: 'nominal', realGrowth: 'growth', perCapitaPpp: 'ppp' };
const METRIC_LABEL: Record<WorldMetric, string> = { nominalUsd: '名目GDP（米ドル）', realGrowth: '実質成長率（年ごと）', perCapitaPpp: '一人あたりGDP（購買力平価）' };
const METRIC_UNIT: Record<WorldMetric, string> = {
  nominalUsd: '各年の米ドル換算。為替の動きを含みます。',
  realGrowth: '前年からの実質GDPの伸び（％）。物価の変動を除いています。',
  perCapitaPpp: '2021年基準の国際ドル。物価の差を調整した、暮らしの豊かさに近い指標です。',
};
const JAPAN = 'JPN';

export type WorldView = { metric: WorldMetric; period: WorldPeriod; log: boolean; hidden: string[]; focus: string; basis: GrowthBasis };

function readView(): WorldView {
  const params = new URLSearchParams(window.location.search);
  const period = params.get('period') ?? '1990';
  return {
    metric: METRIC_KEYS[params.get('metric') ?? ''] ?? 'nominalUsd',
    period: (WORLD_PERIODS as readonly string[]).includes(period) ? period as WorldPeriod : '1990',
    log: params.get('scale') === 'log',
    hidden: (params.get('hide') ?? '').split(',').filter(code => /^[A-Z]{3}$/.test(code) && code !== JAPAN),
    focus: /^[A-Z]{3}$/.test(params.get('focus') ?? '') && params.get('focus') !== JAPAN ? params.get('focus')! : '',
    basis: params.get('basis') === 'percapita' ? 'perCapita' : 'real',
  };
}

function viewLocation(view: WorldView): string {
  const params = new URLSearchParams({ metric: METRIC_PARAM[view.metric], period: view.period });
  if (view.log && view.metric !== 'realGrowth') params.set('scale', 'log');
  if (view.hidden.length) params.set('hide', [...view.hidden].sort().join(','));
  if (view.focus) params.set('focus', view.focus);
  if (view.basis === 'perCapita') params.set('basis', 'percapita');
  return `/world?${params}`;
}


export function LineChart({ data, view, onHover, hover, narrow }: { data: WorldGdpSnapshot; view: WorldView; hover: string; onHover: (code: string) => void; narrow: boolean }) {
  const W = narrow ? 420 : 900, H = narrow ? 340 : 380, M = narrow ? { top: 14, right: 64, bottom: 30, left: 58 } : { top: 18, right: 118, bottom: 34, left: 86 };
  const range = periodRange(data, view.metric, view.period);
  if (!range) return <p role="status">この期間の値はありません。</p>;
  const log = view.log && view.metric !== 'realGrowth';
  const lines = data.countries
    .filter(country => !view.hidden.includes(country.code))
    .map(country => ({ country, points: pointsInRange(country.series[view.metric], range.from, range.to) }))
    .filter(line => line.points.length > 0);
  const values = lines.flatMap(line => line.points.map(([, value]) => value));
  if (!values.length) return <p role="status">表示する国を一つ以上選んでください。</p>;
  let lo = Math.min(...values), hi = Math.max(...values);
  if (view.metric === 'realGrowth') { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  else if (!log) lo = 0;
  if (lo === hi) hi = lo + 1;
  const ticks = log ? logTicks(lo, hi) : linearTicks(lo, hi, narrow ? 4 : 5);
  if (!log) { lo = Math.min(lo, ticks[0] ?? lo); hi = Math.max(hi, ticks[ticks.length - 1] ?? hi); }
  const innerW = W - M.left - M.right, innerH = H - M.top - M.bottom;
  const x = (year: number) => M.left + (range.to === range.from ? innerW / 2 : (year - range.from) / (range.to - range.from) * innerW);
  const y = (value: number) => M.top + innerH - (log ? (Math.log10(value) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) : (value - lo) / (hi - lo)) * innerH;
  const yearTicks = linearTicks(range.from, range.to, narrow ? 4 : 6).filter(year => Number.isInteger(year) && year >= range.from && year <= range.to);
  const shortLabel = (value: number) => view.metric === 'nominalUsd' ? formatMetric('nominalUsd', value).replace('ドル', '') : view.metric === 'perCapitaPpp' ? new Intl.NumberFormat('ja-JP', { notation: 'compact', maximumFractionDigits: 1 }).format(value) : `${value}％`;
  const role = (code: string) => code === JAPAN ? 'japan' : code === view.focus ? 'focus' : code === hover ? 'hover' : 'other';
  const order = { other: 0, hover: 1, focus: 2, japan: 3 };
  const sorted = [...lines].sort((a, b) => order[role(a.country.code)] - order[role(b.country.code)]);
  const labels = sorted.filter(line => role(line.country.code) !== 'other').map(line => {
    const [year, value] = line.points[line.points.length - 1];
    return { code: line.country.code, name: line.country.name, x: x(year), y: y(value), kind: role(line.country.code) };
  });
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 16) labels[i].y = labels[i - 1].y + 16;
  return <svg className="world-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${METRIC_LABEL[view.metric]}、${range.from}〜${range.to}年、${lines.length}か国・地域の推移`} onMouseLeave={() => onHover('')}>
    {ticks.map(tick => <g key={tick} className="world-grid"><line x1={M.left} x2={W - M.right} y1={y(tick)} y2={y(tick)} /><text x={M.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">{shortLabel(tick)}</text></g>)}
    {view.metric === 'realGrowth' && <line className="world-zero" x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)} />}
    {yearTicks.map(year => <text key={year} className="world-axis" x={x(year)} y={H - 10} textAnchor="middle">{year}</text>)}
    {sorted.map(({ country, points }) => {
      const d = points.map(([year, value], index) => `${index ? 'L' : 'M'}${x(year).toFixed(1)},${y(value).toFixed(1)}`).join('');
      return <g key={country.code} className={`world-line world-line-${role(country.code)}`} onMouseEnter={() => onHover(country.code)}>
        <path d={d}><title>{country.name}：{points[points.length - 1][0]}年 {formatMetric(view.metric, points[points.length - 1][1])}</title></path>
        {points.length === 1 && <circle cx={x(points[0][0])} cy={y(points[0][1])} r={3} />}
      </g>;
    })}
    {labels.map(label => <text key={label.code} className={`world-end-label world-end-${label.kind}`} x={label.x + 6} y={label.y} dy="0.32em">{label.name}</text>)}
  </svg>;
}

function useNarrow() {
  const query = '(max-width: 600px)';
  const [narrow, setNarrow] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(query).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const list = window.matchMedia(query);
    const update = () => setNarrow(list.matches);
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, []);
  return narrow;
}

export function GrowthBars({ data, view }: { data: WorldGdpSnapshot; view: WorldView }) {
  const range = periodRange(data, view.basis === 'real' ? 'realGrowth' : 'perCapitaPpp', view.period);
  const rows = range ? growthRanking(data, range.from, range.to, view.basis) : [];
  if (!range || !rows.length) return <p role="status">この期間の平均成長率は計算できません。</p>;
  const lo = Math.min(0, ...rows.map(row => row.growth.value)), hi = Math.max(0, ...rows.map(row => row.growth.value));
  const span = hi - lo || 1;
  const japan = rows.find(row => row.code === JAPAN);
  return <>
    <p className="world-lead">{japan ? <>日本は<strong>{rows.length}か国・地域中{japan.rank}位</strong>（年平均{formatRate(japan.growth.value)}）。</> : '日本の値はこの期間にありません。'}{range.from}〜{range.to}年、{view.basis === 'real' ? '実質GDP成長率を複利で平均' : '一人あたりGDP（購買力平価）の最初と最後の年から年平均の伸びを計算'}しています。</p>
    <ol className="world-bars" aria-label="期間平均成長率の順位">
      {rows.map(row => {
        const left = (Math.min(row.growth.value, 0) - lo) / span * 100, width = Math.abs(row.growth.value) / span * 100;
        const short = row.growth.from > range.from || row.growth.to < range.to;
        return <li key={row.code} className={row.code === JAPAN ? 'is-japan' : row.code === view.focus ? 'is-focus' : undefined}>
          <span className="world-bar-name">{row.rank}. {row.name}{short && <small>（{row.growth.from}〜{row.growth.to}年）</small>}</span>
          <span className="world-bar-track" aria-hidden="true"><span className="world-bar-zero" style={{ left: `${(0 - lo) / span * 100}%` }} /><span className={`world-bar${row.growth.value < 0 ? ' is-negative' : ''}`} style={{ left: `${left}%`, width: `${width}%` }} /></span>
          <span className="world-bar-value">{formatRate(row.growth.value)}</span>
        </li>;
      })}
    </ol>
  </>;
}

export function LatestTable({ data, view }: { data: WorldGdpSnapshot; view: WorldView }) {
  const rows = latestRanking(data, view.metric);
  const japan = rows.find(row => row.code === JAPAN);
  const years = new Set(rows.map(row => row.year));
  return <>
    <p className="world-lead">{japan ? <>日本は<strong>{rows.length}か国・地域中{japan.rank}位</strong>（{japan.year}年、{formatMetric(view.metric, japan.value)}）。</> : 'この指標には日本の値がありません。'}このページに載せた国・地域の中での順位で、世界全体の順位ではありません。</p>
    <div className="world-table-wrap"><table className="world-table">
      <thead><tr><th scope="col">順位</th><th scope="col">国・地域</th><th scope="col">{METRIC_LABEL[view.metric].replace('（年ごと）', '')}</th>{years.size > 1 && <th scope="col">年</th>}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.code} className={row.code === JAPAN ? 'is-japan' : row.code === view.focus ? 'is-focus' : undefined}><td>{row.rank}</td><td>{row.name}</td><td>{formatMetric(view.metric, row.value)}</td>{years.size > 1 && <td>{row.year}</td>}</tr>)}</tbody>
    </table></div>
  </>;
}

export function WorldGdpPage() {
  useEffect(() => { document.title = PUBLIC_SITE ? '世界のGDP比較｜試作版' : '世界のGDP比較｜国賊／国士ランキング'; }, []);
  const [view, setView] = useState<WorldView>(readView);
  const [data, setData] = useState<WorldGdpSnapshot | null>(null);
  const [error, setError] = useState('');
  const [hover, setHover] = useState('');
  const narrow = useNarrow();
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionWorldGdpUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        const value = parseWorldGdp(await response.text());
        if (!controller.signal.aborted) { setData(value); setError(''); }
      } catch { if (!controller.signal.aborted) { setData(null); setError('世界のGDPデータを読み込めませんでした。'); } }
    })();
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const restore = () => setView(readView());
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  function change(patch: Partial<WorldView>, mode: 'push' | 'replace' = 'push') {
    const next = { ...view, ...patch };
    setView(next);
    window.history[mode === 'push' ? 'pushState' : 'replaceState'](null, '', viewLocation(next));
  }
  const codes = new Set(data?.countries.map(country => country.code) ?? []);
  const shown = data ? { ...view, hidden: view.hidden.filter(code => codes.has(code)), focus: codes.has(view.focus) ? view.focus : '' } : view;
  const missing = data?.countries.filter(country => !country.series[shown.metric] && !shown.hidden.includes(country.code)) ?? [];
  const toggle = (code: string, visible: boolean) => change({ hidden: visible ? shown.hidden.filter(item => item !== code) : [...shown.hidden, code] }, 'replace');
  const metricNames: Record<WorldMetric, string> = { nominalUsd: '名目GDP', realGrowth: '実質成長率', perCapitaPpp: '一人あたりGDP（購買力平価）' };
  return <div className="app-shell research-page world-page" data-theme="light"><ProductHeader title="世界のGDP比較" label="日本と各国を比べる" brandHref="/world"><nav aria-label="主なページ"><a href="/history">長期推移</a><a href="/world" className="nav-active" aria-current="page">世界のGDP</a><a href="/policies">政策と結果</a><a href="/actors">人物・団体</a><a href="/ranking">法律ランキング</a><a href="/demo">架空デモ</a></nav></ProductHeader><main>
    <h2>日本の経済は、世界と比べてどうですか？</h2>
    <p>世界の主要国（名目GDPの上位国と、中国・韓国・台湾・東南アジアなど）を、同じ統計で並べます。日本は赤い太線です。グラフの差だけで、原因や誰かの責任とは判定しません。</p>
    <section className="real-intake world-controls" aria-label="表示の切り替え">
      <div className="world-segment" role="group" aria-label="見る指標">{(Object.keys(METRIC_PARAM) as WorldMetric[]).map(metric => <button key={metric} type="button" aria-pressed={shown.metric === metric} onClick={() => change({ metric })}>{metricNames[metric]}</button>)}</div>
      <label>見る期間<select value={shown.period} onChange={event => change({ period: event.target.value as WorldPeriod })}>{WORLD_PERIODS.map(period => <option key={period} value={period}>{periodLabel(period)}</option>)}</select></label>
      {shown.metric !== 'realGrowth' && <label className="world-check"><input type="checkbox" checked={shown.log} onChange={event => change({ log: event.target.checked }, 'replace')} />対数の目盛りで見る（伸び率を比べやすくします）</label>}
      <label>色を付けて比べる国<select value={shown.focus} onChange={event => change({ focus: event.target.value }, 'replace')}><option value="">選ばない</option>{data?.countries.filter(country => country.code !== JAPAN).map(country => <option key={country.code} value={country.code}>{country.name}</option>)}</select></label>
    </section>
    {error && <p className="state-banner" role="alert">{error}</p>}
    {data && <>
      <fieldset className="world-countries"><legend>表示する国・地域</legend>
        <div className="world-country-actions"><button type="button" onClick={() => change({ hidden: [] }, 'replace')}>すべて表示</button><button type="button" onClick={() => change({ hidden: data.countries.filter(country => country.code !== JAPAN && country.code !== shown.focus).map(country => country.code) }, 'replace')}>日本{shown.focus ? 'と比べる国' : ''}だけ</button></div>
        <div className="world-country-list">{data.countries.map(country => <label key={country.code} className={country.code === JAPAN ? 'is-japan' : country.code === shown.focus ? 'is-focus' : undefined}><input type="checkbox" checked={!shown.hidden.includes(country.code)} disabled={country.code === JAPAN} onChange={event => toggle(country.code, event.target.checked)} />{country.name}</label>)}</div>
        <p className="fine-note">日本は比較の基準なので、常に表示します。</p>
      </fieldset>
      <section aria-labelledby="world-chart-heading">
        <h3 id="world-chart-heading">{METRIC_LABEL[shown.metric]}：{periodLabel(shown.period)}</h3>
        <p className="fine-note">{METRIC_UNIT[shown.metric]}{shown.log && shown.metric !== 'realGrowth' ? '対数の目盛りでは、同じ傾きが同じ伸び率を表します。' : ''}線に触れると国名を強調します。</p>
        <div className="world-chart-wrap"><LineChart data={data} view={shown} hover={hover} onHover={setHover} narrow={narrow} /></div>
        {missing.length > 0 && <p className="fine-note">この指標の値が無いため表示していない国・地域：{missing.map(country => country.name).join('、')}。</p>}
      </section>
      <div className="world-grid-2">
        <section className="lower-panel" aria-labelledby="world-latest-heading"><h3 id="world-latest-heading">最新年の順位（{metricNames[shown.metric]}）</h3><LatestTable data={data} view={shown} /></section>
        <section className="lower-panel" aria-labelledby="world-growth-heading"><h3 id="world-growth-heading">期間平均成長率の順位：{periodLabel(shown.period)}</h3>
          <div className="world-segment" role="group" aria-label="平均する値"><button type="button" aria-pressed={shown.basis === 'real'} onClick={() => change({ basis: 'real' }, 'replace')}>実質GDP</button><button type="button" aria-pressed={shown.basis === 'perCapita'} onClick={() => change({ basis: 'perCapita' }, 'replace')}>一人あたり（購買力平価）</button></div>
          <GrowthBars data={data} view={shown} />
          <p className="fine-note">人口が減る国では、国全体の伸びより一人あたりの伸びの方が実感に近いことがあります。</p>
        </section>
      </div>
      <section className="lower-panel" aria-labelledby="world-notes-heading"><h3 id="world-notes-heading">注記と出典</h3>
        <ul className="world-notes">{data.notes.map(note => <li key={note}>{note}</li>)}<li>取得日時：{new Date(data.fetchedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}（日本時間）</li></ul>
        <details><summary>各国の出典を確認する</summary><ul className="world-sources">{data.countries.map(country => <li key={country.code}><span>{country.name}（{country.provider}）</span>{(Object.keys(METRIC_PARAM) as WorldMetric[]).filter(metric => country.sourceUrls[metric]).map(metric => <a key={metric} href={country.sourceUrls[metric]} target="_blank" rel="noopener noreferrer">{metricNames[metric]}</a>)}</li>)}</ul></details>
        <p><a href="/history">日本の長期推移を詳しく読む</a></p>
      </section>
    </>}
    <section id="growth-causes" className="world-causes"><GrowthCauses /></section>
  </main></div>;
}
