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

test('並べ替えに損失順・便益順があり、一覧を共有でき、額なしの数が一覧とそろい、/votes へ行ける', async ({ page }) => {
  await page.goto('/ranking?sort=loss');
  await expect(page.getByLabel('並べ替え')).toHaveValue('loss');
  await page.getByLabel('並べ替え').selectOption('benefit');
  await expect(page).toHaveURL(/sort=benefit/);
  await expect(page.getByRole('button', { name: 'この一覧を共有' })).toBeVisible();
  // 上部カードの額なしは、一覧の「額なし」の絞り込みの件数と同じ（政策を含む）。
  const card = await page.locator('a.laws-stat', { hasText: '額なし（理由つき）' }).locator('strong').innerText();
  await page.getByRole('button', { name: '額なし', exact: true }).click();
  const showAll = page.getByRole('button', { name: '同じ観測の法律もすべて表示' });
  if (await showAll.isVisible()) await showAll.click();
  await expect(page.locator('.laws-count')).toContainText(`${card.replace('件', '')}件`);
  await expect(page.getByRole('link', { name: '法案の賛否' })).toHaveAttribute('href', '/votes');
});

test('/methodology#spec-price で式の節が開く', async ({ page }) => {
  await page.goto('/methodology#spec-price');
  const section = page.locator('details#spec-price');
  await expect(section).toHaveAttribute('open', '');
  await expect(section).toBeInViewport();
});
