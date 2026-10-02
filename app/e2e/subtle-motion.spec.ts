import { test, expect } from '@playwright/test';

test('詳細設定は収納直後から操作対象外になりフォーカスを入口へ戻す', async ({ page }) => {
  await page.goto('/ranking');
  const toggle = page.getByRole('button', { name: '詳細設定', exact: true });
  const panel = page.locator('#advanced-settings');
  await expect(panel).toHaveAttribute('inert', '');
  await toggle.click();
  await expect(panel).not.toHaveAttribute('inert', '');
  await panel.locator('select').first().focus();
  // フォーカスが内部に残る閉操作でも入口へ戻ります。
  await toggle.evaluate((element: HTMLElement) => element.click());
  await expect(toggle).toBeFocused();
  await expect(panel).toHaveAttribute('inert', '');
  await expect(panel).toHaveAttribute('aria-hidden', 'true');
  await expect(panel).not.toBeVisible();
});

test('連続切替後も最後の方向・選択・URLが一致し戻ると復元する', async ({ page }) => {
  await page.goto('/?domain=economy&direction=harm&period=4');
  for (const direction of ['貢献', '悪影響', '貢献']) {
    await page.getByRole('button', { name: direction, exact: true }).click();
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  }
  const motion = page.locator('#inspector-content > div').last();
  await expect.poll(() => motion.evaluate(el => getComputedStyle(el).transform)).toBe('none');
  await expect.poll(() => motion.evaluate(el => getComputedStyle(el).opacity)).toBe('1');
  await expect(page).toHaveTitle('国士ランキング');
  await expect(page.locator('.app-shell')).toHaveAttribute('data-theme', 'light');
  await expect(page).toHaveURL(/view=benefit/);
  await expect(page.locator('.inspector-heading')).toContainText('架空議員べに');
  await page.reload();
  await expect(page).toHaveTitle('国士ランキング');
  await page.getByRole('button', { name: '悪影響', exact: true }).click();
  await page.goBack();
  await expect(page).toHaveTitle('国士ランキング');
});

test('動きを減らす設定は切替中にも適用されます', async ({ page }) => {
  await page.goto('/ranking');
  await page.getByRole('tab', { name: '政策', exact: true }).click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('tab', { name: '根拠', exact: true }).click();
  const motion = page.locator('#inspector-content > div').last();
  await expect.poll(() => motion.evaluate(el => getComputedStyle(el).transform)).toBe('none');
  await expect.poll(() => motion.evaluate(el => getComputedStyle(el).opacity)).toBe('1');
  expect(await page.locator('.settings-button').evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s');
  await expect(page.locator('.source-panel')).toContainText('表示している資料はすべて架空です。');
});
