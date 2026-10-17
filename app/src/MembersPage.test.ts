import { expect, it } from 'vitest';
import { signedYen, topBars } from './MembersPage';
import type { PublicMember } from './members-build';

const member = (name: string, rank: number, low: number, median: number, high: number) => ({ name, rank, net: { low, median, high }, laws: [{}] }) as unknown as PublicMember;

it('上位の横棒は側ごとに大きい順で、幅が0をまたぐときは0から出す', () => {
  const members = [member('甲', 1, -300, -200, -100), member('乙', 2, -50, -10, 20), member('丙', 3, 5, 30, 60), member('丁', 4, 10, 90, 120)];
  expect(topBars(members, 'loss').map(b => [b.label, b.value, b.low, b.high])).toEqual([['甲', 200, 100, 300], ['乙', 10, 0, 50]]);
  expect(topBars(members, 'benefit').map(b => b.label)).toEqual(['丁', '丙']);
  expect(topBars(members, 'benefit')[0].href).toBe(`/members?name=${encodeURIComponent('丁')}`);
});

it('符号つきの額', () => {
  expect(signedYen(-2e11)).toBe('−2,000億円');
  expect(signedYen(0)).toBe('0円');
});
