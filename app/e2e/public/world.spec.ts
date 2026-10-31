import { expect, test } from '@playwright/test';
import { watchPage } from './helpers';

test.describe('/world（世界のGDP比較）', () => {
  test('グラフ・表・title・データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/world');
    await expect(page).toHaveTitle(/世界のGDP比較/);
    await expect(page.getByRole('heading', { level: 1, name: '日本の経済は、世界と比べてどうですか？' })).toBeVisible();
    const chart = page.locator('section[aria-labelledby="world-chart-heading"] .world-chart-wrap svg[role="img"]');
    await expect(chart).toBeVisible();
    expect(await chart.locator('path, polyline').count()).toBeGreaterThan(0);
    expect(await page.locator('.world-table tbody tr').count()).toBeGreaterThan(0);
    expect(watch.dataUrls.some(url => url.endsWith('/distribution/world-gdp.json'))).toBe(true);
    await expect(page.getByRole('heading', { level: 3, name: /原因の軸の結論/ })).toBeVisible();
    watch.expectClean();
  });

  test('指標・期間・国の切り替えでグラフの見出しとURLが変わる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/world');
    const heading = page.locator('#world-chart-heading');
    // 既定は名目ではなく、物価と為替を除いた一人あたりGDP（購買力平価）の初期年＝100（国どうしを同じ条件で比べる）。
    await expect(heading).toContainText('一人あたりGDP');

    const metrics = page.getByRole('group', { name: '見る指標' });
    await metrics.getByRole('button', { name: '実質成長率（年ごと）' }).click();
    await expect(heading).toContainText('実質成長率');
    await expect(page).toHaveURL(/metric=growth/);
    await metrics.getByRole('button', { name: '名目GDP' }).click();
    await expect(heading).toContainText('名目GDP');
    await expect(page).toHaveURL(/metric=nominal/);

    const period2000 = page.getByRole('group', { name: '見る期間' }).getByRole('button', { name: '2000年〜' });
    await period2000.click();
    await expect(period2000).toHaveAttribute('aria-pressed', 'true');
    await expect(page).toHaveURL(/period=2000/);

    const chart = page.locator('section[aria-labelledby="world-chart-heading"] .world-chart-wrap svg[role="img"]');
    await expect(chart).toBeVisible();
    const lines = await chart.locator('path').count();
    // 国の選択は折りたたみの中にある。開いてから触る。
    await page.locator('.world-countries summary').click();
    const countries = page.locator('.world-country-list input[type="checkbox"]:not([disabled])');
    await countries.first().uncheck();
    await expect(page).toHaveURL(/hide=[A-Z]{3}/);
    await expect.poll(() => chart.locator('path').count()).toBeLessThan(lines);

    await page.getByRole('button', { name: /だけ$/ }).click();
    await expect(page).toHaveURL(/hide=/);
    await page.getByRole('button', { name: 'すべて表示' }).click();
    await expect(page).not.toHaveURL(/hide=/);
    watch.expectClean();
  });

  test('URLを直接開くと指標・期間が復元され、グラフにキー操作で触れる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/world?metric=ppp&period=2010');
    await expect(page.locator('#world-chart-heading')).toContainText('一人あたりGDP');
    await expect(page.getByRole('group', { name: '見る期間' }).getByRole('button', { name: '2010年〜' })).toHaveAttribute('aria-pressed', 'true');
    const chart = page.locator('section[aria-labelledby="world-chart-heading"] .world-chart-wrap svg[role="img"]');
    await expect(chart).toBeVisible();
    const readout = page.locator('section[aria-labelledby="world-chart-heading"] .m-line-readout');
    const before = await readout.innerText();
    await chart.focus();
    await page.keyboard.press('ArrowLeft');
    // キー操作で注目の年が切り替わり、読み上げ欄の文と案内が変わる（キー操作が効かなければここで落ちる）。
    await expect.poll(() => readout.innerText()).not.toBe(before);
    await expect(readout).toContainText('指を離すと最新の値に戻ります');
    watch.expectClean();
  });
});
