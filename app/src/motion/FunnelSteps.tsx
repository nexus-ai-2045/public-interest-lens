import { useRef } from 'react';
import { MOTION, useInView, usePrefersReducedMotion } from './useMotion';
import { CountUp } from './CountUp';

/**
 * 件数の絞り込み。桁が大きく違う（3,415→1）ので、棒は対数の長さにして小さい段も見えるようにする。
 * 実数は必ず数字で出す。上から順に短く伸びる。
 */
export function FunnelSteps({ steps, unit = '本', caption }: { steps: { key: string; label: string; count: number; note?: string }[]; unit?: string; caption: string }) {
  const root = useRef<HTMLOListElement>(null);
  const inView = useInView(root, 0.2);
  const reduced = usePrefersReducedMotion();
  const top = Math.max(1, ...steps.map(step => step.count));
  const width = (count: number) => count <= 0 ? 0 : Math.max(2, Math.log10(count + 1) / Math.log10(top + 1) * 100);
  const format = (value: number) => `${Math.round(value).toLocaleString('ja-JP')}${unit}`;
  return <ol ref={root} className={`m-funnel ${inView || reduced ? 'is-in' : ''}`} aria-label={caption}>
    {steps.map((step, index) => <li key={step.key} className="m-funnel-step">
      <span className="m-funnel-label">{step.label}{step.note && <small>{step.note}</small>}</span>
      <span className="m-funnel-track" aria-hidden="true"><span className="m-funnel-fill" style={{ width: `${width(step.count)}%`, transitionDelay: `${Math.min(index * 70, MOTION.maxStagger * 2)}ms` }} /></span>
      <CountUp className="m-funnel-count" value={step.count} format={format} />
    </li>)}
  </ol>;
}
