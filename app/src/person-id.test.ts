import { expect, it } from 'vitest';
import { PersonLedger } from './person-id';

const persons = (rows: string[][]) => ['人物ID,氏名,読み,院,選挙区,別表記', ...rows.map(r => [...r, ''].join(','))].join('\n');
const row = (院: string, 選挙区: string, 読み: string) => ({ 氏名: '森川 空', 院, 選挙区, 読み });

it('名簿の行は読みまで合う1人にだけ結び、並び順で決めない', () => {
  // 同じ選挙区に読みの違う後任が入った台帳（scripts/person_ids.py が後任に選挙区付きIDを付けたもの）。
  const ledger = new PersonLedger(persons([['森川空', '森川空', 'もりかわ そら', '衆議院', '東京3'], ['森川空（衆・東京3）', '森川空', 'もりかわ くう', '衆議院', '東京3']]));
  expect(ledger.rosterPerson(row('衆議院', '東京3', 'もりかわ くう'))?.id).toBe('森川空（衆・東京3）');
  expect(ledger.rosterPerson(row('衆議院', '東京3', 'もりかわ そら'))?.id).toBe('森川空');
  // 区割り変更などで院と読みが合う人が2人いて選挙区が合わなければ、決めない。
  const two = new PersonLedger(persons([['森川空（衆・東京3）', '森川空', 'もりかわ そら', '衆議院', '東京3'], ['森川空（衆・大阪1）', '森川空', 'もりかわ そら', '衆議院', '大阪1']]));
  expect(two.rosterPerson(row('衆議院', '東京30', 'もりかわ そら'))).toBeUndefined();
});

it('院の分からない歴代の人がいる同姓同名は、院で決めない', () => {
  const ledger = new PersonLedger(persons([['森川空', '森川空', '', '', ''], ['森川空（参・比例）', '森川空', 'もりかわ そら', '参議院', '比例']]));
  expect(ledger.resolve('森川空', '参議院')).toBeNull();
});
