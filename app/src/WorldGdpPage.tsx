import { useEffect, useState } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { SiteShell } from './SiteHeader';
import { GrowthCauses } from './GrowthCauses';
import { LineReveal, type LineSeries } from './motion';
import {
  WORLD_PERIODS, distributionWorldGdpUrl, formatMetric, formatRate, growthRanking, latestRanking, parseWorldGdp, periodLabel, periodRange, periodShort, pointsInRange,
  type GrowthBasis, type WorldGdpSnapshot, type WorldMetric, type WorldPeriod,
} from './world-gdp';

const METRIC_KEYS: Record<string, WorldMetric> = { nominal: 'nominalUsd', growth: 'realGrowth', ppp: 'perCapitaPpp', realgdp: 'realGdp' };
const METRIC_PARAM: Record<WorldMetric, string> = { nominalUsd: 'nominal', realGrowth: 'growth', perCapitaPpp: 'ppp', realGdp: 'realgdp' };
/** 画面に並べる順。年ごとの実質成長率は分かりにくいので最後に置く。 */
const METRIC_ORDER: WorldMetric[] = ['perCapitaPpp', 'realGdp', 'nominalUsd', 'realGrowth'];
const METRIC_LABEL: Record<WorldMetric, string> = { nominalUsd: '名目GDP（米ドル）', realGrowth: '実質成長率（年ごと）', perCapitaPpp: '一人あたりGDP（購買力平価）', realGdp: '実質GDP（物価を除いた経済の大きさ）' };
const METRIC_SHORT: Record<WorldMetric, string> = { nominalUsd: '名目GDP', realGrowth: '実質成長率（年ごと）', perCapitaPpp: '一人あたりGDP', realGdp: '実質GDP' };
const METRIC_UNIT: Record<WorldMetric, string> = {
  nominalUsd: '各年の米ドル換算。為替の動きを含むので、国どうしの比較には実質GDPか一人あたりGDPを見てください。',
  realGrowth: '前年からの実質GDPの伸び（％）。年ごとの上下が大きく、長い期間の比較には向きません。積み上げた「実質GDP」の方が読みやすいです。',
  perCapitaPpp: '2021年基準の国際ドル。物価の差を調整した、暮らしの豊かさに近い指標です（人口で割っているので、人口が減る国にも公平です）。',
  realGdp: '年ごとの実質成長率を積み上げた指数です。物価の変動を除いた、国全体の経済の大きさの伸びを表します（人口の増減は含まれるので、暮らしの豊かさは一人あたりで見てください）。',
};
const JAPAN = 'JPN';
const METRIC_AXIS: Record<WorldMetric, string> = { nominalUsd: '米ドル（各年）', realGrowth: '％（前年比）', perCapitaPpp: '国際ドル（2021年基準）', realGdp: '指数' };
/** 固定で目立たせる国。日本は赤（LineReveal の highlight）、ほかは色を分ける。 */
const FIXED_ACCENTS: Record<string, string> = { USA: '#1f5fbf', CHN: '#d97706' };
/** 「伸びている国」に順に割り当てる色。 */
const GROWTH_PALETTE = ['#0b7474', '#7c3aed', '#15803d', '#be185d'];
const FOCUS_COLOR = '#475569';
/** 指数にできない（水準の絶対値が意味を持たない、または年ごとの率そのもの）指標。 */
const indexable = (metric: WorldMetric) => metric !== 'realGrowth';
const indexOnly = (metric: WorldMetric) => metric === 'realGdp';

export type WorldView = { metric: WorldMetric; period: WorldPeriod; indexed: boolean; log: boolean; hidden: string[]; focus: string; basis: GrowthBasis };

/** 既定の指標。国どうしは物価と為替を除いた実質で比べるので、名目ではなく一人あたり（購買力平価）から始めます。 */
export const DEFAULT_METRIC: WorldMetric = 'perCapitaPpp';

/** アドレスの検索部分（?metric=…）から表示の状態を作ります。読めない値は既定に戻します。 */
export function parseWorldView(search: string): WorldView {
  const params = new URLSearchParams(search);
  const period = params.get('period') ?? '1990';
  return {
    metric: METRIC_KEYS[params.get('metric') ?? ''] ?? DEFAULT_METRIC,
    period: (WORLD_PERIODS as readonly string[]).includes(period) ? period as WorldPeriod : '1990',
    indexed: params.get('scale') !== 'abs',
    log: params.get('axis') !== 'linear',
    hidden: (params.get('hide') ?? '').split(',').filter(code => /^[A-Z]{3}$/.test(code) && code !== JAPAN),
    focus: /^[A-Z]{3}$/.test(params.get('focus') ?? '') && params.get('focus') !== JAPAN ? params.get('focus')! : '',
    basis: params.get('basis') === 'percapita' ? 'perCapita' : 'real',
  };
}

