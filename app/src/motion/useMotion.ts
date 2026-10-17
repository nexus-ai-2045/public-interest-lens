import { useEffect, useState, type RefObject } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

/** 利用者が「視差効果を減らす」を選んでいるか。途中で切り替えても追従する。 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(QUERY).matches);
  useEffect(() => {
    const media = window.matchMedia?.(QUERY);
    if (!media) return;
    const change = () => setReduced(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  return reduced;
}

/** 画面に入ったら true。一度入ったら戻さない（読み終えた図が再び動かないように）。 */
export function useInView(ref: RefObject<Element | null>, threshold = 0.2): boolean {
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    if (seen || !ref.current || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { setSeen(true); observer.disconnect(); } }, { threshold });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [ref, seen, threshold]);
  return seen;
}

/** 動きの長さ（ms）。読ませる図は短く、遅くても 900ms で止める。 */
export const MOTION = { quick: 150, base: 450, draw: 700, count: 650, stagger: 35, maxStagger: 350 } as const;

export const easeOutExpo = (t: number) => t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);
