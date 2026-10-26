import { useSyncExternalStore } from 'react';

/**
 * 国賊／国士の効果音。素材ファイルは使わず、ブラウザの Web Audio で自作する（権利の問題なし）。
 * 既定は消音。利用者が「音」を押したときだけ AudioContext を作り、自動再生はしない。
 */
export type SoundTone = 'harm' | 'benefit';

/** 「ウ・ヒ・ヒ・ヒ・ヒ」。長さ（秒）、声の高さ（Hz）、母音（u は暗く、i は鋭く）。 */
export type Syllable = { at: number; len: number; hz: number; vowel: 'u' | 'i' };

export function laughPlan(): Syllable[] {
  const plan: Syllable[] = [{ at: 0, len: 0.32, hz: 150, vowel: 'u' }];
  for (let i = 0; i < 5; i++) plan.push({ at: 0.34 + i * 0.15, len: 0.11, hz: 235 - i * 14, vowel: 'i' });
  return plan;
}

/** 天使：高い鐘の分散和音（C6 E6 G6 C7 G6 E6 C7）。 */
export const CHIME_HZ = [1046.5, 1318.5, 1568, 2093, 1568, 1318.5, 2093] as const;

const FORMANT = { u: [300, 870, 2240], i: [280, 2250, 2890] } as const;

let enabled = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach(fn => fn());

export const isSoundOn = () => enabled;
export function setSoundOn(on: boolean): void { enabled = on; emit(); }
export function useSoundOn(): boolean {
  return useSyncExternalStore(fn => { listeners.add(fn); return () => { listeners.delete(fn); }; }, isSoundOn, () => false);
}

