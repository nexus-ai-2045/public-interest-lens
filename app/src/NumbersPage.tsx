import { useEffect, useRef, useState } from 'react';
import { SiteShell } from './SiteHeader';
import { useTone } from './site-tone';
import { CountUp, Reveal, useInView } from './motion';
import {
  chartsUrl, magnitudeLabel, niceMax, parseCharts, SIDE_LABEL, ticks, timelineValues, UNDETERMINED_NOTE, yen,
  type Ledger, type PublicCharts, type Side,
} from './numbers-view';
import './numbers.css';

type Tip = { x: number; y: number; text: string } | null;

/** グラフの上に出す吹き出し。マウスでもタッチでも、棒に触れた所に出る。 */
function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return <div className="nc-tip" role="status" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>;
}

function useTip(): [Tip, (e: React.PointerEvent | React.FocusEvent, text: string) => void, () => void, React.RefObject<HTMLDivElement | null>] {
  const [tip, setTip] = useState<Tip>(null);
  const box = useRef<HTMLDivElement>(null);
  const show = (e: React.PointerEvent | React.FocusEvent, text: string) => {
    const rect = box.current?.getBoundingClientRect();
    const target = (e.target as Element).getBoundingClientRect();
    const x = 'clientX' in e && e.clientX ? e.clientX : target.left + target.width / 2;
    const y = 'clientY' in e && e.clientY ? e.clientY : target.top;
    setTip({ x: x - (rect?.left ?? 0), y: y - (rect?.top ?? 0), text });
  };
  return [tip, show, () => setTip(null), box];
}

function Legend({ sides }: { sides: Side[] }) {
  return <p className="nc-legend">{sides.map(s => <span key={s} className={`nc-key ${s}`}><i aria-hidden="true" />{SIDE_LABEL[s]}</span>)}</p>;
}

const SIDES: Side[] = ['loss', 'benefit', 'undetermined'];

/** 額の分布：観測（同じ観測を共有する法律は1つ）の中央値の桁ごとの数。向き未確定は国賊側・国士側に入れず、別の棒にする。 */
function Histogram({ data }: { data: PublicCharts['histogram'] }) {
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, 0.2);
  const [tip, show, hide, box] = useTip();
  const max = niceMax(Math.max(...data.flatMap(d => SIDES.map(s => d[s]))));
  const W = 640, H = 260, L = 36, B = 40, T = 10, slot = (W - L) / data.length, bw = Math.min(22, slot / 3 - 3);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return <div className="nc-figure" ref={box}>
    <Legend sides={SIDES} />
    <div className="nc-scroll"><svg ref={ref} viewBox={`0 0 ${W} ${H}`} className={`nc-svg ${inView ? 'is-in' : ''}`} role="img" aria-label="法律の額の桁ごとの観測の数">
      {ticks(max).map(t => <g key={t}><line className="nc-grid" x1={L} x2={W} y1={y(t)} y2={y(t)} /><text className="nc-axis" x={L - 6} y={y(t) + 4} textAnchor="end">{t}</text></g>)}
      {data.map((d, i) => {
        const cx = L + slot * i + slot / 2;
        return <g key={d.exp}>
          {SIDES.map((s, j) => {
            const v = d[s], x = cx + (j - 1.5) * (bw + 2) + 1, h = y(0) - y(v);
            const text = `${magnitudeLabel(d.exp)}台：${SIDE_LABEL[s]} ${v}個`;
            return <g key={s}>
              <rect className={`nc-bar ${s}`} x={x} y={y(v)} width={bw} height={Math.max(0, h)} rx={4} style={{ transitionDelay: `${i * 60}ms` }} />
              <rect className="nc-hit" x={x - 3} y={T} width={bw + 6} height={H - T - B} tabIndex={0} aria-label={text} onPointerEnter={e => show(e, text)} onPointerMove={e => show(e, text)} onPointerLeave={hide} onFocus={e => show(e, text)} onBlur={hide} />
            </g>;
          })}
          <text className="nc-axis" x={cx} y={H - B + 18} textAnchor="middle">{magnitudeLabel(d.exp)}〜</text>
        </g>;
      })}
      <line className="nc-base" x1={L} x2={W} y1={y(0)} y2={y(0)} />
    </svg></div>
    <Tooltip tip={tip} />
  </div>;
}

