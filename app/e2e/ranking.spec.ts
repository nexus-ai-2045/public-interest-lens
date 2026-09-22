import { test, expect } from '@playwright/test';

test('順位変更から人物・政策の根拠へ遡り、未評価と検索を区別する', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '人物ワーストランキング' })).toBeVisible();
  await expect(page.locator('tbody tr').first()).toContainText('架空議員あおい');
  await page.getByRole('slider', { name: '所得の重み' }).fill('100');
  await expect(page.locator('tbody tr').first()).toContainText('架空議員べに');
  await page.getByRole('button', { name: '架空議員べに', exact: true }).click();
  await page.getByRole('button', { name: /架空の所得配分制度/ }).click();
  await expect(page.locator('.evidence-detail')).toContainText('架空の所得配分制度');
  await expect(page.locator('.evidence-detail')).toContainText('人口構成');
  for (const name of ['生産性', '所得', '財政']) await page.getByRole('slider', { name: `${name}の重み` }).fill('0');
  await expect(page.getByRole('status').filter({ hasText: '全員未評価' })).toBeVisible();
  await expect(page.locator('tbody tr').first()).toContainText('未評価');
  await page.getByRole('button', { name: '均等重みに戻す' }).click();
  await expect(page.locator('tbody tr').first()).toContainText('架空議員あおい');
  await page.getByLabel('人物名で検索').fill('存在しない名前');
  await expect(page.locator('tbody tr')).toHaveCount(0);
  await expect(page.getByRole('status').filter({ hasText: '該当する人物がいません' })).toBeVisible();
  await page.getByLabel('人物名で検索').fill('');
  await page.getByLabel('開始年').selectOption('2026');
  await expect(page.locator('tbody tr').first()).toContainText('未評価');
  expect(errors).toEqual([]);
});

test('PCとモバイルの表示、外部通信、架空表示', async ({ page }, testInfo) => {
  const external: string[] = [];
  page.on('request', request => {
    if (!request.url().startsWith('http://127.0.0.1:4179')) external.push(request.url());
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/');
    await expect(page.getByText('全員・全政策・全資料が架空です。')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`ranking-${width}.png`), fullPage: true });
  }
  expect(external).toEqual([]);
});
