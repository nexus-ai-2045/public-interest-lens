import { describe, expect, it } from 'vitest';
import { affiliationOf } from './caucus-label';

describe('名簿の会派の略称 → 党名', () => {
  it('参議院の「民主」は国民民主党、「い党」はれいわ新選組（略称のまま政党名に見せない）', () => {
    expect(affiliationOf('参議院', '民主')).toBe('国民民主党');
    expect(affiliationOf('参議院', 'い党')).toBe('れいわ新選組');
    expect(affiliationOf('参議院', '立憲')).toBe('立憲民主党');
  });
  it('衆議院の略称', () => {
    expect(affiliationOf('衆議院', '中道')).toBe('中道改革連合');
    expect(affiliationOf('衆議院', '無')).toBe('無所属');
  });
  it('決められない略称は「（会派）」を付け、党名だと読めないようにする', () => {
    expect(affiliationOf('衆議院', '志士')).toBe('志士（会派）');
    expect(affiliationOf('参議院', '沖縄')).toBe('沖縄の風（会派）');
    expect(affiliationOf('参議院', '未知')).toBe('未知（会派）');
  });
});
