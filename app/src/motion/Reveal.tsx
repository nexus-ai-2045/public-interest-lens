import { useRef, type ReactNode } from 'react';
import { useInView } from './useMotion';

/** 画面に入ったら、短く浮かび上がる（国士）／沈み込む（国賊）。減らす設定では CSS 側で動かさない。 */
export function Reveal({ children, tone = 'neutral', delay = 0, as: Tag = 'div', className = '' }: { children: ReactNode; tone?: 'loss' | 'benefit' | 'neutral'; delay?: number; as?: 'div' | 'section' | 'article' | 'li'; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, 0.12);
  return <Tag ref={ref as never} className={`m-reveal m-reveal-${tone} ${inView ? 'is-in' : ''} ${className}`.trim()} style={{ '--m-delay': `${delay}ms` } as React.CSSProperties}>{children}</Tag>;
}
