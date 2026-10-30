import { describe, expect, it } from 'vitest';
import { characterStances, isClearlyBad, type StanceRow } from './StanceList';
import type { VoteLaw } from './votes';
import type { CatalogItem } from './laws-catalog';

const law = (id: string, yes: string[], no: string[]): VoteLaw => ({ id, title: id, kind: '閣法', session: 1, proposer: '内閣', promulgated: '2026-01-01', url: 'https://example.jp', shu: { date: null, yes, no }, san: null });

describe('characterStances', () => {
  it('性格ごとに賛成・反対の本数を数える（割れは両方）', () => {
    const rows: StanceRow[] = [
      { law: law('a', ['自由民主党'], ['日本共産党']), character: 'regulate', title: 'a' },
      { law: law('b', ['自由民主党', '日本共産党'], []), character: 'regulate', title: 'b' },
    ];
    const reg = characterStances(rows, '共産').find(r => r.character === 'regulate')!;
    expect(reg).toMatchObject({ yes: 1, no: 1 });
  });
});

describe('isClearlyBad', () => {
  const base = { id: 'x', kind: '閣法', title: 'x', year: 2000, field: 'f', marks: [], summary: '' } as unknown as CatalogItem;
  it('確かな額で損失側のときだけ', () => {
    expect(isClearlyBad({ ...base, side: 'loss', step: 'published', amount: { median: 1, low: 0, high: 2 } })).toBe(true);
    expect(isClearlyBad({ ...base, side: 'loss', step: 'amounted', amount: { median: 1, low: 0, high: 2 } })).toBe(false);
    expect(isClearlyBad(undefined)).toBe(false);
  });
});
