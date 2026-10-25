import { describe, expect, it } from 'vitest';
import { partyComparison, partyById, sortPartyRows } from './party-compare';
import type { PublicMember } from './members-build';
import type { ReferenceMember } from './members-reference';

const member = (id: string, net: number) => ({ id, name: id, net: { low: net, median: net, high: net } }) as unknown as PublicMember;
const ref = (id: string, party: string | null) => ({ id, name: id, current: party ? { house: '衆議院', party, district: '' } : null }) as unknown as ReferenceMember;

describe('政党ごとの比較', () => {
  const parties = partyById([ref('a', 'X党'), ref('b', 'X党'), ref('c', 'Y党'), ref('d', null)]);
  const { rows, excluded } = partyComparison([member('a', -300), member('b', 100), member('c', -50), member('d', -999), member('e', 0)], parties);
  it('現職の所属政党で足し、政党が分からない人は数えて外す', () => {
    expect(excluded).toBe(2);
    expect(rows.find(r => r.party === 'X党')).toMatchObject({ people: 2, total: -200, perPerson: -100, loss: 1, benefit: 1, zero: 0 });
    expect(rows.find(r => r.party === 'Y党')).toMatchObject({ people: 1, total: -50, perPerson: -50 });
  });
  it('並べ替え：1人あたり・合計は小さい順、人数は多い順', () => {
    expect(sortPartyRows(rows, 'perPerson').map(r => r.party)).toEqual(['X党', 'Y党']);
    expect(sortPartyRows(rows, 'total').map(r => r.party)).toEqual(['X党', 'Y党']);
    expect(sortPartyRows(rows, 'people').map(r => r.party)).toEqual(['X党', 'Y党']);
  });
});
