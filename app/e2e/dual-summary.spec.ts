import { test, expect } from '@playwright/test';
import { rankingDataset } from '../src/ranking-data';
import { actionKey } from '../src/ranking';

test('両面評価を方向切替に関係なく同じ条件で示す', async ({ page }) => {
  await page.goto('/?domain=economy&direction=harm&period=4');
  const summary = page.getByRole('region', { name: '両面評価' });
  await expect(summary).toContainText('貢献点');
  await expect(summary).toContainText('悪影響点');
  await expect(summary).toContainText('3.00');
  await expect(summary).toContainText('悪影響の記録あり・貢献は未評価');
  await expect(page.locator('tbody tr').first()).toContainText('悪影響の記録あり・貢献は未評価');
  await page.getByRole('button', { name: '貢献', exact: true }).click();
  await expect(summary).toContainText('2.00');
  await expect(summary).toContainText('貢献の記録あり・悪影響は未評価');
  await expect(page.locator('.policy-flow')).toContainText('架空の新規参入支援策');
  await expect(page.locator('.policy-flow')).not.toContainText('架空の設備投資制限制');
});

test('条件内ツリーが空でも全履歴へ移動しURL復元できる', async ({ page }) => {
  await page.goto('/?domain=economy&direction=harm&period=4');
  await page.getByRole('button', { name: '架空議員べに', exact: true }).click();
  await expect(page.getByText('現在の条件に合う行動がありません。', { exact: true })).toBeVisible();
  await expect(page.locator('.policy-flow')).toHaveCount(0);
  await page.getByRole('button', { name: '全履歴を見る', exact: true }).click();
  await expect(page).toHaveURL(/history=all/);
  await expect(page.locator('.policy-flow')).toContainText('架空の新規参入支援策');
  await expect(page.locator('.policy-flow')).toContainText('現在の条件外');
  await page.reload();
  await expect(page.getByRole('button', { name: '全履歴', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '現在の条件', exact: true }).click();
  await expect(page.getByText('現在の条件に合う行動がありません。', { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.locator('.policy-flow')).toContainText('架空の新規参入支援策');
});

test('古い条件外行動リンクは全履歴で開き未知の行動は開かない', async ({ page }) => {
  const action = rankingDataset.involvements.find(item => item.personId === 'fiction-b')!;
  const params = new URLSearchParams({ domain: 'economy', direction: 'harm', period: '4', person: 'fiction-b', action: actionKey(action), tab: 'evidence' });
  await page.goto('/?' + params.toString());
  await expect(page.getByRole('button', { name: '全履歴', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.policy-flow')).toContainText('現在の条件外');
  await expect(page.locator('.source-panel')).toContainText('fixture:action-b');
  params.set('action', 'unknown-action');
  await page.goto('/?' + params.toString());
  await expect(page.getByRole('alert')).toContainText('指定された行動は見つかりません');
  await expect(page.getByRole('region', { name: '政策と行動のつながり' })).toHaveCount(0);
});

test('公約・準備中・全重み0は傾向を判定しない', async ({ page }) => {
  for (const search of ['?domain=fiscal', '?domain=economy&assessment=outlook', '?domain=overall&economy=0&technology=0']) {
    await page.goto('/' + search);
    const summary = page.getByRole('region', { name: '両面評価' });
    await expect(summary).toContainText('判断材料不足');
    await expect(summary.getByText('未評価', { exact: true })).toHaveCount(2);
    await expect(summary).not.toContainText('優勢');
  }
});

test('両テーマの要約とツリーをPC・スマホで確認する', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const direction of ['harm', 'benefit']) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto('/?domain=economy&direction=' + direction + '&period=4');
      await expect(page.getByRole('region', { name: '両面評価' })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('dual-' + direction + '-' + width + '.png'), fullPage: width === 390 });
    }
  }
  expect(errors).toEqual([]);
});
