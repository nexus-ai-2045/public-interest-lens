import { useEffect, useRef } from 'react';
import type { Direction } from './data/fiction';

const LOOK: Record<Direction, { fade: string; stroke: string; alpha: number }> = {
  // 国賊：くすんだ赤の雨が下へ落ちる
  harm: { fade: 'rgba(8,8,10,0.09)', stroke: '#a3343b', alpha: 0.5 },
  // 国士：明るい背景に金と空色の光が昇る
  benefit: { fade: 'rgba(251,247,238,0.12)', stroke: '#f0a500', alpha: 0.6 },
};

/** ヒーロー背景の2D流線。prefers-reduced-motion では数フレームだけ描いて止めます。 */
export function FlowField({ mode }: { mode: Direction }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

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
    type P = { x: number; y: number; life: number; tw: number };
    let ps: P[] = [];

    const spawn = (p: P) => {
      p.x = Math.random() * w;
      p.y = Math.random() * h;
      p.life = 120 + Math.random() * 200;
      p.tw = Math.random() * Math.PI * 2;
    };
    const resize = () => {
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.round(Math.min(900, (w * h) / 1400));
      ps = Array.from({ length: n }, () => { const p = { x: 0, y: 0, life: 0, tw: 0 }; spawn(p); return p; });
    };

    const step = (t: number) => {
      const m = modeRef.current;
      const look = LOOK[m];
      ctx.fillStyle = look.fade;
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = look.stroke;
      ctx.lineWidth = m === 'benefit' ? 1.4 : 1;
      ctx.globalAlpha = look.alpha;
      ctx.beginPath();
      for (const p of ps) {
        let dx: number;
        let dy: number;
        if (m === 'harm') {
          // 重く垂れ下がる線
          const a = Math.PI / 2 + Math.sin(p.x * 0.004 + t * 0.0003) * 0.35 + (pointer.x - 0.5) * 0.3;
          dx = Math.cos(a) * 1.1;
          dy = Math.sin(a) * 1.9;
        } else {
          // 軽く舞い上がる線
          const a = -Math.PI / 2 + Math.sin(p.y * 0.006 + t * 0.0006 + p.tw) * 0.9 + (pointer.x - 0.5) * 0.6;
          dx = Math.cos(a) * 1.6;
          dy = Math.sin(a) * 1.6;
        }
        ctx.moveTo(p.x, p.y);
        p.x += dx;
        p.y += dy;
        ctx.lineTo(p.x, p.y);
        p.life -= 1;
        if (p.life < 0 || p.x < 0 || p.x > w || p.y < 0 || p.y > h) spawn(p);
      }
      ctx.stroke();
      if (m === 'benefit') {
        ctx.globalAlpha = 1;
        for (let i = 0; i < ps.length; i += 23) {
          const p = ps[i];
          const s = (Math.sin(t * 0.004 + p.tw) + 1) * 1.6;
          ctx.fillStyle = i % 2 ? '#ffd166' : '#5cc8ff';
          ctx.fillRect(p.x - s / 2, p.y - s / 2, s, s);
        }
      }
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
