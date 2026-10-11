import { useEffect, useRef, useState } from 'react';
import gsap from 'gsap';
import { economy, periodGrowth, seriesById } from './economy';

const W = 760;
const H = 300;
const PAD = { l: 56, r: 24, t: 24, b: 36 };
const EDGES = [1980, 1990, 2000, 2010, 2020, 2025];

/** 実在データ（日本の一人当たり実質GDP）。架空ランキングとは別の区画に表示します。 */
export function GdpChart({ reduce }: { reduce: boolean }) {
  const s = seriesById('real_gdp_per_capita');
  const pts = s.points;
  const pathRef = useRef<SVGPathElement>(null);
  const areaRef = useRef<SVGPathElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const y0 = pts[0].year;
  const y1 = pts[pts.length - 1].year;
  const vmax = Math.max(...pts.map((p) => p.value)) * 1.08;
  const X = (yr: number) => PAD.l + ((yr - y0) / (y1 - y0)) * (W - PAD.l - PAD.r);
  const Y = (v: number) => H - PAD.b - (v / vmax) * (H - PAD.t - PAD.b);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.year).toFixed(1)} ${Y(p.value).toFixed(1)}`).join('');
  const area = `${line}L${X(y1)} ${H - PAD.b}L${X(y0)} ${H - PAD.b}Z`;
  const ticks = [0, 1e6, 2e6, 3e6, 4e6, 5e6].filter((v) => v < vmax);
  const growth = periodGrowth(pts, EDGES);

  useEffect(() => {
    const path = pathRef.current;
    const wrap = wrapRef.current;
    if (!path || !wrap || reduce) return;
    const len = path.getTotalLength();
    gsap.set(path, { strokeDasharray: len, strokeDashoffset: len });
    gsap.set(areaRef.current, { opacity: 0 });
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      gsap.to(path, { strokeDashoffset: 0, duration: 2.2, ease: 'power2.inOut' });
      gsap.to(areaRef.current, { opacity: 1, duration: 1.6, delay: 0.9 });
      gsap.from(wrap.querySelectorAll('.growth-chip'), { y: 24, opacity: 0, stagger: 0.08, duration: 0.7, ease: 'expo.out', delay: 0.6 });
      io.disconnect();
    }, { threshold: 0.35 });
    io.observe(wrap);
    return () => io.disconnect();
  }, [reduce]);

  const hp = hover === null ? null : pts[hover];
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W;
    const yr = Math.round(y0 + ((x - PAD.l) / (W - PAD.l - PAD.r)) * (y1 - y0));
    const i = pts.findIndex((p) => p.year === Math.min(y1, Math.max(y0, yr)));
    setHover(i < 0 ? null : i);
  };

  return (
    <section className="gdp" id="gdp" aria-labelledby="gdp-title" ref={wrapRef}>
      <div className="section-head">
        <p className="eyebrow real">実データ・{economy.provider}</p>
        <h2 id="gdp-title">日本の一人当たり実質GDP</h2>
        <p className="lede">1980年から2025年まで。1990年代から伸びが細っていることが、数字だけで見えます。</p>
      </div>
      <div className="chart-card">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="日本の一人当たり実質GDPの推移 1980〜2025年" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          <defs>
            <linearGradient id="gdp-fill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--real)" stopOpacity="0.35" />
              <stop offset="100%" stopColor="var(--real)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={Y(v)} y2={Y(v)} className="grid" />
              <text x={PAD.l - 8} y={Y(v) + 4} textAnchor="end" className="axis">{v / 1e4}万円</text>
            </g>
          ))}
          {EDGES.map((yr) => (
            <text key={yr} x={X(yr)} y={H - 12} textAnchor="middle" className="axis">{yr}</text>
          ))}
          <path ref={areaRef} d={area} fill="url(#gdp-fill)" />
          <path ref={pathRef} d={line} fill="none" stroke="var(--real)" strokeWidth="2.5" strokeLinejoin="round" />
          {hp && (
            <g>
              <line x1={X(hp.year)} x2={X(hp.year)} y1={PAD.t} y2={H - PAD.b} className="cursor" />
              <circle cx={X(hp.year)} cy={Y(hp.value)} r="5" fill="var(--real)" />
            </g>
          )}
        </svg>
        <p className="readout" aria-live="polite">
          {hp ? <><strong>{hp.year}年</strong> 一人当たり {Math.round(hp.value / 1e4).toLocaleString('ja-JP')}万円</> : 'グラフに触れると、その年の値が出ます。'}
        </p>
      </div>
      <div className="growth">
        {growth.map((g) => (
          <div key={g.from} className="growth-chip">
            <span>{g.from}–{g.to}</span>
            <strong>{g.rate === null ? '—' : `${g.rate >= 0 ? '+' : ''}${g.rate.toFixed(1)}%`}</strong>
            <small>年平均</small>
          </div>
        ))}
      </div>
      <p className="fine">
        出典：<a href={s.sourceUrl} target="_blank" rel="noreferrer">世界銀行 WDI（実質GDP・円・一定価格）</a>と人口から計算した値。
        観測 {economy.observedAt.slice(0, 10)}。年平均成長率は機械計算です。{economy.note}
      </p>
    </section>
  );
}
