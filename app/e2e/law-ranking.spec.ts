import { test, expect } from '@playwright/test';

test('法律ランキングは実データの件数と保留の理由を出し、架空デモは別のパスにある', async ({ page }) => {
  await page.goto('/ranking');
  await expect(page.getByRole('heading', { name: '法律ごとの損失と便益' })).toBeVisible();
  await expect(page.getByText(/3,415本のうち、額を公開できたのは\d+本です/)).toBeVisible();
  await expect(page.getByText('結果への責任を測るもので', { exact: false })).toBeVisible();
  await expect(page.locator('details.law-held')).not.toHaveCount(0);
  await page.getByRole('link', { name: '架空デモ' }).first().click();
  await expect(page).toHaveURL(/\/demo$/);
  await expect(page.locator('#ranking')).toBeVisible();
});
