import { test, expect } from '@playwright/test';

test('壊れた資料で直前の正常な取得結果を失わない', async ({ page }) => {
  await page.goto('/');
  const localData = { schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24', coverage: { scope: '保持される取得範囲', assessedPeople: 0, sourceStatus: 'pages_captured', sourceRecords: 1 }, people: [], policies: [], involvements: [], evidence: [], held: [{ id: 'ndl-1', reason: '発言本文未取得', sourceUrl: 'https://kokkai.ndl.go.jp/api/speech/metadata', observedAt: '2026-09-29T00:00:00Z', sha256: 'a'.repeat(64) }] };
  const input = page.getByLabel('ローカル評価データJSONを開く');
  await input.setInputFiles({ name: 'good.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(localData)) });
  await expect(page.locator('.inspection-result')).toContainText('保持される取得範囲');
  await expect(page.locator('.inspection-result')).toContainText('2026-09-29T00:00:00Z');
  await input.setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{broken') });
  await expect(page.getByRole('alert')).toContainText('読み取り失敗');
  await expect(page.locator('.inspection-result')).toContainText('保持される取得範囲');
  await expect(page.locator('tbody tr').first()).toContainText('架空議員あおい');
});

test('選択した根拠と行動をURLから復元できる', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /架空の設備投資制限制.*架空の個人採決で賛成/ }).click();
  await page.getByRole('tab', { name: '根拠', exact: true }).click();
  await expect(page.locator('.source-panel')).toContainText('fixture:action-a-vote');
  await page.reload();
  await expect(page.getByRole('tab', { name: '根拠', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.source-panel')).toContainText('fixture:action-a-vote');
  await expect(page.locator('canvas')).toHaveCount(0);
});

test('暗い国賊・白い国士をPCと小画面で表示し保存する', async ({ page }, testInfo) => {
  const errors: string[] = [];
  const external: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4179')) external.push(request.url()); });
  for (const direction of ['harm', 'benefit']) {
    for (const [width, height] of [[1536, 1024], [1440, 1000], [390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto('/?domain=economy&direction=' + direction + '&period=4');
      await expect(page.getByRole('heading', { name: direction === 'harm' ? '国賊ランキング' : '国士ランキング', exact: true, level: 1 })).toBeVisible();
      await expect(page.getByRole('region', { name: '政策と行動のつながり' })).toBeVisible();
      const background = await page.locator('.app-shell').evaluate(element => getComputedStyle(element).backgroundColor);
      expect(background).toBe(direction === 'harm' ? 'rgb(21, 21, 21)' : 'rgb(255, 255, 255)');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('app-' + direction + '-' + width + '.png'), fullPage: width === 390 });
    }
  }
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});
