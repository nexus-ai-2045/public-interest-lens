import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LawName, lawNameText, plainLawName } from './law-name';

describe('法律の呼び方', () => {
  it('何をするかを先に、正式名をかっこで後に置く', () => {
    expect(plainLawName('原発の安全を見る、独立性の高い委員会を環境省の下に作る')).toBe('原発の安全を見る、独立性の高い委員会を環境省の下に作る法律');
    expect(plainLawName('認定農業者などの担い手に、米や麦などの経営を支える交付金を交付する。')).toBe('認定農業者などの担い手に、米や麦などの経営を支える交付金を交付する法律');
    expect(lawNameText('原子力規制委員会設置法案', '原発の安全を見る委員会を作る')).toBe('原発の安全を見る委員会を作る法律（AI要約／正式名：原子力規制委員会設置法案）');
    expect(renderToStaticMarkup(<LawName title="原子力規制委員会設置法案" what="原発の安全を見る委員会を作る" />)).toContain('AI要約');
  });

  it('一文が無いときは題名から作らず、正式名だけを理由つきで出す', () => {
    expect(lawNameText('道路運送車両法の一部を改正する法律案')).toBe('道路運送車両法の一部を改正する法律案');
    const html = renderToStaticMarkup(<LawName title="道路運送車両法の一部を改正する法律案" withheld="shared" />);
    expect(html).toContain('道路運送車両法の一部を改正する法律案');
    expect(html).toContain('ほかの法案とまとめた説明');
    expect(html).not.toContain('正式名');
    expect(renderToStaticMarkup(<LawName title="道路運送車両法の一部を改正する法律案" withheld="shared" compact />)).not.toContain('一文なし');
  });
});
