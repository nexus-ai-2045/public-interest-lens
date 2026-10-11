import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';

export interface ConfettiHandle {
  burst: (x: number, y: number, count?: number) => void;
}

const COLORS = ['#ffc247', '#ff8a3d', '#3ec9ff', '#7cf29a', '#ff6fb5', '#ffffff'];

type Piece = { x: number; y: number; vx: number; vy: number; r: number; spin: number; w: number; h: number; c: string; life: number };

/** 国士側の称賛演出。画面全体に重ねる紙吹雪で、操作は奪いません。 */
export const Confetti = forwardRef<ConfettiHandle, { disabled: boolean }>(function Confetti({ disabled }, ref) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pieces = useRef<Piece[]>([]);
  const raf = useRef(0);

  const loop = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const dpr = canvas.width / window.innerWidth;
    pieces.current = pieces.current.filter((p) => p.life > 0 && p.y < window.innerHeight + 40);
    for (const p of pieces.current) {
      p.vy += 0.32;
      p.vx *= 0.985;
      p.x += p.vx;
      p.y += p.vy;
      p.r += p.spin;
      p.life -= 1;
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.r);
      ctx.scale(1, Math.cos(p.r * 2));
      ctx.globalAlpha = Math.min(1, p.life / 30);
      ctx.fillStyle = p.c;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    }
    if (pieces.current.length) raf.current = requestAnimationFrame(loop);
    else raf.current = 0;
  };

  useImperativeHandle(ref, () => ({
    burst(x, y, count = 140) {
      if (disabled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      for (let i = 0; i < count; i++) {
        const a = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 0.9;
        const v = 8 + Math.random() * 11;
        pieces.current.push({
          x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, r: Math.random() * 6, spin: (Math.random() - 0.5) * 0.35,
          w: 6 + Math.random() * 6, h: 9 + Math.random() * 8, c: COLORS[i % COLORS.length], life: 120 + Math.random() * 60,
        });
      }
      if (!raf.current) raf.current = requestAnimationFrame(loop);
    },
  }), [disabled]);

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  return <canvas ref={canvasRef} className="confetti" aria-hidden="true" />;
});
