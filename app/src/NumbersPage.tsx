import { useEffect, useMemo, useRef, useState } from 'react';
import { SiteShell } from './SiteHeader';
import { useTone } from './site-tone';
import { CountUp, RankBars, Reveal, useInView } from './motion';
import {
  chartsUrl, magnitudeLabel, memberHref, memberRange, niceMax, parseCharts, roleShares, SIDE_LABEL, ticks, timelineValues, topMembers, yen,
  type PublicCharts, type Side,
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

/** 額の分布：観測（同じ観測を共有する法律は1つ）の中央値の桁ごとの数。 */
function Histogram({ data }: { data: PublicCharts['histogram'] }) {
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, 0.2);
  const [tip, show, hide, box] = useTip();
  const max = niceMax(Math.max(...data.flatMap(d => [d.loss, d.benefit])));
  const W = 640, H = 260, L = 36, B = 40, T = 10, slot = (W - L) / data.length, bw = Math.min(28, slot / 2 - 4);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return <div className="nc-figure" ref={box}>
    <Legend sides={['loss', 'benefit']} />
    <div className="nc-scroll"><svg ref={ref} viewBox={`0 0 ${W} ${H}`} className={`nc-svg ${inView ? 'is-in' : ''}`} role="img" aria-label="法律の額の桁ごとの観測の数">
      {ticks(max).map(t => <g key={t}><line className="nc-grid" x1={L} x2={W} y1={y(t)} y2={y(t)} /><text className="nc-axis" x={L - 6} y={y(t) + 4} textAnchor="end">{t}</text></g>)}
      {data.map((d, i) => {
        const cx = L + slot * i + slot / 2;
        return <g key={d.exp}>
          {(['loss', 'benefit'] as const).map((s, j) => {
            const v = d[s], x = cx + (j === 0 ? -bw - 1 : 1), h = y(0) - y(v);
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

/** 時系列：施行年ごとの額（国士は上、国賊は下）。確かな額と参考の額は桁が違うので切り替えて別々に出す（1つの軸に混ぜない）。 */
function Timeline({ data }: { data: PublicCharts['timeline'] }) {
  const [ledger, setLedger] = useState<'confirmed' | 'reference'>('confirmed');
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, 0.2);
  const [tip, show, hide, box] = useTip();
  const values = data.map(d => ({ year: d.year, laws: d.laws, ...timelineValues(d, ledger) }));
  const max = niceMax(Math.max(1, ...values.flatMap(v => [v.up, v.down])));
  const W = 680, H = 300, L = 64, T = 12, B = 30, mid = T + (H - T - B) / 2, half = (H - T - B) / 2;
  const slot = (W - L) / values.length, bw = Math.max(4, slot - 4);
  const scale = (v: number) => v / max * half;
  return <div className="nc-figure" ref={box}>
    <div className="nc-switch" role="group" aria-label="額の種類">
      <button type="button" aria-pressed={ledger === 'confirmed'} onClick={() => setLedger('confirmed')}>確かな額（高・中・低）</button>
      <button type="button" aria-pressed={ledger === 'reference'} onClick={() => setLedger('reference')}>参考の額</button>
    </div>
    <Legend sides={['benefit', 'loss']} />
    <div className="nc-scroll"><svg ref={ref} viewBox={`0 0 ${W} ${H}`} className={`nc-svg ${inView ? 'is-in' : ''}`} role="img" aria-label="施行年ごとの額">
      {[max, max / 2, 0, max / 2, max].map((t, i) => {
        const yy = T + half * i / 2;
        return <g key={i}><line className="nc-grid" x1={L} x2={W} y1={yy} y2={yy} /><text className="nc-axis" x={L - 6} y={yy + 4} textAnchor="end">{i < 2 ? '+' : i > 2 ? '−' : ''}{yen(t)}</text></g>;
      })}
      {values.map((v, i) => {
        const x = L + slot * i + 2;
        const text = `${v.year}年施行（${v.laws}本）：${SIDE_LABEL.benefit} ${yen(v.up)}・${SIDE_LABEL.loss} ${yen(v.down)}`;
        return <g key={v.year}>
          <rect className="nc-bar benefit grow-up" x={x} y={mid - scale(v.up) - 1} width={bw} height={Math.max(0, scale(v.up))} rx={3} style={{ transitionDelay: `${i * 25}ms` }} />
          <rect className="nc-bar loss grow-down" x={x} y={mid + 1} width={bw} height={Math.max(0, scale(v.down))} rx={3} style={{ transitionDelay: `${i * 25}ms` }} />
          <rect className="nc-hit" x={x - 1} y={T} width={bw + 2} height={H - T - B} tabIndex={0} aria-label={text} onPointerEnter={e => show(e, text)} onPointerMove={e => show(e, text)} onPointerLeave={hide} onFocus={e => show(e, text)} onBlur={hide} />
          {(i % 5 === 0 || (i === values.length - 1 && i % 5 > 2)) && <text className="nc-axis" x={x + bw / 2} y={H - 8} textAnchor="middle">{v.year}</text>}
        </g>;
      })}
      <line className="nc-base" x1={L} x2={W} y1={mid} y2={mid} />
    </svg></div>
    <Tooltip tip={tip} />
    <p className="fine-note">同じ観測を共有する法律は、観測の額を本数で割った分を足しています（同じ差を何度も数えない）。施行日が無い法律は公布日で推定した年です。</p>
  </div>;
}

/** 配り先の内訳：法律の額が、提出者・参院の賛成票・衆院の会派にどう分かれたか（100% の帯）。 */
function RoleSplit({ roles }: { roles: PublicCharts['roles'] }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, 0.2);
  return <div ref={ref} className={`nc-roles ${inView ? 'is-in' : ''}`}>
    {(['loss', 'benefit'] as const).map(side => {
      const rows = roleShares(roles, side);
      const total = rows.reduce((s, r) => s + r.value, 0);
      return <figure key={side} className={`nc-role ${side}`}>
        <figcaption>{SIDE_LABEL[side]}：配った額の合計 <strong>{yen(total)}</strong></figcaption>
        <div className="nc-stack" role="img" aria-label={rows.map(r => `${r.label} ${Math.round(r.share * 100)}%`).join('、')}>
          {rows.map((r, i) => <span key={r.role} className={`nc-seg s${i}`} style={{ width: `${r.share * 100}%` }} title={`${r.label}：${yen(r.value)}（${Math.round(r.share * 100)}%）`} />)}
        </div>
        <ul className="nc-role-list">{rows.map((r, i) => <li key={r.role}><i className={`nc-seg-key s${i}`} aria-hidden="true" />{r.label}<span>{Math.round(r.share * 100)}%・{yen(r.value)}</span></li>)}</ul>
      </figure>;
    })}
  </div>;
}

function Parties({ parties }: { parties: PublicCharts['parties'] }) {
  const top = parties.slice(0, 12);
  const max = niceMax(Math.max(1, ...top.flatMap(p => [p.loss, p.benefit])));
  const ref = useRef<HTMLTableElement>(null);
  const inView = useInView(ref, 0.2);
  return <div className="nc-figure">
    <Legend sides={['loss', 'benefit']} />
    <table ref={ref} className={`nc-party ${inView ? 'is-in' : ''}`}>
      <thead><tr><th scope="col">衆議院の会派（記録の表記）</th><th scope="col">賛成した確かな額の法律</th><th scope="col">額（国賊側／国士側）</th></tr></thead>
      <tbody>{top.map((p, i) => <tr key={p.party}>
        <th scope="row">{p.party}</th>
        <td className="num">{p.laws}本</td>
        <td>
          <span className="nc-pbar loss" style={{ width: `${p.loss / max * 100}%`, transitionDelay: `${i * 40}ms` }} title={`${SIDE_LABEL.loss} ${yen(p.loss)}`} />
          <small>{yen(p.loss)}</small>
          <span className="nc-pbar benefit" style={{ width: `${p.benefit / max * 100}%`, transitionDelay: `${i * 40}ms` }} title={`${SIDE_LABEL.benefit} ${yen(p.benefit)}`} />
          <small>{yen(p.benefit)}</small>
        </td>
      </tr>)}</tbody>
    </table>
    <p className="fine-note">これは配分ではなく、その会派が衆議院で賛成した法律の分（観測を本数で割ったもの）の合計です。同じ法律に賛成した会派はみな同じ額を数えるので、会派どうしで足し合わせません。会派の名前は議案の経過の表記のままです（同じ党でも時期で表記が変わります）。</p>
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
  const members = useMemo(() => charts ? topMembers(charts.members, tone) : [], [charts, tone]);
  const side: Side = tone === 'harm' ? 'loss' : 'benefit';
  const counts = charts?.byCertainty ?? [];
  const confirmed = counts.filter(c => c.certainty !== '参考').reduce((s, c) => s + c.laws, 0);
  const reference = counts.find(c => c.certainty === '参考')?.laws ?? 0;
  return <SiteShell active="/numbers" label="数字で見る" className="law-ranking numbers-page">
    <main id="main">
      <h1>数字で見る</h1>
      <p className="nc-lead">法律ごとの額、施行の年ごとの推移、議員と党への配り先を、同じデータベースから描いています。計算の式は<a href="/methodology#formulas">計算方法</a>、元の表は <a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/データベース.md" target="_blank" rel="noopener noreferrer">データベースの説明</a>にあります。</p>
      {error && <p className="state-banner">{error}</p>}
      {!charts && !error && <p className="empty-state">読み込み中…</p>}
      {charts && <>
        <Reveal tone={side} className="nc-hero">
          <div><strong><CountUp value={confirmed} format={n => `${Math.round(n)}`} /></strong><span>本：確かな額（高・中・低）</span></div>
          <div><strong><CountUp value={reference} format={n => `${Math.round(n)}`} /></strong><span>本：参考の額</span></div>
          <div><strong><CountUp value={charts.members.length} format={n => `${Math.round(n)}`} /></strong><span>人：確かな額を配った議員</span></div>
        </Reveal>

        <section className="nc-section">
          <h3>1. 法律の額はどのくらいの大きさか</h3>
          <p>額の出た観測（同じ観測を共有する法律は1つ）を、中央値の桁ごとに数えました。多くは1兆〜100兆円の桁です。</p>
          <Histogram data={charts.histogram} />
          <table className="nc-certainty"><caption>確かさごとの本数</caption>
            <thead><tr><th scope="col">確かさ</th><th scope="col">国賊側</th><th scope="col">国士側</th><th scope="col">計</th></tr></thead>
            <tbody>{counts.map(c => <tr key={c.certainty}><th scope="row">{c.certainty}</th><td className="num">{c.loss}</td><td className="num">{c.benefit}</td><td className="num">{c.laws}</td></tr>)}</tbody>
          </table>
        </section>

        <section className="nc-section">
          <h3>2. いつ施行された法律の額か</h3>
          <Timeline data={charts.timeline} />
        </section>

        <section className="nc-section">
          <h3>3. {tone === 'harm' ? '失わせた額の大きい議員' : '生んだ額の大きい議員'}（確かな額、上位10人）</h3>
          <RankBars items={members.map(m => ({ id: m.id, label: m.name, value: Math.abs(m.net), ...memberRange(m), side, note: `純額。失わせた額 ${yen(m.loss)}・生んだ額 ${yen(m.credit)}`, href: memberHref(m.id) }))}
            format={yen} caption={tone === 'harm' ? '失わせた額の大きい議員' : '生んだ額の大きい議員'} />
          <p className="fine-note">今の配り方（成立への寄与、causal-shapley-v1）の結果です。配り方は見直し中で、決まったら計算方法の版を上げて差し替えます。</p>
        </section>

        <section className="nc-section">
          <h3>4. 法律の額はだれに配られたか</h3>
          <RoleSplit roles={charts.roles} />
        </section>

        <section className="nc-section">
          <h3>5. 会派ごとの、賛成した法律の額</h3>
          <Parties parties={charts.parties} />
        </section>
        <p className="fine-note">計算方法の版：{charts.spec}。入力の照合値 {charts.inputs.slice(0, 12)}…</p>
      </>}
    </main>
  </SiteShell>;
}