let ctx: AudioContext | null = null;
function audio(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  ctx ??= new Ctor();
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

function noise(ac: AudioContext, seconds: number): AudioBufferSourceNode {
  const buffer = ac.createBuffer(1, Math.ceil(ac.sampleRate * seconds), ac.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  const src = ac.createBufferSource();
  src.buffer = buffer;
  return src;
}

function drive(ac: AudioContext, amount: number): WaveShaperNode {
  const shaper = ac.createWaveShaper();
  const curve = new Float32Array(256);
  for (let i = 0; i < 256; i++) { const x = (i / 255) * 2 - 1; curve[i] = Math.tanh(x * amount); }
  shaper.curve = curve;
  return shaper;
}

/** 国賊：低いうなりの上で、しゃがれた「ウヒヒヒヒ」。ざらつき（歪み）と息の雑音で小汚く。 */
function playLaugh(ac: AudioContext, out: AudioNode, t0: number): number {
  const plan = laughPlan();
  const total = plan[plan.length - 1].at + plan[plan.length - 1].len + 0.25;
  // 低いうなり
  const drone = ac.createOscillator(); drone.type = 'sawtooth'; drone.frequency.setValueAtTime(58, t0); drone.frequency.linearRampToValueAtTime(48, t0 + total);
  const droneLp = ac.createBiquadFilter(); droneLp.type = 'lowpass'; droneLp.frequency.value = 220;
  const droneGain = ac.createGain(); droneGain.gain.setValueAtTime(0, t0); droneGain.gain.linearRampToValueAtTime(0.5, t0 + 0.2); droneGain.gain.linearRampToValueAtTime(0, t0 + total);
  drone.connect(droneLp).connect(droneGain).connect(out); drone.start(t0); drone.stop(t0 + total);
  // 声：のこぎり波を2本ずらして重ね、母音の山（フォルマント）を通す
  const voices = [0, 17].map(cents => { const o = ac.createOscillator(); o.type = 'sawtooth'; o.detune.value = cents; return o; });
  const vibrato = ac.createOscillator(); vibrato.frequency.value = 31; // ひきつった震え
  const vibratoDepth = ac.createGain(); vibratoDepth.gain.value = 9; vibrato.connect(vibratoDepth);
  const bands = [0, 1, 2].map(() => { const f = ac.createBiquadFilter(); f.type = 'bandpass'; f.Q.value = 7; return f; });
  const bandGain = [1, 0.8, 0.35];
  const voiceGain = ac.createGain(); voiceGain.gain.setValueAtTime(0, t0);
  const grit = drive(ac, 3.2);
  voices.forEach(o => { vibratoDepth.connect(o.frequency); o.connect(grit); });
  grit.connect(voiceGain);
  bands.forEach((f, k) => { const g = ac.createGain(); g.gain.value = bandGain[k]; voiceGain.connect(f); f.connect(g).connect(out); });
  plan.forEach(s => {
    const t = t0 + s.at;
    voices.forEach((o, n) => { o.frequency.setValueAtTime(s.hz * (n ? 1.01 : 1) * 0.92, t); o.frequency.linearRampToValueAtTime(s.hz * (n ? 1.01 : 1), t + s.len * 0.45); });
    bands.forEach((f, k) => f.frequency.setTargetAtTime(FORMANT[s.vowel][k], t, 0.02));
    voiceGain.gain.setValueAtTime(0.0001, t);
    voiceGain.gain.linearRampToValueAtTime(s.vowel === 'u' ? 0.5 : 0.65, t + 0.025);
    voiceGain.gain.exponentialRampToValueAtTime(0.0001, t + s.len);
    if (s.vowel === 'i') { // 「ヒ」の息
      const breath = noise(ac, 0.08); const hp = ac.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 3200;
      const bg = ac.createGain(); bg.gain.setValueAtTime(0.28, t - 0.01); bg.gain.exponentialRampToValueAtTime(0.0001, t + 0.07);
      breath.connect(hp).connect(bg).connect(out); breath.start(t - 0.01); breath.stop(t + 0.08);
    }
  });
  [...voices, vibrato].forEach(o => { o.start(t0); o.stop(t0 + total); });
  return total;
}

/** 国士：やわらかい合唱風の和音と、きらきらした鐘。 */
function playAngel(ac: AudioContext, out: AudioNode, t0: number): number {
  const total = 2.6;
  // 合唱風の和音（C5 E5 G5 を「アー」の山に通す）
  const pad = ac.createGain(); pad.gain.setValueAtTime(0, t0); pad.gain.linearRampToValueAtTime(0.32, t0 + 0.5); pad.gain.linearRampToValueAtTime(0, t0 + total);
  const ah = [800, 1150, 2900].map(hz => { const f = ac.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = hz; f.Q.value = 5; return f; });
  [523.25, 659.25, 783.99].forEach(hz => [-6, 6].forEach(cents => {
    const o = ac.createOscillator(); o.type = 'sawtooth'; o.frequency.value = hz; o.detune.value = cents;
    const g = ac.createGain(); g.gain.value = 0.12; o.connect(g).connect(pad); o.start(t0); o.stop(t0 + total);
  }));
  ah.forEach(f => { pad.connect(f); f.connect(out); });
  // 鐘（基音と非整数倍音の組み合わせ）
  CHIME_HZ.forEach((hz, i) => {
    const t = t0 + 0.15 + i * 0.16;
    [[1, 0.5, 1.4], [2.76, 0.18, 0.6]].forEach(([ratio, level, decay]) => {
      const o = ac.createOscillator(); o.type = 'sine'; o.frequency.value = hz * ratio;
      const g = ac.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(level * 0.55, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + decay);
      o.connect(g).connect(out); o.start(t); o.stop(t + decay + 0.05);
    });
  });
  return total;
}

/** 鳴らす。消音のとき・音声が使えない端末では何もしない。 */
export function playToneSound(tone: SoundTone): void {
  if (!enabled) return;
  const ac = audio();
  if (!ac) return;
  const master = ac.createGain(); master.gain.value = 0.22;
  const limiter = ac.createDynamicsCompressor();
  master.connect(limiter).connect(ac.destination);
  const t0 = ac.currentTime + 0.03;
  tone === 'harm' ? playLaugh(ac, master, t0) : playAngel(ac, master, t0);
}
