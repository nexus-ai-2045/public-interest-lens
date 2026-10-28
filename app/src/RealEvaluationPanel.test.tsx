import { afterEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { EvidenceDatasetRoot } from './RealEvaluationPanel';

const mode = vi.hoisted(() => ({ PUBLIC_SITE: true }));
vi.mock('./site-mode', () => mode);
vi.mock('./MembersPage', () => ({ MembersPage: () => <p>real-members</p>, MethodologyPage: () => null }));
afterEach(() => vi.unstubAllGlobals());

function renderRoute(pathname: string, search: string, publicSite = true) {
  mode.PUBLIC_SITE = publicSite;
  vi.stubGlobal('window', { location: { pathname, search } });
  return renderToStaticMarkup(<EvidenceDatasetRoot fictional={<p>fictional-ranking</p>} />);
}

it('公開トップは共有用・人物指定・算定条件のクエリでも実資料を表示する', () => {
  for (const query of ['', '?utm_source=share', '?name=example', '?r=50&p=30&tone=benefit', '?dataset=fiction']) {
    expect(renderRoute('/', query)).toContain('real-members');
  }
});

it('公開版の非公開入口とデモ拒否、非公開版の架空保存リンクを維持する', () => {
  expect(renderRoute('/records', '')).not.toContain('fictional-ranking');
  expect(renderRoute('/demo', '')).not.toContain('fictional-ranking');
  expect(renderRoute('/', '?dataset=real')).not.toContain('real-members');
  expect(renderRoute('/', '?dataset=fiction&release=saved', false)).toContain('fictional-ranking');
});
