import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { gsap } from 'gsap';

/** 選択変更を短く示し、非表示や継続アニメーションを残さない。 */
export function EvidenceMotion({ stateKey, selectionKey = stateKey, navigationKey = '', children }: { stateKey: string; selectionKey?: string; navigationKey?: string; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const previous = useRef({ stateKey, selectionKey, navigationKey });
  useLayoutEffect(() => {
    if (previous.current.stateKey === stateKey) return;
    const navigationOnly = previous.current.selectionKey === selectionKey && previous.current.navigationKey !== navigationKey;
    previous.current = { stateKey, selectionKey, navigationKey };
    const duration = navigationOnly ? 0.15 : 0.18;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (!root.current || preference.matches) return;
    const context = gsap.context(() => {
      gsap.fromTo(root.current, { opacity: 0.88, y: 3 }, { opacity: 1, y: 0, duration, ease: 'power1.out', overwrite: true, clearProps: 'opacity,transform' });
    }, root);
    const stopForReducedMotion = () => {
      if (preference.matches) context.revert();
    };
    preference.addEventListener('change', stopForReducedMotion);
    return () => {
      preference.removeEventListener('change', stopForReducedMotion);
      context.revert();
    };
  }, [stateKey, selectionKey, navigationKey]);
  return <div ref={root}>{children}</div>;
}
