import { expect, test } from '@playwright/test';
import { leadingNumber, watchPage } from './helpers';

const slider = (page: import('@playwright/test').Page, name: RegExp) => page.getByRole('slider', { name });

test.describe('/members（議員ランキング）', () => {
  test('一覧・title・データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    await expect(page).toHaveTitle(/議員・実名/);
    await expect(page.getByRole('heading', { level: 2, name: 'この人が失わせた額・生んだ額' })).toBeVisible();
    const cards = page.locator('ol.members-list > li');
    await expect(cards.first()).toBeVisible();
    expect(leadingNumber(await page.getByRole('status').filter({ hasText: '人を表示' }).textContent())).toBeGreaterThan(0);
    await expect(page.getByRole('region', { name: '見え方のつまみ' })).toBeVisible();
    expect(watch.dataUrls.some(url => url.endsWith('/distribution/members.json'))).toBe(true);
    watch.expectClean();
  });

  test('つまみを動かすと順位の額とURLのクエリが変わり、初期値に戻せる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    const summaries = page.locator('ol.members-list > li summary');
    await expect(summaries.first()).toBeVisible();
    const before = (await summaries.allInnerTexts()).join('|');

    await slider(page, /提出者/).fill('0');
    await expect(page).toHaveURL(/[?&]p=0(&|$)/);
    await expect.poll(async () => (await summaries.allInnerTexts()).join('|')).not.toBe(before);

    await page.getByRole('combobox', { name: /衆議院の分/ }).selectOption('voters');
    await expect(page).toHaveURL(/house=voters/);
    await page.getByRole('checkbox', { name: '委員長も拒否権者にする' }).check();
    await expect(page).toHaveURL(/chair=1/);

    await page.getByRole('button', { name: '初期値に戻す' }).click();
    await expect(page).not.toHaveURL(/[?&](p|house|chair|r)=/);
    await expect.poll(async () => (await summaries.allInnerTexts()).join('|')).toBe(before);
    watch.expectClean();
  });

  test('URLを直接開くとつまみの状態が復元される', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members?p=40&house=voters&chair=1&r=70');
    await expect(page.locator('ol.members-list > li').first()).toBeVisible();
    await expect(slider(page, /提出者/)).toHaveValue('40');
    await expect(slider(page, /帰属率/)).toHaveValue('70');
    await expect(page.getByRole('combobox', { name: /衆議院の分/ })).toHaveValue('voters');
    await expect(page.getByRole('checkbox', { name: '委員長も拒否権者にする' })).toBeChecked();
    await expect(page.getByRole('button', { name: '初期値に戻す' })).toBeVisible();
    watch.expectClean();
  });

  test('名前で探すと人数が減る', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    const status = page.getByRole('status').filter({ hasText: '人を表示' });
    await expect(page.locator('ol.members-list > li').first()).toBeVisible();
    const total = leadingNumber(await status.textContent());
    const name = (await page.locator('.member-name').first().textContent())!.trim();
    await page.getByRole('searchbox', { name: '名前で探す' }).fill(name);
    await expect.poll(async () => leadingNumber(await status.textContent())).toBeLessThan(total); // 絞り込みが効かなければ人数は変わらない
    expect(leadingNumber(await status.textContent())).toBeGreaterThan(0);
    await expect(page.locator('.member-name').first()).toHaveText(name);
    watch.expectClean();
  });
});
