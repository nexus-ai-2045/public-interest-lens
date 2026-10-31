import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RefBasisNote } from './LawCatalog';

describe('参考値の理由・根拠の表示', () => {
  it('理由と根拠を折りたたまず出し、順位・議員配分に使わないと明記する', () => {
    const html = renderToStaticMarkup(<RefBasisNote item={{ id: '閣法-1-1', refReason: '検証で桁が合わなかった', refBasis: '統計表の窓' }} />);
    expect(html).toContain('参考値（検証で降格）');
    expect(html).toContain('順位・議員配分には使わない');
    expect(html).toContain('検証で桁が合わなかった');
    expect(html).toContain('統計表の窓');
    expect(html).not.toContain('<details');
    expect(html).not.toContain('/demo');
  });

  it('根拠が無ければ理由だけ、理由が無ければ何も出さない', () => {
    expect(renderToStaticMarkup(<RefBasisNote item={{ id: 'a', refReason: '理由' }} />)).not.toContain('根拠</span>');
    expect(renderToStaticMarkup(<RefBasisNote item={{ id: 'a' }} />)).toBe('');
  });
});
