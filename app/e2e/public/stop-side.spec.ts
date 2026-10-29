import { expect, test } from '@playwright/test';
import { watchPage } from './helpers';

test.describe('/stop-side（技術を止めた側と判決）', () => {
  test('全件の件数と確認の印、データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/stop-side');
    await expect(page).toHaveTitle(/技術を止めた側と判決/);
    await expect(page.getByRole('heading', { level: 2, name: '新しい技術を、誰が止めたのか' })).toBeVisible();
    const total = page.getByRole('list', { name: '全体の件数' });
    await expect(total).toContainText('1,227件の記録');
    await expect(total).toContainText('653確認済み');
    await expect(total).toContainText('524保留');
    await expect(total).toContainText('50未照合');
    await expect(total).toContainText('40件の判決');
    expect(watch.dataUrls.some(url => url.endsWith('/distribution/stop-side.json'))).toBe(true);
    watch.expectClean();
  });

  test('確認の状態で絞ると件数とURLが変わり、リンクは別タブの https だけ', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/stop-side');
    await page.getByRole('group', { name: '確認の状態' }).getByRole('button', { name: '未照合' }).click();
    await expect(page).toHaveURL(/v=u/);
    await expect(page.getByRole('list', { name: 'いまの条件の件数' })).toContainText('50件');
    await expect(page.locator('.stop-item .stop-state.is-u').first()).toBeVisible();
    await expect(page.locator('.stop-item .stop-state.is-c')).toHaveCount(0);
    const hrefs = await page.locator('.stop-item a').evaluateAll(links => links.map(a => (a as HTMLAnchorElement).href));
    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.every(h => h.startsWith('https://'))).toBe(true);
    watch.expectClean();
  });

  test('判決の一覧と保留の理由が出る', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/stop-side');
    await expect(page.getByRole('heading', { level: 3, name: /規制をめぐる判決（40件）/ })).toBeVisible();
    expect(await page.locator('.stop-ruling').count()).toBe(40);
    await expect(page.getByRole('heading', { level: 4, name: '保留の判決（8件）' })).toBeVisible();
    watch.expectClean();
  });
});