/**
 * 時系列：施行年ごとの額（国士は上、国賊は下）。確かな額・参考の額（向きあり）・参考の額（向き未確定）は切り替えて別々に出す（1つの軸に混ぜない）。
 * 向き未確定は向きが無いので、上下に分けず、基線から上へ大きさだけを出す。
 */
function Timeline({ data }: { data: PublicCharts['timeline'] }) {
  const [ledger, setLedger] = useState<Ledger>('confirmed');
  const oneSided = ledger === 'undetermined';
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, 0.2);
  const [tip, show, hide, box] = useTip();
  const values = data.map(d => ({ year: d.year, laws: d.laws, ...timelineValues(d, ledger) }));
  const max = niceMax(Math.max(1, ...values.flatMap(v => [v.up, v.down])));
  const W = 680, H = 300, L = 64, T = 12, B = 30, half = oneSided ? H - T - B : (H - T - B) / 2, mid = T + half;
  const slot = (W - L) / values.length, bw = Math.max(4, slot - 4);
  const scale = (v: number) => v / max * half;
  return <div className="nc-figure" ref={box}>
    <div className="nc-switch" role="group" aria-label="額の種類">
      <button type="button" aria-pressed={ledger === 'confirmed'} onClick={() => setLedger('confirmed')}>確かな額（高・中・低）</button>
      <button type="button" aria-pressed={ledger === 'reference'} onClick={() => setLedger('reference')}>参考の額（向きあり）</button>
      <button type="button" aria-pressed={ledger === 'undetermined'} onClick={() => setLedger('undetermined')}>参考の額（向き未確定）</button>
    </div>
    <Legend sides={oneSided ? ['undetermined'] : ['benefit', 'loss']} />
    {oneSided && <p className="nc-undetermined-note" role="note">{UNDETERMINED_NOTE}</p>}
    <div className="nc-scroll"><svg ref={ref} viewBox={`0 0 ${W} ${H}`} className={`nc-svg ${inView ? 'is-in' : ''}`} role="img" aria-label="施行年ごとの額">
      {(oneSided ? [max, max / 2, 0] : [max, max / 2, 0, max / 2, max]).map((t, i) => {
        const yy = T + half * i / 2;
        return <g key={i}><line className="nc-grid" x1={L} x2={W} y1={yy} y2={yy} /><text className="nc-axis" x={L - 6} y={yy + 4} textAnchor="end">{oneSided ? '' : i < 2 ? '+' : i > 2 ? '−' : ''}{yen(t)}</text></g>;
      })}
      {values.map((v, i) => {
        const x = L + slot * i + 2;
        const text = oneSided
          ? `${v.year}年施行（額のある法律${v.laws}本）：${SIDE_LABEL.undetermined}の差の大きさ ${yen(v.up)}`
          : `${v.year}年施行（${v.laws}本）：${SIDE_LABEL.benefit} ${yen(v.up)}・${SIDE_LABEL.loss} ${yen(v.down)}`;
        return <g key={v.year}>
          <rect className={`nc-bar ${oneSided ? 'undetermined' : 'benefit'} grow-up`} x={x} y={mid - scale(v.up) - 1} width={bw} height={Math.max(0, scale(v.up))} rx={3} style={{ transitionDelay: `${i * 25}ms` }} />
          {!oneSided && <rect className="nc-bar loss grow-down" x={x} y={mid + 1} width={bw} height={Math.max(0, scale(v.down))} rx={3} style={{ transitionDelay: `${i * 25}ms` }} />}
          <rect className="nc-hit" x={x - 1} y={T} width={bw + 2} height={H - T - B} tabIndex={0} aria-label={text} onPointerEnter={e => show(e, text)} onPointerMove={e => show(e, text)} onPointerLeave={hide} onFocus={e => show(e, text)} onBlur={hide} />
          {(i % 5 === 0 || (i === values.length - 1 && i % 5 > 2)) && <text className="nc-axis" x={x + bw / 2} y={H - 8} textAnchor="middle">{v.year}</text>}
        </g>;
      })}
      <line className="nc-base" x1={L} x2={W} y1={mid} y2={mid} />
    </svg></div>
    <Tooltip tip={tip} />
    <p className="fine-note">同じ観測を共有する法律は、観測の額を1回だけ、代表の1本（確かさの高い順、同じなら id の順の先頭）の年に数えます（同じ差を何度も数えない）。施行日が無い法律は公布日で推定した年です。{oneSided && '向き未確定の棒は、向きの違う差も大きさのまま積んだ値で、損失や便益の合計ではありません。期間の重なる群があるので、年をまたいで足さないでください。'}</p>
  </div>;
}

