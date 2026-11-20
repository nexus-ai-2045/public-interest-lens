import { expect, it } from 'vitest';
import { AMBIGUOUS, NO_TERM, OUTSIDE_HOUSE, OUTSIDE_TERM, PersonLedger, UNRESOLVED, linkPerson, type PersonRow } from './person-id';

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
  expect(ledger.resolve('森川空', '参議院')).toMatchObject({ id: '', reason: UNRESOLVED });
});

const termed = (id: string, house: string, start: string, end: string): PersonRow => ({
  id, name: '青木蓮', reading: '', house, district: '', terms: [{ start, end, house }],
});

it('在任が重ならない同姓同名は、その日付に在任していた方だけに結び、期間の外は未結合', () => {
  const early = termed('青木蓮（衆・東京1）', '衆議院', '1990-01-01', '1996-12-31');
  const late = termed('青木蓮（参・比例）', '参議院', '2010-01-01', '2016-12-31');
  for (const candidates of [[early, late], [late, early]]) {
    expect(linkPerson(candidates, '1992-06-01', '')).toEqual({ id: early.id, reason: '' });
    expect(linkPerson(candidates, '2012-06-01', '')).toEqual({ id: late.id, reason: '' });
    expect(linkPerson(candidates, '2000-06-01', '')).toEqual({ id: '', reason: OUTSIDE_TERM });
  }
  const overlap = { ...early, terms: [{ start: '2010-01-01', end: '2016-12-31', house: '衆議院' }] };
  expect(linkPerson([overlap, late], '2012-06-01', '')).toEqual({ id: '', reason: AMBIGUOUS });
  expect(linkPerson([late, overlap], '2012-06-01', '')).toEqual({ id: '', reason: AMBIGUOUS });
  expect(linkPerson([late, overlap], '2012-06-01', '参議院')).toEqual({ id: late.id, reason: '' });
  expect(linkPerson([early], '1992-06-01', '参議院')).toEqual({ id: '', reason: OUTSIDE_HOUSE });
  expect(linkPerson([early], '2000-06-01', '')).toEqual({ id: '', reason: OUTSIDE_TERM });
  expect(linkPerson([{ ...early, terms: [] }], '1992-06-01', '参議院')).toEqual({ id: '', reason: NO_TERM });
  const mover: PersonRow = {
    ...early, id: '架空蓮', house: '参議院',
    terms: [{ start: '1990-01-01', end: '1996-12-31', house: '衆議院' }, { start: '2010-01-01', end: '2016-12-31', house: '参議院' }],
  };
  expect(linkPerson([mover], '1992-06-01', '衆議院')).toEqual({ id: mover.id, reason: '' });
  expect(linkPerson([mover], '2012-06-01', '参議院')).toEqual({ id: mover.id, reason: '' });
  expect(linkPerson([mover], '2012-06-01', '衆議院').id).toBe('');
});

it('在任が複数なら `;` で分けて読み、院の指定はその院の在任だけに結ぶ', () => {
  const ledger = new PersonLedger(['人物ID,氏名,読み,院,選挙区,別表記,在任の院,在任開始,在任終了,在任の出典',
    '架空蓮,架空蓮,,,,,衆議院;参議院,1990-01-01;2010-01-01,1996-12-31;2016-12-31,出典甲;出典乙'].join('\n'));
  expect(ledger.resolve('架空蓮', '衆議院', '1992-06-01').id).toBe('架空蓮');
  expect(ledger.resolve('架空蓮', '参議院', '1992-06-01').id).toBe('');
  expect(ledger.resolve('架空蓮', '参議院', '2012-06-01').id).toBe('架空蓮');
});
