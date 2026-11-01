import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RefBasisNote, SharedRefNote } from './LawCatalog';

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

describe('共有額の参考値の表示', () => {
  const shared = { key: 'k', size: 28, median: 380e12, low: 120e12, high: 470e12, side: 'loss' as const, whole: true, ratio: 0.68, baseYear: 1997 };
  it('合計の一部（0〜合計）として出し、法律だけの効果でないこと・足さないこと・確かさ低を明記する', () => {
    const html = renderToStaticMarkup(<SharedRefNote item={{ id: '衆法-139-18', shared }} />);
    for (const word of ['共有額の参考値', '確かさ：低', '順位・合計・議員配分には使わない', '足し合わせない', '0〜380', '28本が共有', 'この法律だけの効果ではない', '経済全体', '日本の付加価値1年分（1997年）の約68%']) expect(html).toContain(word);
    expect(html).not.toContain('検証で降格');
  });
  it('規模が小さければ付加価値の割合を出さず、共有額でなければ何も出さない', () => {
    expect(renderToStaticMarkup(<SharedRefNote item={{ id: 'a', shared: { ...shared, ratio: 0.02, whole: false } }} />)).not.toContain('規模');
    expect(renderToStaticMarkup(<SharedRefNote item={{ id: 'a' }} />)).toBe('');
  });
});
