import { expect, test } from '@playwright/test';
import { watchPage } from './helpers';

// 計算方法の見直し中は、議員・政党の順位と点（参考の表を含む）を出さない（MEMBER_RANKING_HIDDEN）。
// 戻すときは、このファイルの履歴から議員ランキング・全議員一覧・政党比較の検査を戻す。
test.describe('/members（順位を非表示）', () => {
  test('見直し中の一文を出し、順位・点・全議員の表・政党比較は出さない', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    await expect(page).toHaveTitle(/議員・実名/);
    await expect(page.getByRole('heading', { level: 1, name: 'この人が失わせた額・生んだ額' })).toBeVisible();
    await expect(page.getByRole('note').filter({ hasText: '計算方法の見直し中' })).toBeVisible();
    for (const selector of ['ol.members-list', '.tone-hero', '.all-members', '.members-top', '.members-tabs']) await expect(page.locator(selector)).toHaveCount(0);
    await expect(page.getByRole('region', { name: '全議員' })).toHaveCount(0);
    watch.expectClean();
  });
  test('公開サイトにテスト用の仮データ画面へのリンクが無く、/demo は開けない', async ({ page }) => {
    await page.goto('/members');
    await expect(page.locator('a[href^="/demo"]')).toHaveCount(0);
    await page.goto('/demo');
    await expect(page.getByRole('heading', { level: 1, name: 'この機能は公開版に含まれていません' })).toBeVisible();
  });
});
