import { test, expect } from '@playwright/test';

test('法律ランキングは全法律と政策を理由つきで並べ、行を開くと詳細が出て、架空デモは別のパスにある', async ({ page }) => {
  await page.goto('/ranking');
  await expect(page.getByRole('heading', { name: '法律と政策ごとの損失と便益' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /全部の法律と政策（3,4\d\d件）/ })).toBeVisible();
  await expect(page.locator('.laws-row')).toHaveCount(60);
  await expect(page.getByText('結果への責任を測るもので', { exact: false })).toBeVisible();
  await page.getByRole('searchbox', { name: '法律の名前・番号・分野で探す' }).fill('金融再生プログラム');
  const row = page.locator('.laws-row').first();
  await expect(row).toContainText('金融再生プログラム');
  await row.locator('.laws-row-head').click();
  await expect(row.getByRole('heading', { name: /計算の流れ/ })).toBeVisible();
  await page.getByRole('link', { name: '架空デモ' }).first().click();
  await expect(page).toHaveURL(/\/demo$/);
  await expect(page.locator('#ranking')).toBeVisible();
});
