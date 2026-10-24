import { useLayoutEffect, useRef } from 'react';
import { MOTION, useInView, usePrefersReducedMotion } from './useMotion';
import { Burst } from './Burst';
import { CountUp } from './CountUp';

export type RankBarItem = {
  id: string;
  label: string;
  /** 中央値など、棒の長さに使う値（正の数）。 */
  value: number;
  /** 幅（四分位など）。あれば棒の上に細い線で重ねる。 */
  low?: number;
  high?: number;
  side: 'loss' | 'benefit';
  /** 行の下に小さく出す補足（指標・確かさの印など）。 */
  note?: string;
  href?: string;
};

/** 色だけに頼らず、言葉でも損失・便益を示す印。 */
const SIDE_TAG = { loss: '国賊・損失', benefit: '国士・便益' } as const;

/**
 * 横棒のランキング。国賊（損失）は暗く沈み、国士（便益）は明るく浮く。
 * 幅は棒の上の細い線（FT・OWID の推計区間の見せ方）で必ず一緒に出し、一覧の上に棒と線の意味を一言で添える。
 * スマホでは名前と額を上の行に大きく、棒をその下に置く。
 * 並び替えたときは行が滑って移動する（FLIP）。動きを減らす設定では、すぐ最終状態を出す。
 */
export function RankBars({ items, format, caption, max: fixedMax }: { items: RankBarItem[]; format: (value: number) => string; caption: string; max?: number }) {
  const root = useRef<HTMLOListElement>(null);
  const inView = useInView(root, 0.15);
  const reduced = usePrefersReducedMotion();
  const positions = useRef(new Map<string, number>());
  const max = fixedMax ?? Math.max(1, ...items.map(item => item.high ?? item.value));
  const order = items.map(item => item.id).join('|');
  useLayoutEffect(() => {
    const rows = root.current ? [...root.current.querySelectorAll<HTMLLIElement>('[data-bar-id]')] : [];
    const next = new Map<string, number>();
    for (const row of rows) {
      const id = row.dataset.barId!;
      const top = row.getBoundingClientRect().top;
      next.set(id, top);
      const before = positions.current.get(id);
      if (!reduced && before !== undefined && before !== top && typeof row.animate === 'function') row.animate([{ transform: `translateY(${before - top}px)` }, { transform: 'translateY(0)' }], { duration: 350, easing: 'cubic-bezier(.4,0,.2,1)' });
    }
    positions.current = next;
  }, [order, reduced]);
  const percent = (value: number) => `${Math.max(0, Math.min(100, value / max * 100))}%`;
  const hasRange = items.some(item => item.low !== undefined && item.high !== undefined);
  return <div className="m-rank-wrap">
  <p className={`m-rank-legend ${items[0]?.side ?? ''}`} aria-hidden="true">
    <span className="m-rank-key"><span className="m-rank-key-bar" />太い棒＝中央値の額</span>
    {hasRange && <span className="m-rank-key"><span className="m-rank-key-range" />細い線＝幅（低い推計〜高い推計）</span>}
  </p>
  <ol ref={root} className={`m-rank-bars ${inView || reduced ? 'is-in' : ''}`} aria-label={caption}>
    {items.map((item, index) => {
      const range = item.low !== undefined && item.high !== undefined ? `幅 ${format(item.low)}〜${format(item.high)}` : '';
      const body = <>
        <span className={`m-rank-no ${index < 3 ? `top top-${index + 1}` : ''}`} aria-hidden="true" style={{ animationDelay: `${Math.min(index * MOTION.stagger, MOTION.maxStagger) + MOTION.base}ms` }}>{index + 1}{index === 0 && <Burst tone={item.side} />}</span>
        <span className="m-rank-text"><span className="m-rank-label">{item.label}</span>{item.note && <small>{item.note}</small>}</span>
        <span className="m-rank-track" aria-hidden="true">
          <span className="m-rank-fill" style={{ width: percent(item.value), animationDelay: `${Math.min(index * MOTION.stagger, MOTION.maxStagger) + MOTION.base}ms`, transitionDelay: `${Math.min(index * MOTION.stagger, MOTION.maxStagger)}ms` }} />
          {range && <span className="m-rank-range" style={{ left: percent(item.low!), width: `calc(${percent(item.high!)} - ${percent(item.low!)})`, transitionDelay: `${Math.min(index * MOTION.stagger, MOTION.maxStagger) + MOTION.base}ms` }} />}
        </span>
        <span className="m-rank-value" aria-hidden="true"><span className="m-rank-tag">{SIDE_TAG[item.side]}</span><strong><CountUp value={item.value} format={format} /></strong>{range && <small>{range}</small>}</span>
      </>;
      return <li key={item.id} data-bar-id={item.id} className={`m-rank-row ${item.side}`} aria-label={`${index + 1}位 ${item.label}、${item.side === 'loss' ? '損失' : '便益'} ${format(item.value)}${range ? `、${range}` : ''}`}>{item.href ? <a href={item.href}>{body}</a> : body}</li>;
    })}
  </ol>
  </div>;
}
