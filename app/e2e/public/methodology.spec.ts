import { expect, test } from '@playwright/test';
import { watchPage } from './helpers';

test.describe('/methodology（計算方法）', () => {
  test('見出しが複数出て、title・データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/methodology');
    await expect(page).toHaveTitle(/計算方法/);
    await expect(page.getByRole('heading', { level: 2, name: 'どう計算しているか' })).toBeVisible();
    const sections = page.locator('main.methodology h3');
    expect(await sections.count()).toBeGreaterThanOrEqual(4);
    await expect(page.getByRole('heading', { level: 3, name: /この人が失わせた額・生んだ額/ })).toBeVisible();
    await expect(page.getByRole('heading', { level: 3, name: '4. 訂正と反論' })).toBeVisible();
    watch.expectClean();
  });

  test('配布データへのリンクはJSONを返し、ナビで他ページへ移れる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/methodology');
    const link = page.getByRole('link', { name: /members\.json/ });
    await expect(link).toBeVisible();
    const response = await page.request.get((await link.getAttribute('href'))!);
    expect(response.ok()).toBe(true);
    expect(response.headers()['content-type']).toContain('json');

    await expect(page.getByRole('navigation', { name: '主なページ' }).getByRole('link', { name: '計算方法' })).toHaveAttribute('aria-current', 'page');
    await page.getByRole('navigation', { name: '主なページ' }).getByRole('link', { name: '法律ランキング' }).click();
    await expect(page).toHaveURL(/\/ranking$/);
    await expect(page).toHaveTitle(/法律・政策ランキング/);
    watch.expectClean();
  });
});
