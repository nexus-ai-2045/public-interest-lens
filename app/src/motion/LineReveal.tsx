import { useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useInView, usePrefersReducedMotion } from './useMotion';

export type LineSeries = { id: string; label: string; points: { year: number; value: number | null }[] };

/** 幅が測れないとき（テスト・初回描画）の大きさ。 */
const DEFAULT_W = 900, DEFAULT_H = 360;
/** これより狭いとスマホ向けの作り（縦長・文字は実寸）にする。 */
const NARROW = 560;

/** 終端ラベルが重ならないように、上から順に最小の間隔をあけて並べる。 */
export function spreadLabels(ys: number[], gap = 16, min = 16, max = DEFAULT_H - 32): number[] {
  const order = ys.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y);
  const placed: number[] = [];
  for (const [i, item] of order.entries()) placed[i] = Math.max(item.y, i ? placed[i - 1] + gap : min);
  const overflow = (placed.at(-1) ?? 0) - max;
  if (overflow > 0) for (let i = placed.length - 1; i >= 0; i--) placed[i] = Math.min(placed[i], (i === placed.length - 1 ? max : placed[i + 1] - gap));
  const result = new Array<number>(ys.length);
  order.forEach((item, i) => { result[item.index] = placed[i]; });
  return result;
}

/**
 * 線の終わりに名前を出す系列を選ぶ。必ず出すもの（日本・選んだ国）を先に置き、
 * 残りは値の大きい順（上から）に、すでに置いた名前と gap 未満に近づかないものだけ出す。
 * 名前を線の終わりから動かさずに済むので、どの線の名前かが一目で分かる。
 */
export function pickLabels(items: { y: number; force?: boolean }[], gap: number): boolean[] {
  const chosen = items.map(item => !!item.force);
  const taken = items.filter(item => item.force).map(item => item.y);
  items.map((item, index) => ({ ...item, index })).filter(item => !item.force).sort((a, b) => a.y - b.y).forEach(item => {
    if (taken.every(y => Math.abs(y - item.y) >= gap)) { chosen[item.index] = true; taken.push(item.y); }
  });
  return chosen;
}

/** 基準年を 100 にそろえる。基準年の値が無い系列は出さない（0 で埋めない）。 */
export function indexSeries(series: LineSeries[], baseYear: number): LineSeries[] {
  return series.flatMap(item => {
    const base = item.points.find(point => point.year === baseYear)?.value;
    if (!base) return [];
    return [{ ...item, points: item.points.map(point => ({ year: point.year, value: point.value === null ? null : point.value / base * 100 })) }];
  });
}

/** 画面の幅に合わせた図の寸法。SVG の 1 単位を画面の 1px にそろえ、文字が縮まないようにする。 */
function layout(width: number, labelChars: number) {
  const narrow = width < NARROW;
  const label = narrow ? 12 : 13;
  const height = Math.round(narrow ? Math.min(340, Math.max(280, width * 0.85)) : Math.min(420, Math.max(300, width * 0.42)));
  const right = Math.min(narrow ? 100 : 160, labelChars * (label + 1) + 18);
  return { narrow, width, height, gap: label + 4, pad: { top: 24, right, bottom: 28, left: 2 } };
}

/**
 * OWID 型の折れ線。注目の系列（日本）だけ色をつけ、ほかは灰色。線の終わりに名前を置く。
 * 名前が重なる国は線の終わりに出さず、図の下の一覧（値の大きい順）に出す。一覧の国を選ぶと、その線を濃くして名前を出す。
 * 画面に入ったら線を描く。矢印キーとポインタで年を動かし、その年の値を一覧と読み上げで読める。
 */
