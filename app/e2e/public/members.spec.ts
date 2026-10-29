import { expect, test } from '@playwright/test';
import { leadingNumber, watchPage } from './helpers';

const openBasis = (page: import('@playwright/test').Page) => page.getByText(/^根拠と計算の前提/).click();
const slider = (page: import('@playwright/test').Page, name: RegExp) => page.getByRole('slider', { name });

test.describe('/members（議員ランキング）', () => {
  test('一覧・title・データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    await expect(page).toHaveTitle(/議員・実名/);
    await expect(page.getByRole('heading', { level: 1, name: 'この人が失わせた額・生んだ額' })).toBeVisible();
    const cards = page.locator('ol.members-list > li');
    await expect(cards.first()).toBeVisible();
    expect(leadingNumber(await page.getByRole('status').filter({ hasText: '人を表示' }).textContent())).toBeGreaterThan(0);
    // 最初は順位・名前・所属政党・額だけ。理由（元になった法律・つまみ）は折りたたみの中。
    await expect(page.getByRole('region', { name: '見え方のつまみ' })).toBeHidden();
    await expect(page.locator('.member-party').first()).not.toBeEmpty();
    await expect(page.locator('ol.members-list > li summary .member-from')).toHaveCount(0);
    await openBasis(page);
    await expect(page.getByRole('region', { name: '見え方のつまみ' })).toBeVisible();
    expect(watch.dataUrls.some(url => url.endsWith('/distribution/members.json'))).toBe(true);
    watch.expectClean();
  });

  test('つまみを動かすと順位の額とURLのクエリが変わり、初期値に戻せる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    const summaries = page.locator('ol.members-list > li summary');
    await expect(summaries.first()).toBeVisible();
    await openBasis(page);
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

test.describe('/members 政党ごとの比較', () => {
  test('切り替えると所属政党ごとの表が出て、URL に tab=party が入る', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    await page.getByRole('button', { name: '政党ごとの比較' }).click();
    await expect(page).toHaveURL(/tab=party/);
    const table = page.getByRole('region', { name: '所属政党ごとの比較' }).locator('table');
    await expect(table.locator('tbody tr').first()).toBeVisible();
    expect(await table.locator('tbody tr').count()).toBeGreaterThan(3);
    await page.getByRole('button', { name: '議員ランキング' }).click();
    await expect(page).not.toHaveURL(/tab=party/);
    await expect(page.locator('ol.members-list > li').first()).toBeVisible();
    watch.expectClean();
  });
  test('公開サイトにテスト用の仮データ画面へのリンクが無く、/demo は開けない', async ({ page }) => {
    await page.goto('/members');
    await expect(page.locator('a[href^="/demo"]')).toHaveCount(0);
    await page.goto('/demo');
    await expect(page.getByRole('heading', { level: 1, name: 'この機能は公開版に含まれていません' })).toBeVisible();
  });
});
