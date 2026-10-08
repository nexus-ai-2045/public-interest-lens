import { test, expect } from '@playwright/test';

const points = Array.from({ length: 46 }, (_, i) => ({ year: 1980 + i, value: 100000000000000 + i * 1000000000000 }));
const snapshot = { schemaVersion: 'economic-series/v1', observedAt: '2026-10-07T00:00:00Z', provider: '人工試験資料', country: 'JPN', series: [{ id: 'real_gdp', label: '実質GDP', unit: '円・一定価格', basis: '人工の単一系列です。', sourceUrl: 'https://api.worldbank.org/v2/', points }, { id: 'nominal_gdp', label: '名目GDP', unit: '円・当年価格', basis: '人工の単一系列です。', sourceUrl: 'https://api.worldbank.org/v2/', points }], unavailable: ['労働生産性'], note: '推移だけで原因を判定しません。' };
for (const width of [390, 1440]) {
  test(`長期推移の40年・30年・4年・任意期間と復元 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await page.route('**/__local__/economy', route => route.fulfill({ json: snapshot }));
    await page.goto('/');
    await expect(page).toHaveTitle('日本の長期推移｜国賊／国士ランキング');
    await expect(page.getByRole('heading', { name: '実質GDP：1986〜2025年' })).toBeVisible();
    await page.getByLabel('見る期間').selectOption('30');
    await expect(page.getByRole('heading', { name: '実質GDP：1996〜2025年' })).toBeVisible();
    await page.getByLabel('見る期間').selectOption('4');
    await expect(page.getByRole('heading', { name: '実質GDP：2022〜2025年' })).toBeVisible();
    await page.getByLabel('見る指標').selectOption('nominal_gdp');
    await page.reload();
    await expect(page.getByRole('heading', { name: '名目GDP：2022〜2025年' })).toBeVisible();
    await page.getByLabel('見る期間').selectOption('custom');
    await page.getByLabel('開始年').fill('2000');
    await page.getByLabel('終了年').fill('2010');
    await expect(page.getByRole('heading', { name: '名目GDP：2000〜2010年' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
test('未知の指標と取得失敗を架空値へ置き換えません', async ({ page }) => {
  await page.route('**/__local__/economy', route => route.fulfill({ json: snapshot }));
  await page.goto('/history?metric=unknown');
  await expect(page.getByRole('alert')).toContainText('指定された指標は収録されていません');
  await page.route('**/__local__/economy', route => route.fulfill({ status: 404 }));
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('長期統計を読み込めませんでした');
});
