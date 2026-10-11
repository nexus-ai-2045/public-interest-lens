import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import gsap from 'gsap';
import { AS_OF, type Direction } from './data/fiction';
import { Confetti, type ConfettiHandle } from './Confetti';
import { FlowField } from './FlowField';
import { GdpChart } from './GdpChart';
import { Ranking } from './Ranking';


function useReducedMotion() {
  const [reduce, setReduce] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setReduce(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduce;
}

export function App() {
  const [direction, setDirection] = useState<Direction>('harm');
  const reduce = useReducedMotion();
  const heroRef = useRef<HTMLElement>(null);
  const confetti = useRef<ConfettiHandle>(null);
  const title = direction === 'harm' ? '国賊' : '国士';

  useEffect(() => {
    document.documentElement.dataset.mood = direction;
    document.title = `${title}ランキング｜架空データ版デモ`;
  }, [direction, title]);

  const choose = (d: Direction, e?: React.MouseEvent) => {
    if (d === direction) return;
    setDirection(d);
    if (d === 'benefit') {
      const x = e ? e.clientX : window.innerWidth / 2;
      const y = e ? e.clientY : window.innerHeight / 2;
      requestAnimationFrame(() => confetti.current?.burst(x, y, 180));
    }
  };

  useLayoutEffect(() => {
    if (reduce || !heroRef.current) return;
    const ctx = gsap.context(() => {
      if (direction === 'harm') {
        // 国賊：一度立ち上がった文字が、力なくうなだれる
        const tl = gsap.timeline();
        tl.from('.hero-char', { yPercent: 150, opacity: 0, duration: 0.9, ease: 'expo.out', stagger: 0.05 });
        tl.to('.hero-char', {
          y: (i: number) => 6 + (i % 3) * 7,
          rotate: (i: number) => (i % 2 ? 7 : -5),
          duration: 1.4, ease: 'bounce.out', stagger: 0.07,
        }, '+=0.15');
        tl.to('.hero-char', { y: '+=3', duration: 2.4, ease: 'sine.inOut', yoyo: true, repeat: -1, stagger: 0.2 });
      } else {
        // 国士：弾んで登場し、軽く浮き続ける
        const tl = gsap.timeline();
        tl.from('.hero-char', { yPercent: 120, scale: 0.4, opacity: 0, duration: 1.2, ease: 'elastic.out(1, 0.45)', stagger: 0.06 });
        tl.to('.hero-char', { y: -6, duration: 1.6, ease: 'sine.inOut', yoyo: true, repeat: -1, stagger: { each: 0.12, from: 'center' } });
      }
      gsap.from('.hero-sub, .hero-cta, .direction', { y: 24, opacity: 0, duration: 0.9, ease: 'expo.out', stagger: 0.08, delay: 0.35 });
    }, heroRef);
    return () => ctx.revert();
  }, [direction, reduce]);

  useEffect(() => {
    if (reduce) return;
    const els = document.querySelectorAll<HTMLElement>('.reveal');
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        gsap.fromTo(e.target, { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 1, ease: 'expo.out' });
        io.unobserve(e.target);
      }
    }, { threshold: 0.2 });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [reduce]);

  return (
    <>
      <div className="fiction-banner" role="note">
        <span className="dot" aria-hidden="true" />
        架空データ版デモ。ランキングの人物・政策・記録はすべて創作で、実在の議員とは関係ありません。
      </div>
      <header className="hero" ref={heroRef}>
        <FlowField mode={direction} />
        <div className="hero-inner">
          <h1 className="hero-title" aria-label={`${title}ランキング`}>
            {[...`${title}ランキング`].map((c, i) => (
              <span key={`${direction}-${i}`} className="hero-mask" aria-hidden="true"><span className="hero-char">{c}</span></span>
            ))}
          </h1>
          <p className="hero-sub">
            {direction === 'harm'
              ? <>日本の伸びを、誰が止めたか。<br />政策の結果と、そこへの公開された関与だけで並べる。</>
              : <>日本の伸びを、誰が押し上げたか。<br />よくやった人を、根拠つきで、ちゃんと褒める。</>}
          </p>
          <div className="direction" role="radiogroup" aria-label="評価の向き">
            <button role="radio" aria-checked={direction === 'harm'} className={direction === 'harm' ? 'on' : ''} onClick={(e) => choose('harm', e)}>国賊<small>悪影響</small></button>
            <button role="radio" aria-checked={direction === 'benefit'} className={direction === 'benefit' ? 'on' : ''} onClick={(e) => choose('benefit', e)}>国士<small>貢献</small></button>
            <span className="direction-thumb" aria-hidden="true" />
          </div>
          <a className="hero-cta" href="#ranking">ランキングを見る</a>
        </div>
      </header>
      <main>
        <Ranking direction={direction} reduce={reduce} onCelebrate={(x, y) => confetti.current?.burst(x, y, 90)} />
        <GdpChart reduce={reduce} />
        <section className="method reveal" aria-labelledby="method-title">
          <div className="section-head">
            <p className="eyebrow">評価のしかた</p>
            <h2 id="method-title">人ではなく、行動と結果を見る</h2>
          </div>
          <div className="method-grid">
            <article><span>01</span><h3>公開された行動だけ</h3><p>法案の提出、個人の採決、政策の決定。噂や人柄は点数に入れません。党籍から個人の賛否を推定もしません。</p></article>
            <article><span>02</span><h3>根拠と反証を並べる</h3><p>評価には出典、反証、別の説明を必ず付けます。根拠が足りない政策は保留にし、0点扱いもしません。</p></article>
            <article><span>03</span><h3>事実と計算と解釈を分ける</h3><p>確認済みの事実、機械計算、AIの解釈、未確認を区別して表示します。</p></article>
          </div>
        </section>
      </main>
      <Confetti ref={confetti} disabled={reduce} />
      <footer className="footer">
        <p>国賊ランキング（公益レンズ）架空データ版デモ・{AS_OF}</p>
        <p>実在の議員の評価は、評価方法・出典・反証・個人への帰属を人間がレビューしてから公開します。</p>
        <a href="https://github.com/nexus-ai-2045/public-interest-lens" target="_blank" rel="noreferrer">ソースコード</a>
      </footer>
    </>
  );
}
