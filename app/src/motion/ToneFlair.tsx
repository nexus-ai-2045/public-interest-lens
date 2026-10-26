import { useEffect, useRef } from 'react';
import { playToneSound, setSoundOn, useSoundOn, type SoundTone } from './tone-sound';
import { usePrefersReducedMotion } from './useMotion';

/**
 * 1位の札に重ねる飾り。国賊は汚れた霧・したたる赤・飛び回るハエ・「ウヒヒヒ…」の吹き出し、
 * 国士は後光・翼・舞い落ちる羽・「ポロロン♪」の吹き出し。人の顔や属性は描かず、札（行動と結果の枠）だけを飾る。
 * 飾りなので読み上げない。動きを減らす設定では止める（CSS）。
 */
export function ToneFlair({ side }: { side: 'loss' | 'benefit' }) {
  return <span className={`tone-flair tone-flair-${side}`} aria-hidden="true">
    {side === 'loss' ? <>
      <span className="tf-fog" />
      <span className="tf-drips">{[8, 23, 41, 63, 82].map((x, i) => <i key={x} style={{ '--x': `${x}%`, '--d': `${i * 170}ms`, '--h': `${14 + (i * 7) % 18}px` } as React.CSSProperties} />)}</span>
      <span className="tf-flies">{[0, 1, 2].map(i => <i key={i} style={{ '--i': i } as React.CSSProperties} />)}</span>
      <span className="tf-bubble">{[...'ウヒヒヒヒ…'].map((c, i) => <b key={i} style={{ '--i': i } as React.CSSProperties}>{c}</b>)}</span>
    </> : <>
      <span className="tf-rays" />
      <svg className="tf-wing tf-wing-l" viewBox="0 0 80 50"><path d="M78 40C60 42 30 36 4 8c14-2 28 0 38 6C34 8 24 2 14 0c20-2 36 6 46 16-6-4-12-7-18-8 14 4 26 14 36 30z" /></svg>
      <svg className="tf-wing tf-wing-r" viewBox="0 0 80 50"><path d="M78 40C60 42 30 36 4 8c14-2 28 0 38 6C34 8 24 2 14 0c20-2 36 6 46 16-6-4-12-7-18-8 14 4 26 14 36 30z" /></svg>
      <span className="tf-halo" />
      <span className="tf-feathers">{Array.from({ length: 9 }, (_, i) => <i key={i} style={{ '--x': `${6 + i * 11}%`, '--d': `${(i * 410) % 3200}ms`, '--t': `${4800 + (i * 370) % 1800}ms`, '--dx': `${(i % 2 ? 1 : -1) * (14 + (i * 5) % 20)}px` } as React.CSSProperties} />)}</span>
      <span className="tf-bubble">♪ ポロロン〜</span>
    </>}
  </span>;
}

/** 音を出す／出さないの切り替え。既定は消音。押した瞬間に今の向きの音を一度鳴らして確かめる。 */
export function SoundToggle({ tone }: { tone: SoundTone }) {
  const on = useSoundOn();
  return <button type="button" className={`sound-toggle ${on ? 'is-on' : ''}`} aria-pressed={on} title={on ? '音を消す' : '音を出す（国賊は笑い声、国士は鐘と合唱）'}
    onClick={() => { const next = !on; setSoundOn(next); if (next) playToneSound(tone); }}>
    <span aria-hidden="true">{on ? '🔊' : '🔇'}</span>音{on ? 'あり' : 'なし'}
  </button>;
}

/** 向きを切り替えたとき、音がオンなら鳴らす。動きを減らす設定の人には自動では鳴らさない。 */
export function useToneSound(tone: SoundTone): void {
  const on = useSoundOn();
  const reduced = usePrefersReducedMotion();
  const previous = useRef(tone);
  useEffect(() => {
    if (previous.current === tone) return;
    previous.current = tone;
    if (on && !reduced) playToneSound(tone);
  }, [tone, on, reduced]);
}
