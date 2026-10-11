import { test, expect } from '@playwright/test';

for (const width of [390, 1440]) {
  test(`公開配布の金融再生プログラムを保留のまま読める ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/history?years=40');
    await expect(page.getByText('公開配布版です')).toBeVisible();
    await expect(page.getByRole('heading', { name: '金融再生プログラム' })).toBeVisible();
    await page.getByLabel('見る期間').selectOption('30');
    await expect(page.getByRole('heading', { name: '金融再生プログラム' })).toBeVisible();
    await page.getByLabel('見る期間').selectOption('4');
    await expect(page.getByRole('heading', { name: '金融再生プログラム' })).toHaveCount(0);
    await expect(page.getByText('重ならない候補')).toBeVisible();
    await page.goto('/policies');
    await expect(page.getByRole('heading', { name: '金融再生プログラム' })).toBeVisible();
    await page.getByRole('tab', { name: '実施' }).focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab', { name: '観測された結果' })).toBeFocused();
    await page.keyboard.press('End');
    await expect(page.getByRole('tab', { name: '不足している資料' })).toBeFocused();
    await expect(page.getByText('GDP損失額も置かない')).toBeVisible();
    await page.goto('/actors');
    await expect(page.getByRole('heading', { name: '竹中平蔵', level: 2 })).toHaveCount(0);
    await expect(page.getByText('竹中平蔵').first()).toBeVisible();
    await expect(page.getByText('点数は付けていません').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('未知の統計版は現在版へ置き換えません', async ({ page }) => {
  await page.goto(`/history?edition=${'0'.repeat(64)}`);
  await expect(page.getByRole('alert')).toContainText('長期統計を読み込めませんでした');
  await expect(page.getByText('公開配布版です')).toHaveCount(0);
});
