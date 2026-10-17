import { useEffect, useRef, useState } from 'react';
import { useInView, usePrefersReducedMotion } from './useMotion';

/**
 * 一度だけ弾ける演出。国士（benefit）は金と緑の光の粒が飛び、国賊（loss）は黒い破片が下へ落ちる。
 * 飾りなので読み上げない。動きを減らす設定では出さない。繰り返さない。
 */
export function Burst({ tone, count = 14 }: { tone: 'loss' | 'benefit'; count?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, 0.4);
  const reduced = usePrefersReducedMotion();
  const [done, setDone] = useState(false);
  useEffect(() => { if (!inView) return; const timer = setTimeout(() => setDone(true), 1200); return () => clearTimeout(timer); }, [inView]);
  if (reduced || done) return <span ref={ref} className="m-burst" aria-hidden="true" />;
  return <span ref={ref} className={`m-burst m-burst-${tone} ${inView ? 'is-in' : ''}`} aria-hidden="true">
    {Array.from({ length: count }, (_, i) => {
      const angle = tone === 'benefit' ? (i / count) * Math.PI * 2 : Math.PI * (0.15 + 0.7 * (i / count));
      const distance = 26 + (i * 37 % 23);
      return <i key={i} style={{ '--dx': `${Math.cos(angle) * distance}px`, '--dy': `${(tone === 'benefit' ? -1 : 1) * Math.abs(Math.sin(angle)) * distance}px`, '--d': `${(i * 13) % 90}ms` } as React.CSSProperties} />;
    })}
  </span>;
}
