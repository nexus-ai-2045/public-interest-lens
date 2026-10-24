import { expect, test } from '@playwright/test';
import { leadingNumber, watchPage } from './helpers';

test.describe('/ranking（法律ランキング）', () => {
  test('一覧・件数・title・データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking');
    await expect(page).toHaveTitle(/法律・政策ランキング/);
    await expect(page.getByRole('heading', { level: 2, name: '法律と政策ごとの損失と便益' })).toBeVisible();
    await expect(page.getByRole('region', { name: '法律と政策の一覧' })).toBeVisible();
    const rows = page.locator('.laws-list > li');
    await expect(rows.first()).toBeVisible();
    expect(leadingNumber(await page.locator('.laws-count').textContent())).toBeGreaterThan(0);
    await expect(page.getByRole('region', { name: '額の大きい順' }).locator('svg, [role="img"], ol, ul').first()).toBeVisible();
    expect(watch.dataUrls.some(url => url.endsWith('/distribution/laws.json'))).toBe(true);
    watch.expectClean();
  });

  test('検索と向きの絞り込みで件数が変わり、外すと戻る', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking');
    const count = page.locator('.laws-count');
    await expect(page.locator('.laws-list > li').first()).toBeVisible();
    const total = leadingNumber(await count.textContent());

    // 行の名前は「何をする法律（正式名：…）」。検索には正式名を使う（一文の無い行は正式名だけ）。
    const firstName = page.locator('.laws-row-title').first();
    const formal = firstName.locator('.law-name-formal');
    const firstTitle = (await formal.count() ? (await formal.textContent())!.replace(/^AI要約（正式名：|）$/g, '') : (await firstName.locator('.law-name-plain').textContent())!).trim();
    await page.getByRole('searchbox', { name: '法律の名前・番号・分野で探す' }).fill(firstTitle);
    await expect.poll(async () => leadingNumber(await count.textContent())).toBeLessThan(total);
    expect(leadingNumber(await count.textContent())).toBeGreaterThan(0);
    await expect(page).toHaveURL(/[?&]q=/);

    await page.getByRole('searchbox', { name: '法律の名前・番号・分野で探す' }).fill('存在しない語句zzzqqq');
    await expect(page.getByText('条件に合う法律がありません。')).toBeVisible();
    expect(leadingNumber(await count.textContent())).toBe(0);

    await page.getByRole('button', { name: '絞り込みを外す' }).click();
    await expect.poll(async () => leadingNumber(await count.textContent())).toBe(total);

    await page.getByRole('group', { name: '向きで絞る' }).getByRole('button', { name: '額なし' }).click();
    await expect(page).toHaveURL(/side=none/);
    await expect.poll(async () => leadingNumber(await count.textContent())).not.toBe(total);
    watch.expectClean();
  });

  test('行を開くと詳細（laws-detail）を読み込んで表示する', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking');
    const head = page.locator('.laws-row-head').first();
    await expect(head).toHaveAttribute('aria-expanded', 'false');
    const detailResponse = page.waitForResponse(r => r.url().includes('/distribution/laws-detail/'));
    await head.click();
    expect((await detailResponse).ok()).toBe(true);
    await expect(head).toHaveAttribute('aria-expanded', 'true');
    const detail = page.locator('.laws-detail').first();
    await expect(detail.getByRole('heading', { name: /計算の流れ/ })).toBeVisible();
    await expect(page.getByText('詳細を読み込めませんでした。')).toHaveCount(0);
    await head.click();
    await expect(head).toHaveAttribute('aria-expanded', 'false');
    watch.expectClean();
  });
});