const readView = () => parseWorldView(window.location.search);

function viewLocation(view: WorldView): string {
  const params = new URLSearchParams({ metric: METRIC_PARAM[view.metric], period: view.period });
  if (!view.indexed && !indexOnly(view.metric)) params.set('scale', 'abs');
  if (!view.log) params.set('axis', 'linear');
  if (view.hidden.length) params.set('hide', [...view.hidden].sort().join(','));
  if (view.focus) params.set('focus', view.focus);
  if (view.basis === 'perCapita') params.set('basis', 'percapita');
  return `/world?${params}`;
}


/** 表示する国・期間の折れ線データ。値の無い国は入れない。 */
export function worldLineSeries(data: WorldGdpSnapshot, view: WorldView): LineSeries[] {
  const range = periodRange(data, view.metric, view.period);
  if (!range) return [];
  return data.countries
    .filter(country => !view.hidden.includes(country.code))
    .map(country => ({ id: country.code, label: country.name, points: pointsInRange(country.series[view.metric], range.from, range.to).map(([year, value]) => ({ year, value })) }))
    .filter(line => line.points.length > 0);
}

/** 目立たせる国の色。日本は別（赤）。アメリカ・中国は固定色、期間で最も伸びた国は順に色を分け、選んだ国は灰青。 */
export function worldAccents(data: WorldGdpSnapshot, view: WorldView): { colors: Record<string, string>; leaders: string[] } {
  const colors: Record<string, string> = {};
  for (const [code, color] of Object.entries(FIXED_ACCENTS)) if (!view.hidden.includes(code) && data.countries.some(country => country.code === code)) colors[code] = color;
  const basis: GrowthBasis = view.metric === 'perCapitaPpp' ? 'perCapita' : 'real';
  const range = periodRange(data, basis === 'real' ? 'realGrowth' : 'perCapitaPpp', view.period);
  const leaders = (range ? growthRanking(data, range.from, range.to, basis) : [])
    .filter(row => row.code !== JAPAN && !(row.code in FIXED_ACCENTS) && !view.hidden.includes(row.code))
    .slice(0, GROWTH_PALETTE.length).map(row => row.code);
  leaders.forEach((code, index) => { colors[code] = GROWTH_PALETTE[index]; });
  if (view.focus && !(view.focus in colors) && !view.hidden.includes(view.focus)) colors[view.focus] = FOCUS_COLOR;
  return { colors, leaders };
}

/** 初期年の値が無く、指数にできないため線に出せない国。 */
export function droppedForBase(data: WorldGdpSnapshot, view: WorldView): string[] {
  const base = worldBaseYear(data, view);
  if (base === undefined || !view.indexed || !indexable(view.metric)) return [];
  return worldLineSeries(data, view).filter(line => !line.points.some(point => point.year === base && point.value)).map(line => line.label);
}

/** 指数表示の基準年。期間の最初の年を 100 にする。 */
export function worldBaseYear(data: WorldGdpSnapshot, view: WorldView): number | undefined {
  return periodRange(data, view.metric, view.period)?.from;
}

