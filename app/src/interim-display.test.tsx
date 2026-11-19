import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { INTERIM_DISPLAY, foldAllReference, rankingPaused, type InterimDisplay } from './interim-display';
import { InterimNotice } from './InterimNotice';

const off: InterimDisplay = { ...INTERIM_DISPLAY, active: false };

describe('当て直しまでの暫定表示の切り替え', () => {
  it('切り替え1つで、順位の一時停止と参考の額の畳みが一緒に入り、一緒に戻る', () => {
    expect(rankingPaused(INTERIM_DISPLAY)).toBe(INTERIM_DISPLAY.active);
    expect(foldAllReference(INTERIM_DISPLAY)).toBe(INTERIM_DISPLAY.active);
    expect(rankingPaused(off)).toBe(false);
    expect(foldAllReference(off)).toBe(false);
  });

  it('いまは当て直し中（2026-11-19 から）。当て直しと新しい抜き取りが済むまで切らない', () => {
    expect(INTERIM_DISPLAY).toMatchObject({ active: true, label: '振り分けの当て直し中', since: '2026-11-19' });
  });

  it('注記は、何が止まっているか（順位・参考の額・議員の順位）と、データを消していないことを書く', () => {
    const html = renderToStaticMarkup(<InterimNotice display={{ ...INTERIM_DISPLAY, active: true }} />);
    for (const word of ['振り分けの当て直し中', '額の順位を止め', '参考の額を畳んで', '消さずに残して', '議員の順位も出していません']) expect(html).toContain(word);
    expect(html).toContain('role="note"');
  });

  it('切り替えが切れていれば注記を出さない', () => {
    expect(renderToStaticMarkup(<InterimNotice display={off} />)).toBe('');
  });
});
