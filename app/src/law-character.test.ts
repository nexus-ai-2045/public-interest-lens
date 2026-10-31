import { describe, expect, it } from 'vitest';
import { characterOf, matchesCharacter } from './law-character';

describe('characterOf', () => {
  it('規制のことばがあれば、支援のことばが同居しても規制を優先する', () => {
    expect(characterOf('特定商取引に関する法律の一部を改正する法律案（罰則の強化と被害者の支援）')).toBe('regulate');
  });
  it('特例・補助は既得権益・業界を守る側に分ける', () => {
    expect(characterOf('農業協同組合法の特例に関する法律案')).toBe('protect');
  });
  it('整備・推進は新しく整える側', () => {
    expect(characterOf('デジタル社会形成基本法案')).toBe('improve');
  });
  it('どれにも当たらなければ分類なし', () => {
    expect(characterOf('国会議員の歳費に関する法律案')).toBe('other');
  });
  it('選択が空なら全部通す', () => {
    expect(matchesCharacter('何でも', new Set())).toBe(true);
    expect(matchesCharacter('取締りの強化', new Set(['protect']))).toBe(false);
  });
});
