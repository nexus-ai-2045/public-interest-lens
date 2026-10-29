// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { directionLabel, formatGap, formatGapRange, parseProvisional } from './provisional';

describe('暫定評価の配布データ', () => {
  const data = parseProvisional(readFileSync(new URL('../public/distribution/provisional.json', import.meta.url), 'utf8'));
  it('政策カードは幅だけを持ち、点の値を持たない', () => {
    for (const card of data.cards) if (card.effect) { expect(card.effect.low).toBeLessThanOrEqual(card.effect.high); expect('median' in card.effect).toBe(false); }
  });
  it('件数が合う', () => expect(data.counts.provisional + data.counts.unmeasured).toBe(data.counts.recent));
  it('形が違うデータは読まない', () => expect(() => parseProvisional('{"schema":"x"}')).toThrow());
});
describe('表示の整形', () => {
  it('負の効果を符号つきで読む', () => { expect(formatGap(-0.123)).toBe('−12.3%'); expect(formatGapRange({ low: -0.1, high: 0.05 })).toBe('−10%〜+5%'); });
  it('0をまたぐ幅は向き不定', () => expect(directionLabel('unclear')).toContain('定まらない'));
});
