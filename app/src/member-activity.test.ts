import { expect, it } from 'vitest';
import { readActivity } from './member-activity';

const base = { schema: 'member-activity/v1', fetchedAt: '2026-10-17', method: { diet: '', roles: '' } };

it('会議録と公式ページの URL だけを受け付ける', () => {
  const ok = { ...base, members: { 甲: { diet: { speeches: 1, shugiin: 1, sangiin: 0, asMinister: 0, asChair: 0, meetings: 1, first: '2020-01-01', recent: [{ date: '2020-01-01', house: '衆議院', meeting: '本会議', issue: '第1号', position: '', group: '', url: 'https://kokkai.ndl.go.jp/txt/1/1' }] }, roles: [{ category: '役職_内閣', title: '大臣', period: '', url: 'https://www.kantei.go.jp/jp/a.html', source: '公的機関' }] } } };
  expect(readActivity(JSON.stringify(ok)).members['甲'].diet?.speeches).toBe(1);
  const news = { ...base, members: { 甲: { roles: [{ category: '選挙', title: 'x', period: '', url: 'https://example.com/a', source: '' }] } } };
  expect(() => readActivity(JSON.stringify(news))).toThrow('公式ページ以外');
  expect(() => readActivity(JSON.stringify({ ...base, schema: 'x', members: {} }))).toThrow('形式');
});
