import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/__local__/**', route => route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"local_records_unavailable"}' }));
});

for (const contentType of ['text/html; charset=utf-8', 'application/octet-stream']) {
  test(`統計のローカル入口がSPA本文なら公開配布を読む ${contentType}`, async ({ page }) => {
    await page.route('**/__local__/economy*', route => route.fulfill({ status: 200, contentType, body: '<!doctype html><html><body><div id="root"></div></body></html>' }));
    await page.goto('/history?years=40');
    await expect(page.getByRole('status')).toContainText('公開配布版です');
    await expect(page.getByRole('img', { name: /実質GDP.*年次推移/ })).toBeVisible();
  });
}

for (const body of ['{"schemaVersion":"broken"}', '{"error":"EditionMismatch"}', '<html><body>invalid JSON</body></html>']) {
  test(`ローカルJSONの不整合は公開版へ置き換えない ${body}`, async ({ page }) => {
    const publicRequests: string[] = [];
    page.on('request', request => { if (request.url().includes('/distribution/')) publicRequests.push(request.url()); });
    await page.route('**/__local__/economy*', route => route.fulfill({ status: 200, contentType: 'application/json', body }));
    await page.goto('/history?years=40');
    await expect(page.getByRole('alert')).toContainText('長期統計を読み込めませんでした');
    expect(publicRequests).toEqual([]);
  });
}

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
    await expect(page.getByRole('heading', { name: /判定結果：影響段階 1（限定的）/ })).toBeVisible();
    await expect(page.getByText('impact-rule-v1').first()).toBeVisible();
    await expect(page.getByText('+1点（貢献）')).toHaveCount(0);
    await expect(page.getByText('人物照合の受領書が無いため保留').first()).toBeVisible();
    await expect(page.getByText('−3.0pt')).toBeVisible();
    await expect(page.getByText('採点済みではありません')).toHaveCount(0);
    await page.getByText('配布データ作成時点の保留理由').click();
    await expect(page.getByText('GDP損失額も置かない')).toBeVisible();
    await page.goto('/actors');
    await expect(page.getByRole('heading', { name: '竹中平蔵', level: 2 })).toHaveCount(0);
    await expect(page.getByText('竹中平蔵').first()).toBeVisible();
    await expect(page.getByText('人物ごとの点数は上の「判定結果」にまとめています').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: /影響段階 1（限定的）/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('未知の統計版は現在版へ置き換えません', async ({ page }) => {
  await page.route('**/__local__/economy*', route => route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>SPA</body></html>' }));
  await page.goto(`/history?edition=${'0'.repeat(64)}`);
  await expect(page.getByRole('alert')).toContainText('長期統計を読み込めませんでした');
  await expect(page.getByText('公開配布版です')).toHaveCount(0);
});
