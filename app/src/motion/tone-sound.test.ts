import { describe, expect, it } from 'vitest';
import { CHIME_HZ, isSoundOn, laughPlan, playToneSound, setSoundOn } from './tone-sound';

describe('効果音', () => {
  it('既定は消音で、オンにしない限り鳴らさない（音声を作らない）', () => {
    expect(isSoundOn()).toBe(false);
    expect(() => playToneSound('harm')).not.toThrow();
    expect(() => playToneSound('benefit')).not.toThrow();
  });
  it('オンにしても音声が使えない環境では何もしない', () => {
    setSoundOn(true);
    expect(() => playToneSound('harm')).not.toThrow();
    setSoundOn(false);
  });
  it('笑い声は「ウ」のあとに「ヒ」が5回、時間順に並び、声は少しずつ低くなる', () => {
    const plan = laughPlan();
    expect(plan.map(s => s.vowel).join('')).toBe('uiiiii');
    plan.slice(1).forEach((s, i, all) => { if (i) { expect(s.at).toBeGreaterThan(all[i - 1].at); expect(s.hz).toBeLessThan(all[i - 1].hz); } });
  });
  it('鐘の音は高い和音（C6 以上）', () => {
    expect(Math.min(...CHIME_HZ)).toBeGreaterThan(1000);
  });
});
