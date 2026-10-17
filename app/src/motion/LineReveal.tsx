import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useInView, usePrefersReducedMotion } from './useMotion';

export type LineSeries = { id: string; label: string; points: { year: number; value: number | null }[] };

const W = 900, H = 360, PAD = { top: 16, right: 132, bottom: 32, left: 56 };

/** 終端ラベルが重ならないように、上から順に最小の間隔をあけて並べる。 */
export function spreadLabels(ys: number[], gap = 16, min = PAD.top, max = H - PAD.bottom): number[] {
  const order = ys.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y);
  const placed: number[] = [];
  for (const [i, item] of order.entries()) placed[i] = Math.max(item.y, i ? placed[i - 1] + gap : min);
  const overflow = (placed.at(-1) ?? 0) - max;
  if (overflow > 0) for (let i = placed.length - 1; i >= 0; i--) placed[i] = Math.min(placed[i], (i === placed.length - 1 ? max : placed[i + 1] - gap));
  const result = new Array<number>(ys.length);
  order.forEach((item, i) => { result[item.index] = placed[i]; });
  return result;
}

/** 基準年を 100 にそろえる。基準年の値が無い系列は出さない（0 で埋めない）。 */
export function indexSeries(series: LineSeries[], baseYear: number): LineSeries[] {
  return series.flatMap(item => {
    const base = item.points.find(point => point.year === baseYear)?.value;
    if (!base) return [];
    return [{ ...item, points: item.points.map(point => ({ year: point.year, value: point.value === null ? null : point.value / base * 100 })) }];
  });
}

/**
 * OWID 型の折れ線。注目の系列（日本）だけ色をつけ、ほかは灰色。凡例の代わりに線の終わりに名前を置く。
 * 画面に入ったら線を描く。矢印キーとポインタで年を動かし、その年の値を読める。
 */
export function LineReveal({ series, highlightId, format, caption, indexed = false, baseYear }: { series: LineSeries[]; highlightId?: string; format: (value: number) => string; caption: string; indexed?: boolean; baseYear?: number }) {
  const root = useRef<HTMLDivElement>(null);
  const inView = useInView(root, 0.25);
  const reduced = usePrefersReducedMotion();
  const titleId = useId();
  const shown = useMemo(() => indexed && baseYear !== undefined ? indexSeries(series, baseYear) : series, [series, indexed, baseYear]);
  const years = useMemo(() => [...new Set(shown.flatMap(item => item.points.map(point => point.year)))].sort((a, b) => a - b), [shown]);
  const values = shown.flatMap(item => item.points.flatMap(point => point.value === null ? [] : [point.value]));
  const [focusYear, setFocusYear] = useState<number | null>(null);
  if (!years.length || !values.length) return <p className="empty-state" role="status">表示できる値がありません。</p>;
  const lo = Math.min(...values, indexed ? 100 : 0), hi = Math.max(...values);
  const x = (year: number) => PAD.left + (years.length === 1 ? 0 : (year - years[0]) / (years.at(-1)! - years[0]) * (W - PAD.left - PAD.right));
  const y = (value: number) => H - PAD.bottom - (value - lo) / (hi - lo || 1) * (H - PAD.top - PAD.bottom);
  const path = (item: LineSeries) => item.points.reduce((d, point, i, all) => point.value === null ? d : `${d}${i && all[i - 1].value !== null ? 'L' : 'M'}${x(point.year).toFixed(1)},${y(point.value).toFixed(1)}`, '');
  const lastPoint = (item: LineSeries) => [...item.points].reverse().find(point => point.value !== null);
  const ordered = [...shown].sort((a, b) => (a.id === highlightId ? 1 : 0) - (b.id === highlightId ? 1 : 0));
  const ends = ordered.map(item => lastPoint(item));
  const labelYs = spreadLabels(ends.map(point => point ? y(point.value!) : H));
  const ticks = Array.from({ length: 5 }, (_, i) => lo + (hi - lo) * i / 4);
  const yearTicks = years.filter((year, i) => i === 0 || i === years.length - 1 || year % 10 === 0);
  const move = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - box.left) / box.width * W;
    setFocusYear(years.reduce((best, year) => Math.abs(x(year) - px) < Math.abs(x(best) - px) ? year : best, years[0]));
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const index = focusYear === null ? years.length - 1 : years.indexOf(focusYear);
    const next = event.key === 'ArrowLeft' ? index - 1 : event.key === 'ArrowRight' ? index + 1 : event.key === 'Home' ? 0 : event.key === 'End' ? years.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    setFocusYear(years[Math.max(0, Math.min(years.length - 1, next))]);
  };
  const readout = focusYear === null ? '' : `${focusYear}年：${shown.map(item => { const value = item.points.find(point => point.year === focusYear)?.value; return `${item.label} ${value === null || value === undefined ? '未取得' : format(value)}`; }).join('、')}`;
  return <div ref={root} className={`m-line ${inView || reduced ? 'is-in' : ''}`}>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={titleId} tabIndex={0} onPointerMove={move} onPointerLeave={() => setFocusYear(null)} onKeyDown={key} onBlur={() => setFocusYear(null)}>
      <title id={titleId}>{caption}。矢印キーで年を動かすと、その年の値を読み上げます。</title>
      {ticks.map(tick => <g key={tick} className="m-line-grid"><line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} /><text x={PAD.left - 8} y={y(tick) + 4} textAnchor="end">{format(tick)}</text></g>)}
      {yearTicks.map(year => <text key={year} className="m-line-year" x={x(year)} y={H - 8} textAnchor="middle">{year}</text>)}
      {ordered.map((item, index) => <path key={item.id} className={`m-line-path ${item.id === highlightId ? 'is-highlight' : ''}`} d={path(item)} pathLength={1} style={{ transitionDelay: `${item.id === highlightId ? ordered.length * 60 : index * 60}ms` }} />)}
      {ordered.map((item, index) => ends[index] && <g key={item.id} className={`m-line-end ${item.id === highlightId ? 'is-highlight' : ''}`}><circle cx={x(ends[index]!.year)} cy={y(ends[index]!.value!)} r={item.id === highlightId ? 4.5 : 3} /><text x={W - PAD.right + 10} y={labelYs[index] + 4}>{item.label}</text></g>)}
      {focusYear !== null && <g className="m-line-focus"><line x1={x(focusYear)} x2={x(focusYear)} y1={PAD.top} y2={H - PAD.bottom} />{shown.map(item => { const value = item.points.find(point => point.year === focusYear)?.value; return value === null || value === undefined ? null : <circle key={item.id} className={item.id === highlightId ? 'is-highlight' : ''} cx={x(focusYear)} cy={y(value)} r={4} />; })}</g>}
    </svg>
    <p className="m-line-readout" aria-live="polite">{readout || '線の上をなぞるか、図を選んで矢印キーを押すと、その年の値が出ます。'}</p>
  </div>;
}
