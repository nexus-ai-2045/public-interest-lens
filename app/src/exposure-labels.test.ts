import { describe, expect, it } from 'vitest';
import { exposureGroupLabels, industryName } from './exposure-labels';

describe('曝露ランキングの群の表示名', () => {
  it('産業コードを産業名にし、表に無いコードはそのまま出します', () => {
    expect(industryName('C')).toBe('製造業');
    expect(industryName('M+N')).toBe('専門・科学技術、業務支援サービス業');
    expect(industryName('ZZ')).toBe('ZZ');
  });

  it('群（産業×年）には産業名と年を、内訳の束（産業コードだけ）には各年の合計を付けます', () => {
    const labels = exposureGroupLabels([{ id: 'C|1998', group: 'C', window: '1998年' }, { id: 'C|1999', group: 'C', window: '1999年' }, { id: 'J|2001', group: 'J', window: '2001年' }]);
    expect(labels).toContainEqual({ id: 'C|1998', group: '製造業', window: '1998年' });
    expect(labels).toContainEqual({ id: 'C', group: '製造業', window: '各年の合計' });
    expect(labels).toContainEqual({ id: 'J', group: '情報通信業', window: '各年の合計' });
    expect(labels.filter(l => l.id === 'C')).toHaveLength(1);
  });
});