export function NumbersPage() {
  useEffect(() => { document.title = '数字で見る｜国賊／国士ランキング'; }, []);
  const [tone] = useTone();
  const [charts, setCharts] = useState<PublicCharts | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(chartsUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error(`読み込めませんでした（${response.status}）`);
        setCharts(parseCharts(await response.json()));
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => controller.abort();
  }, []);
  const side: Side = tone === 'harm' ? 'loss' : 'benefit';
  const counts = charts?.byCertainty ?? [];
  const confirmed = counts.filter(c => c.certainty !== '参考').reduce((s, c) => s + c.laws, 0);
  const reference = counts.find(c => c.certainty === '参考')?.laws ?? 0;
  const undetermined = counts.reduce((s, c) => s + c.undetermined, 0);
  return <SiteShell active="/numbers" label="数字で見る" className="law-ranking numbers-page">
    <main id="main">
      <h1>数字で見る</h1>
      <p className="nc-lead">法律ごとの額と、施行の年ごとの推移を、同じデータベースから描いています。計算の式は<a href="/methodology#formulas">計算方法</a>、元の表は <a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/データベース.md" target="_blank" rel="noopener noreferrer">データベースの説明</a>にあります。</p>
      {error && <p className="state-banner">{error}</p>}
      {!charts && !error && <p className="empty-state">読み込み中…</p>}
      {charts && <>
        <Reveal tone={side} className="nc-hero">
          <div><strong><CountUp value={confirmed} format={n => `${Math.round(n)}`} /></strong><span>本：確かな額（高・中・低）</span></div>
          <div><strong><CountUp value={reference} format={n => `${Math.round(n)}`} /></strong><span>本：参考の額</span></div>
          <div><strong><CountUp value={undetermined} format={n => `${Math.round(n)}`} /></strong><span>本：うち向き未確定（側に分けない）</span></div>
        </Reveal>

        <section className="nc-section">
          <h3>1. 法律の額はどのくらいの大きさか</h3>
          <p>額の出た観測（同じ観測を共有する法律は1つ）を、中央値の桁ごとに数えました。多くは1兆〜100兆円の桁です。</p>
          <p className="nc-undetermined-note" role="note">{UNDETERMINED_NOTE}</p>
          <Histogram data={charts.histogram} />
          <table className="nc-certainty"><caption>確かさごとの本数</caption>
            <thead><tr><th scope="col">確かさ</th><th scope="col">国賊側</th><th scope="col">国士側</th><th scope="col">向き未確定</th><th scope="col">計</th></tr></thead>
            <tbody>{counts.map(c => <tr key={c.certainty}><th scope="row">{c.certainty}</th><td className="num">{c.loss}</td><td className="num">{c.benefit}</td><td className="num">{c.undetermined}</td><td className="num">{c.laws}</td></tr>)}</tbody>
          </table>
        </section>

        <section className="nc-section">
          <h3>2. いつ施行された法律の額か</h3>
          <Timeline data={charts.timeline} />
        </section>

        <p className="fine-note">計算方法の版：{charts.spec}。入力の照合値 {charts.inputs.slice(0, 12)}…</p>
      </>}
    </main>
  </SiteShell>;
}