/** 「伸び損ねた原因の軸」の結論と、伸び悩んだ側の国の注記。原因の断定も、額の配分もしません。 */
export function MissedGrowthSummary() {
  return <section className="lower-panel world-missed" aria-labelledby="world-missed-heading">
    <h3 id="world-missed-heading">日本はなぜ伸び損ねたか：原因の軸の結論（暫定）</h3>
    <ol className="world-missed-lines">
      <li>いま「原因の軸にする」と言える候補はありません。官公庁の一次資料の多くを確かめられておらず、判定は暫定です。</li>
      <li>「条件つき」の候補は7つ（金融政策・為替・デフレ、大学・研究への公的支出、ベンチャー投資と上場、配信・著作権の規制、政府のIT調達、不良債権、通信事業者主導の端末の仕組み）。決定には結べますが、因果が「中」止まりか、数字が未確認です。根拠の確認状態（2026-10-24 時点）は、OECD の統計 API で値を確かめたものと、検索結果の要約だけで一次資料を未開封のものが混在し、後者は「確認済み」と扱いません。</li>
      <li>2000〜2023年の自国通貨建ての名目付加価値の伸びの差は、大半が物価の差でした（上の米ドル建てのグラフとは別の比較で、為替の動きは含みません）。実質の付加価値（2000→2023年）は日本1.16倍、米国1.62倍、ドイツ1.31倍、韓国2.30倍で、実質の差は残ります。ただし原因は特定せず、額は配っていません。</li>
    </ol>
    <p className="fine-note">イタリア・ロシア・ブラジルは、伸び悩んだ側の例として上のグラフと順位に入れています。この3か国が伸びなかった要因は、まだ調べていません。下の「伸びている国は、なぜ伸びたのか」は伸びた国だけの説明です。<a href="/methodology#spec-cause-axis">原因の軸の式と決まり</a></p>
  </section>;
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
  const useIndex = indexable(shown.metric) && (shown.indexed || indexOnly(shown.metric));
  const chartView = { ...shown, indexed: useIndex };
  const accents = data ? worldAccents(data, shown) : { colors: {}, leaders: [] };
  const dropped = data ? droppedForBase(data, chartView) : [];
  const nameOf = (code: string) => data?.countries.find(country => country.code === code)?.name ?? code;
  const base = data ? worldBaseYear(data, shown) : undefined;
  const swatches: [string, string][] = [[JAPAN, 'var(--japan)'], ...Object.entries(accents.colors)];
  return <SiteShell active="/world" label="世界のGDP比較" className="world-page"><main id="main">
    <h1>日本の経済は、世界と比べてどうですか？</h1>
    <p>世界の主要国を、同じ統計で並べます。年ごとの上下ではなく、<strong>選んだ初期年を100</strong>にして、どれだけ伸びたかを比べるのが基本です。グラフの差だけで、原因や誰かの責任とは判定しません。</p>
    <div className="world-layout">
      <aside className="world-side" aria-label="表示の切り替え">
        <div className="world-side-group"><h2>見る指標</h2>
          <div className="world-stack" role="group" aria-label="見る指標">{METRIC_ORDER.map(metric => <button key={metric} type="button" aria-pressed={shown.metric === metric} onClick={() => change({ metric })}>{METRIC_SHORT[metric]}</button>)}</div>
        </div>
        <div className="world-side-group"><h2>初期年（ここから）</h2>
          <div className="world-stack" role="group" aria-label="見る期間">{WORLD_PERIODS.map(period => <button key={period} type="button" aria-pressed={shown.period === period} onClick={() => change({ period })}>{periodShort(period)}</button>)}</div>
        </div>
        <div className="world-side-group"><h2>縦軸</h2>
          <div className="world-stack" role="group" aria-label="縦軸の目盛り">
            <button type="button" aria-pressed={shown.log} disabled={shown.metric === 'realGrowth'} onClick={() => change({ log: true }, 'replace')}>対数（同じ割合＝同じ傾き）</button>
            <button type="button" aria-pressed={!shown.log || shown.metric === 'realGrowth'} onClick={() => change({ log: false }, 'replace')}>ふつうの目盛り</button>
          </div>
        </div>
        <div className="world-side-group"><h2>表し方</h2>
          <div className="world-stack" role="group" aria-label="表し方">
            <button type="button" aria-pressed={useIndex} disabled={!indexable(shown.metric)} onClick={() => change({ indexed: true }, 'replace')}>初期年＝100</button>
            <button type="button" aria-pressed={!useIndex} disabled={indexOnly(shown.metric)} onClick={() => change({ indexed: false }, 'replace')}>実際の値</button>
          </div>
          {indexOnly(shown.metric) && <p className="fine-note">実質GDPは伸びの積み上げなので、初期年＝100でだけ表示します。</p>}
          {shown.metric === 'realGrowth' && <p className="fine-note">年ごとの率は、そのまま表示します。</p>}
        </div>
      </aside>
      <div className="world-main">
        {shown.period !== 'all' && Number(shown.period) >= 2020 && <p className="fine-note">直近の短い期間です。コロナ禍とその反動、為替の動きで年ごとのぶれが大きく、数年の平均は長期の実力を表しません。ここ数年の評価の仕方は、確定した統計が出るまで暫定として見てください。</p>}
        {error && <p className="state-banner" role="alert">{error}</p>}
        {data && <section aria-labelledby="world-chart-heading">
          <h3 id="world-chart-heading">{METRIC_LABEL[shown.metric]}：{periodLabel(shown.period)}{useIndex && base !== undefined ? `（${base}年＝100）` : ''}</h3>
          <p className="fine-note">{METRIC_UNIT[shown.metric]}</p>
          <ul className="world-key" aria-label="色の見方">
            {swatches.map(([code, color]) => <li key={code}><i style={{ background: color }} aria-hidden="true" />{nameOf(code)}{accents.leaders.includes(code) ? '（伸びた国）' : ''}</li>)}
            <li><i className="world-key-other" aria-hidden="true" />その他の国（薄い線）</li>
          </ul>
          <div className="world-chart-wrap"><LineReveal key={`${shown.metric}-${shown.period}-${useIndex}-${shown.hidden.join(',')}-${shown.focus}-${shown.log}`} series={worldLineSeries(data, shown)} highlightId={JAPAN} accents={accents.colors} log={shown.log && shown.metric !== 'realGrowth'} indexed={useIndex} baseYear={base} format={value => useIndex ? value.toFixed(0) : value === 0 ? '0' : formatMetric(shown.metric, value)} unit={useIndex ? `指数（${base}年＝100）` : METRIC_AXIS[shown.metric]} caption={`${METRIC_LABEL[shown.metric]}、${periodLabel(shown.period)}。日本を赤で強調`} /></div>
          {dropped.length > 0 && <p className="fine-note">{base}年の値が無く、指数にできないため表示していない国：{dropped.join('、')}。初期年を遅くすると出ます。</p>}
          {missing.length > 0 && <p className="fine-note">この指標の値が無いため表示していない国・地域：{missing.map(country => country.name).join('、')}。</p>}
          <details className="world-countries"><summary>表示する国・地域（{(data.countries.length - shown.hidden.length)}／{data.countries.length}）</summary>
            <div className="world-country-actions"><button type="button" onClick={() => change({ hidden: [] }, 'replace')}>すべて表示</button><button type="button" onClick={() => change({ hidden: data.countries.filter(country => country.code !== JAPAN && country.code !== shown.focus).map(country => country.code) }, 'replace')}>日本{shown.focus ? 'と比べる国' : ''}だけ</button></div>
            <div className="world-country-list">{data.countries.map(country => <label key={country.code} className={country.code === JAPAN ? 'is-japan' : country.code === shown.focus ? 'is-focus' : undefined}><input type="checkbox" checked={!shown.hidden.includes(country.code)} disabled={country.code === JAPAN} onChange={event => toggle(country.code, event.target.checked)} />{country.name}</label>)}</div>
            <label className="world-focus-pick">下の表で色を付けて比べる国<select value={shown.focus} onChange={event => change({ focus: event.target.value }, 'replace')}><option value="">選ばない</option>{data.countries.filter(country => country.code !== JAPAN).map(country => <option key={country.code} value={country.code}>{country.name}</option>)}</select></label>
            <p className="fine-note">日本は比較の基準なので、常に表示します。</p>
          </details>
        </section>}
      </div>
    </div>
    {data && <>
      <div className="world-grid-2">
        <section className="lower-panel" aria-labelledby="world-latest-heading"><h3 id="world-latest-heading">最新年の順位（{METRIC_SHORT[shown.metric]}）</h3>{shown.metric === 'realGdp' ? <p className="fine-note">実質GDPは伸びの積み上げなので、水準の順位はありません。一人あたりGDPか名目GDPの順位を見てください。</p> : <LatestTable data={data} view={shown} />}</section>
        <section className="lower-panel" aria-labelledby="world-growth-heading"><h3 id="world-growth-heading">期間平均成長率の順位：{periodLabel(shown.period)}</h3>
          <div className="world-segment" role="group" aria-label="平均する値"><button type="button" aria-pressed={shown.basis === 'real'} onClick={() => change({ basis: 'real' }, 'replace')}>実質GDP</button><button type="button" aria-pressed={shown.basis === 'perCapita'} onClick={() => change({ basis: 'perCapita' }, 'replace')}>一人あたり（購買力平価）</button></div>
          <GrowthBars data={data} view={shown} />
          <p className="fine-note">人口が減る国では、国全体の伸びより一人あたりの伸びの方が実感に近いことがあります。</p>
        </section>
      </div>
      <section className="lower-panel" aria-labelledby="world-notes-heading"><h3 id="world-notes-heading">注記と出典</h3>
        <ul className="world-notes">{data.notes.map(note => <li key={note}>{note}</li>)}<li>実質GDPは、年ごとの実質成長率を積み上げた指数です。世界銀行の実質GDP（2015年基準の米ドル）を1990年＝100にした値と、世界銀行出典のすべての国で0.03ポイント以内で一致することを確かめています（台湾はIMFの値のため未照合）。</li><li>取得日時：{new Date(data.fetchedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}（日本時間）</li></ul>
        <details><summary>各国の出典を確認する</summary><ul className="world-sources">{data.countries.map(country => <li key={country.code}><span>{country.name}（{country.provider}）</span>{(Object.keys(METRIC_PARAM) as WorldMetric[]).filter(metric => metric !== 'realGdp' && country.sourceUrls[metric]).map(metric => <a key={metric} href={country.sourceUrls[metric]} target="_blank" rel="noopener noreferrer">{METRIC_SHORT[metric]}</a>)}</li>)}</ul></details>
        <p><a href="/history">日本の長期推移を詳しく読む</a></p>
      </section>
    </>}
    <MissedGrowthSummary />
    <section id="growth-causes" className="world-causes"><GrowthCauses /></section>
  </main></SiteShell>;
}
