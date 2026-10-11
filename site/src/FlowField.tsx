import { useEffect, useRef } from 'react';

/** ヒーロー背景の2D流線。prefers-reduced-motion では1枚だけ描いて止めます。 */
export function FlowField({ accent }: { accent: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const accentRef = useRef(accent);
  accentRef.current = accent;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let w = 0;
    let h = 0;
    let raf = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pointer = { x: 0.5, y: 0.5 };
    type P = { x: number; y: number; life: number };
    let ps: P[] = [];

    const resize = () => {
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.round(Math.min(900, (w * h) / 1400));
      ps = Array.from({ length: n }, () => ({ x: Math.random() * w, y: Math.random() * h, life: Math.random() * 200 }));
      ctx.fillStyle = '#07070b';
      ctx.fillRect(0, 0, w, h);
    };
    const angle = (x: number, y: number, t: number) =>
      Math.sin(x * 0.0032 + t * 0.00025) * 1.6 + Math.cos(y * 0.0041 - t * 0.0002) * 1.6 + (pointer.x - 0.5) * 1.2;

    const step = (t: number) => {
      ctx.fillStyle = 'rgba(7,7,11,0.085)';
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = accentRef.current;
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      for (const p of ps) {
        const a = angle(p.x, p.y, t);
        const nx = p.x + Math.cos(a) * 1.4;
        const ny = p.y + Math.sin(a) * 1.4 - (pointer.y - 0.5) * 0.6;
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(nx, ny);
        p.x = nx;
        p.y = ny;
        p.life -= 1;
        if (p.life < 0 || p.x < 0 || p.x > w || p.y < 0 || p.y > h) {
          p.x = Math.random() * w;
          p.y = Math.random() * h;
          p.life = 120 + Math.random() * 200;
        }
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
      if (!reduce) raf = requestAnimationFrame(step);
    };
    const onMove = (e: PointerEvent) => {
      pointer.x = e.clientX / window.innerWidth;
      pointer.y = e.clientY / window.innerHeight;
    };

    resize();
    if (reduce) for (let i = 0; i < 120; i++) step(i * 16);
    else raf = requestAnimationFrame(step);
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', onMove);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onMove);
    };
  }, []);

  return <canvas ref={ref} className="flow-field" aria-hidden="true" />;
}