export function LineReveal({ series, highlightId, format, caption, indexed = false, baseYear, unit }: { series: LineSeries[]; highlightId?: string; format: (value: number) => string; caption: string; indexed?: boolean; baseYear?: number; unit?: string }) {
  const root = useRef<HTMLDivElement>(null);
  const inView = useInView(root, 0.25);
  const reduced = usePrefersReducedMotion();
  const titleId = useId();
  const [width, setWidth] = useState(DEFAULT_W);
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => { const next = Math.round(element.clientWidth); if (next > 0) setWidth(next); };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const shown = useMemo(() => indexed && baseYear !== undefined ? indexSeries(series, baseYear) : series, [series, indexed, baseYear]);
  const years = useMemo(() => [...new Set(shown.flatMap(item => item.points.map(point => point.year)))].sort((a, b) => a - b), [shown]);
  const values = shown.flatMap(item => item.points.flatMap(point => point.value === null ? [] : [point.value]));
  const [focusYear, setFocusYear] = useState<number | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  if (!years.length || !values.length) return <p className="empty-state" role="status">表示できる値がありません。</p>;
  const { narrow, width: W, height: H, gap, pad: PAD } = layout(width, Math.max(2, ...shown.map(item => item.label.length)));
  const lo = Math.min(...values, indexed ? 100 : 0), hi = Math.max(...values);
  const x = (year: number) => PAD.left + (years.length === 1 ? 0 : (year - years[0]) / (years.at(-1)! - years[0]) * (W - PAD.left - PAD.right));
  const y = (value: number) => H - PAD.bottom - (value - lo) / (hi - lo || 1) * (H - PAD.top - PAD.bottom);
  const path = (item: LineSeries) => item.points.reduce((d, point, i, all) => point.value === null ? d : `${d}${i && all[i - 1].value !== null ? 'L' : 'M'}${x(point.year).toFixed(1)},${y(point.value).toFixed(1)}`, '');
  const lastPoint = (item: LineSeries) => [...item.points].reverse().find(point => point.value !== null);
  const rank = (item: LineSeries) => item.id === highlightId ? 2 : item.id === picked ? 1 : 0;
  const ordered = [...shown].sort((a, b) => rank(a) - rank(b));
  const ends = ordered.map(item => lastPoint(item));
  const endYs = ends.map(point => point ? y(point.value!) : H);
  const labeled = pickLabels(ordered.map((item, index) => ({ y: endYs[index], force: rank(item) > 0 && !!ends[index] })), gap);
  const labelIndexes = ordered.flatMap((_, index) => labeled[index] && ends[index] ? [index] : []);
  const spread = spreadLabels(labelIndexes.map(index => endYs[index]), gap, PAD.top, H - PAD.bottom);
  const labelYs = new Map(labelIndexes.map((index, i) => [index, spread[i]]));
  const tickCount = narrow ? 4 : 5;
  const ticks = Array.from({ length: tickCount }, (_, i) => lo + (hi - lo) * i / (tickCount - 1));
  const step = narrow && years.at(-1)! - years[0] > 40 ? 20 : 10;
  const minGap = narrow ? 48 : 56;
  const yearTicks = years.filter((year, i) => i === 0 || i === years.length - 1 || (year % step === 0 && x(year) - x(years[0]) >= minGap && x(years.at(-1)!) - x(year) >= minGap));
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
  const valueAt = (item: LineSeries, year: number) => item.points.find(point => point.year === year)?.value ?? null;
  /** 一覧の値：年を選んでいればその年、選んでいなければ各国の最新の値。 */
  const rows = shown.map(item => {
    const point = focusYear === null ? lastPoint(item) : { year: focusYear, value: valueAt(item, focusYear) };
    return { item, value: point?.value ?? null, year: point?.year };
  }).sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
  const highlightRow = rows.find(row => row.item.id === highlightId);
  const counted = rows.filter(row => row.value !== null);
  const highlightRank = highlightRow && highlightRow.value !== null ? counted.indexOf(highlightRow) + 1 : 0;
  const lastYear = years.at(-1)!;
  const readout = focusYear === null ? '' : `${focusYear}年：${rows.map(row => `${row.item.label} ${row.value === null ? '未取得' : format(row.value)}`).join('、')}`;
  const summary = !highlightRow ? '' : `${focusYear === null ? `最新（${highlightRow.year ?? lastYear}年）` : `${focusYear}年`}　${highlightRow.item.label} ${highlightRow.value === null ? '未取得' : `${format(highlightRow.value)}（${counted.length}か国・地域中${highlightRank}位）`}`;
  const lineClass = (item: LineSeries) => item.id === highlightId ? 'is-highlight' : item.id === picked ? 'is-picked' : '';
  return <div ref={root} className={`m-line ${narrow ? 'is-narrow' : ''} ${inView || reduced ? 'is-in' : ''}`}>
    {unit && <p className="m-line-unit" aria-hidden="true">縦軸：{unit}</p>}
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-labelledby={titleId} tabIndex={0} onPointerMove={move} onPointerDown={move} onPointerLeave={() => setFocusYear(null)} onKeyDown={key} onBlur={() => setFocusYear(null)}>
      <title id={titleId}>{caption}{unit ? `（縦軸：${unit}）` : ''}。矢印キーで年を動かすと、その年の値を読み上げます。</title>
      {ticks.map(tick => <g key={tick} className="m-line-grid"><line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} /><text x={PAD.left} y={y(tick) - 5}>{format(tick)}</text></g>)}
      {yearTicks.map((year, i) => <text key={year} className="m-line-year" x={x(year)} y={H - 8} textAnchor={i === 0 ? 'start' : i === yearTicks.length - 1 ? 'end' : 'middle'}>{year}</text>)}
      {ordered.map((item, index) => <path key={item.id} className={`m-line-path ${lineClass(item)}`} d={path(item)} pathLength={1} style={{ transitionDelay: `${item.id === highlightId ? ordered.length * 60 : index * 60}ms` }} />)}
      {ordered.map((item, index) => {
        const end = ends[index];
        if (!end) return null;
        const ly = labelYs.get(index);
        const cx = x(end.year), cy = endYs[index];
        return <g key={item.id} className={`m-line-end ${lineClass(item)}`}>
          <circle cx={cx} cy={cy} r={rank(item) ? 4.5 : 3} />
          {ly !== undefined && Math.abs(ly - cy) > 2 && <polyline className="m-line-leader" points={`${cx + 5},${cy} ${W - PAD.right + 6},${ly}`} />}
          {ly !== undefined && <text x={W - PAD.right + 9} y={ly + 4}>{item.label}</text>}
        </g>;
      })}
      {focusYear !== null && <g className="m-line-focus"><line x1={x(focusYear)} x2={x(focusYear)} y1={PAD.top} y2={H - PAD.bottom} />{ordered.map(item => { const value = valueAt(item, focusYear); return value === null ? null : <circle key={item.id} className={lineClass(item)} cx={x(focusYear)} cy={y(value)} r={rank(item) ? 5 : 3.5} />; })}<text className="m-line-focus-year" x={Math.min(Math.max(x(focusYear), PAD.left + 20), W - PAD.right - 20)} y={PAD.top - 8} textAnchor="middle">{focusYear}</text></g>}
    </svg>
    <p className="m-line-readout" aria-live="polite"><span aria-hidden="true">{summary && <strong className="m-line-summary">{summary}</strong>}<small>{focusYear === null ? '図をなぞるか、図を選んで矢印キーを押すと、その年の値に切り替わります。' : '指を離すと最新の値に戻ります。'}</small></span><span className="sr-only">{readout}</span></p>
    <details className="m-line-legend">
      <summary>{shown.length}{highlightId ? 'か国・地域' : '系列'}すべての値を見る{labelIndexes.length < shown.length ? `（図に名前が出ていない${shown.length - labelIndexes.length}つもここに）` : ''}</summary>
      <p className="m-line-legend-head">{focusYear === null ? `最新の値（${lastYear}年まで）` : `${focusYear}年の値`}・大きい順。国名を押すと、その線を濃くして名前を出します。</p>
      <ol>
        {rows.map((row, i) => {
          const body = <>
            <span className="m-line-swatch" aria-hidden="true" />
            <span className="m-line-legend-name">{row.value === null ? '' : `${i + 1}. `}{row.item.label}</span>
            <span className="m-line-legend-value">{row.value === null ? '未取得' : format(row.value)}{focusYear === null && row.year !== undefined && row.year !== lastYear && <small>（{row.year}年）</small>}</span>
          </>;
          return <li key={row.item.id} className={lineClass(row.item)}>
            {row.item.id === highlightId ? <span className="m-line-legend-row">{body}</span> : <button type="button" className="m-line-legend-row" aria-pressed={picked === row.item.id} onClick={() => setPicked(picked === row.item.id ? null : row.item.id)}>{body}</button>}
          </li>;
        })}
      </ol>
    </details>
  </div>;
}
