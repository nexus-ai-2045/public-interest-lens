import { expect, test } from '@playwright/test';

test('未評価と保留を重複算入の説明と区別する', async ({ page }) => {
  await page.goto('/?domain=economy&direction=harm&period=4');
  await page.getByRole('button', { name: '架空議員べに', exact: true }).click();
  await expect(page.getByText('現在の条件に合う行動がありません。', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '全履歴を見る', exact: true }).click();
  await expect(page.locator('.policy-metrics')).toContainText('現在の条件では未評価');
  await expect(page.locator('.policy-metrics')).not.toContainText('重複算入');
  await page.getByRole('button', { name: '架空候補だいだい', exact: true }).click();
  await expect(page.locator('.policy-metrics')).toContainText('影響の根拠が未検証のため、評価を保留しています');
  await expect(page.locator('.policy-metrics')).not.toContainText('重複算入');
});

test('詳細タブは矢印・Home・Endで選択とフォーカスが移る', async ({ page }) => {
  await page.goto('/');
  const action = page.getByRole('tab', { name: '行動', exact: true });
  const policy = page.getByRole('tab', { name: '政策', exact: true });
  const evidence = page.getByRole('tab', { name: '根拠', exact: true });
  await action.focus();
  await action.press('ArrowRight');
  await expect(policy).toHaveAttribute('aria-selected', 'true');
  await expect(policy).toBeFocused();
  await policy.press('End');
  await expect(evidence).toHaveAttribute('aria-selected', 'true');
  await expect(evidence).toBeFocused();
  await evidence.press('Home');
  await expect(action).toHaveAttribute('aria-selected', 'true');
  await expect(action).toBeFocused();
});

test('動きを減らす設定で人物選択が即時スクロールになる', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (options?: boolean | ScrollIntoViewOptions) {
      if (this.id === 'person') (window as Window & { personScroll?: boolean | ScrollIntoViewOptions }).personScroll = options;
      return original.call(this, options);
    };
  });
  await page.goto('/');
  await page.getByRole('button', { name: '架空議員べに', exact: true }).click();
  const behavior = await page.evaluate(() => ((window as Window & { personScroll?: ScrollIntoViewOptions }).personScroll)?.behavior);
  expect(behavior).toBe('auto');
});

test('方向の切替で製品タイトルを変える', async ({ page }) => {
  await page.goto('/?domain=economy&direction=harm&period=4');
  await expect(page.getByRole('heading', { level: 1, name: '国賊ランキング' })).toBeVisible();
  await page.getByRole('button', { name: '貢献', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: '国士ランキング' })).toBeVisible();
  await expect(page).toHaveTitle(/国士ランキング/);
  await expect(page.locator('.app-shell')).toHaveAttribute('data-theme', 'light');
  await page.reload();
  await expect(page.getByRole('heading', { level: 1, name: '国士ランキング' })).toBeVisible();
  await page.getByRole('button', { name: '悪影響', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: '国賊ランキング' })).toBeVisible();
  await expect(page.locator('.app-shell')).toHaveAttribute('data-theme', 'dark');
  await page.goBack();
  await expect(page.getByRole('heading', { level: 1, name: '国士ランキング' })).toBeVisible();
  await expect(page.locator('.app-shell')).toHaveAttribute('data-theme', 'light');
});

test('政策から別々の行動と資料へ進み、三次元の描画を起動しない', async ({ page }) => {
  await page.goto('/?domain=economy&direction=harm&period=4');
  await expect(page.getByRole('region', { name: '政策と行動のつながり' })).toBeVisible();
  await expect(page.locator('canvas')).toHaveCount(0);
  await page.getByRole('button', { name: /架空の設備投資制限制.*架空の個人採決で賛成/ }).click();
  await expect(page.locator('.evidence-detail')).toContainText('架空の個人採決で賛成');
  await expect(page.locator('.source-panel')).toContainText('fixture:action-a-vote');
  await expect(page.locator('.policy-metrics')).not.toContainText('3.00');
});
