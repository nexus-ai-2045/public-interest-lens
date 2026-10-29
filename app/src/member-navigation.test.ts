import { expect, it } from 'vitest';
import { memberLocation } from './member-navigation';

it('全議員からも同じ算定条件で選んだ人物の欄を開く', () => {
  const url = new URL(memberLocation('person/a', '?r=40&p=60&house=voters&chair=1&office=1&tone=kokushi&tab=party&name=old', true), 'https://example.test');
  expect(url.pathname).toBe('/members');
  expect(url.hash).toBe('#member-person%2Fa');
  expect(Object.fromEntries(url.searchParams)).toEqual({ name: 'person/a', p: '60', house: 'voters', chair: '1', r: '40', office: '1', tone: 'kokushi' });
});

it('不正な算定条件を既存の読取り規則で正規化する', () => {
  const url = new URL(memberLocation('person-a', '?r=invalid&p=300&tone=invalid&redirect=https://example.test'), 'https://example.test');
  expect(Object.fromEntries(url.searchParams)).toEqual({ name: 'person-a' });
});
