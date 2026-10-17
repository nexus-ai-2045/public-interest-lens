import { useEffect, useRef, useState } from 'react';
import { MOTION, easeOutExpo, useInView, usePrefersReducedMotion } from './useMotion';

/** 数字を 0 から一気に数え上げ、止まった瞬間に弾む。読み上げは最終値だけにして、途中の数字を読ませない。 */
export function CountUp({ value, format, duration = MOTION.count, className }: { value: number; format: (value: number) => string; duration?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref);
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState(reduced ? value : 0);
  useEffect(() => {
    if (reduced) { setShown(value); return; }
    if (!inView) return;
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setShown(value * easeOutExpo(t));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, inView, reduced, duration]);
  const final = format(value);
  const landed = !reduced && inView && shown === value;
  return <span ref={ref} className={`${className ?? ''} m-count ${landed ? 'is-landed' : ''}`.trim()} aria-label={final}><span aria-hidden="true">{shown === value ? final : format(shown)}</span></span>;
}
