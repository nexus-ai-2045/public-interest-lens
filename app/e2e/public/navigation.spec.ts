import { expect, test } from '@playwright/test';
import { watchPage } from './helpers';

const PAGES = ['/members', '/ranking', '/votes', '/numbers', '/world', '/history', '/policies', '/actors', '/methodology'];

test.describe('全ページ共通の導線', () => {
  test('どのページも h1 が1つで、ページごとに違い、エラーが出ない', async ({ page }) => {
    const titles = new Set<string>();
    for (const path of PAGES) {
      const watch = watchPage(page);
      await page.goto(path);
      const h1 = page.getByRole('heading', { level: 1 });
      await expect(h1, `${path} の h1`).toHaveCount(1);
      titles.add((await h1.textContent())!.trim());
      watch.expectClean();
    }
    expect(titles.size, 'h1 がページごとに違う').toBe(PAGES.length);
  });

  test('最初の Tab で「本文へ移動」が出て、押すと本文に移る', async ({ page }) => {
    await page.goto('/votes');
    await page.keyboard.press('Tab');
    const skip = page.getByRole('link', { name: '本文へ移動' });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#main$/);
    await expect(page.locator('main#main')).toHaveCount(1);
  });

  test('全ページ末尾の訂正リンクは訂正用テンプレートを指定している', async ({ page }) => {
    for (const path of PAGES) {
      await page.goto(path);
      await expect(page.locator('.public-site-notice a[href*="issues/new"]'), path).toHaveAttribute('href', /[?&]template=correction\.yml(&|$)/);
    }
  });
});

test.describe('/votes（政党・議員の賛否）', () => {
  test('一覧・title・データ応答が正しく、リンクの押す領域が24px以上ある', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/votes');
    await expect(page).toHaveTitle(/政党・議員の賛否/);
    await expect(page.getByRole('heading', { level: 1, name: 'どの政党・議員が、どの法律に賛成・反対したか' })).toBeVisible();
    const links = page.locator('.stance-sub a', { hasText: '議案の経過' });
    await expect(links.first()).toBeVisible();
    expect((await links.first().boundingBox())!.height).toBeGreaterThanOrEqual(24);
    watch.expectClean();
  });
});

test.describe('存在しないパス', () => {
  for (const path of ['/nonexistent', '/members/zzz']) {
    test(`${path} は「見つかりません」と主要ページへの案内を出し、閉じた画面へリンクしない`, async ({ page }) => {
      const watch = watchPage(page);
      await page.goto(path); // 静的ホスティングなので HTTP は 200。画面の案内で伝える。
      await expect(page.getByRole('heading', { level: 1, name: 'ページが見つかりません' })).toBeVisible();
      await expect(page).toHaveTitle('ページが見つかりません｜国賊ランキング');
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex');
      await expect(page.getByRole('main').getByRole('link', { name: '議員ランキングを見る' })).toHaveAttribute('href', '/members');
      await expect(page.locator('a[href^="/demo"]')).toHaveCount(0);
      await expect(page.getByText('架空デモ')).toHaveCount(0);
      watch.expectClean();
    });
  }
});

test.describe('反論・訂正ボタン', () => {
  test('/ranking の行を開くと、訂正用テンプレートと対象つきの Issue 作成画面へのリンクが出る', async ({ page }) => {
    await page.goto('/ranking');
    const row = page.locator('.laws-list > li').first();
    await expect(row).toBeVisible();
    await row.locator('.laws-row-head').click();
    const link = row.locator('a.correction-link');
    await expect(link).toBeVisible();
    const href = new URL((await link.getAttribute('href'))!);
    expect(href.origin + href.pathname).toBe('https://github.com/nexus-ai-2045/public-interest-lens/issues/new');
    expect(href.searchParams.get('template')).toBe('correction.yml');
    expect(href.searchParams.get('target')).toContain('https://kokuzoku.nexusai2045.com/ranking');
    await expect(link).toHaveAttribute('rel', /noopener/);
  });

  test('/members の議員を開くと、同じ形のリンクが出る', async ({ page }) => {
    await page.goto('/members');
    const first = page.locator('ol.members-list > li').first();
    await expect(first).toBeVisible();
    await first.locator('summary').click();
    const href = new URL((await first.locator('a.correction-link').getAttribute('href'))!);
    expect(href.searchParams.get('template')).toBe('correction.yml');
    expect(href.searchParams.get('title')).toMatch(/^\[訂正\] /);
  });
});
