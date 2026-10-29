import { expect, it } from 'vitest';
import { readPoliticalFunds } from './political-funds';

const pdf = 'https://www.soumu.go.jp/main_content/000718006.pdf';
const base = { schema: 'political-funds-groups/v1', method: '', rosters: [{ name: '架空の名簿', url: pdf }], counts: { rosterMembers: 1, linkedMembers: 1, unlinkedMembers: 0, groups: 1 } };

it('総務省の名簿 PDF の URL だけを受け付ける', () => {
  const ok = { ...base, members: { 甲: [{ name: '架空の後援会', kind: '資金管理団体', filedWith: '総務大臣', sources: [pdf] }] } };
  expect(readPoliticalFunds(JSON.stringify(ok)).members['甲'][0].name).toBe('架空の後援会');
  const bad = { ...base, members: { 甲: [{ name: 'x', kind: '資金管理団体', filedWith: '総務大臣', sources: ['https://example.com/a.pdf'] }] } };
  expect(() => readPoliticalFunds(JSON.stringify(bad))).toThrow('総務省の名簿');
  expect(() => readPoliticalFunds(JSON.stringify({ ...base, schema: 'x', members: {} }))).toThrow('形式');
});
