import { expect, test } from '@playwright/test';
import { leadingNumber, watchPage } from './helpers';


const EMPTY = '確かな額がまだ無いため、議員別の額は出していません。';
const allMembers = (page: import('@playwright/test').Page) => page.getByRole('region', { name: '全議員' });

// 検証を通った配分の法律が無い間（降格の帰結）、議員別の額は0人。空白にせず理由を示し、全議員の一覧は残す。
// 確かな額が戻ったら、議員ランキング（ol.members-list）の検査をこのファイルの履歴から戻す。
test.describe('/members（議員ランキング：配分0）', () => {
  test('空状態の理由を出し、議員別の額の並びは出さない', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    await expect(page).toHaveTitle(/議員・実名/);
    await expect(page.getByRole('heading', { level: 1, name: 'この人が失わせた額・生んだ額' })).toBeVisible();
    const note = page.getByRole('note').filter({ hasText: EMPTY });
    await expect(note).toBeVisible();
    await expect(note).toContainText('配分に使える法律が検証を通っていません');
    await expect(page.locator('ol.members-list')).toHaveCount(0);
    await expect(page.locator('.tone-hero')).toHaveCount(0);
    expect(watch.dataUrls.some(url => url.endsWith('/distribution/members.json'))).toBe(true);
    watch.expectClean();
  });

  test('全議員の一覧（3,001人）は残り、名前で探すと人数が減る', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    const all = allMembers(page);
    const status = all.getByRole('status').filter({ hasText: '人' }).first();
    await expect(all.locator('ol.all-members-list > li').first()).toBeVisible();
    await expect(all.locator('.all-members-lead')).toContainText('公開しているのは3,001人');
    const total = leadingNumber(await status.textContent());
    expect(total).toBe(3001);
    const name = (await all.locator('.all-member-name').first().evaluate(el => el.childNodes[0].textContent ?? '')).trim();
    await all.getByRole('searchbox', { name: /名前・会派・選挙区で探す/ }).fill(name);
    await expect.poll(async () => leadingNumber(await status.textContent())).toBeLessThan(total); // 絞り込みが効かなければ人数は変わらない
    expect(leadingNumber(await status.textContent())).toBeGreaterThan(0);
    watch.expectClean();
  });
});

test.describe('/members 政党ごとの比較', () => {
  test('切り替えると政党ごとの比較も同じ理由で空状態になり、URL に tab=party が入る', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/members');
    await page.getByRole('button', { name: '政党ごとの比較' }).click();
    await expect(page).toHaveURL(/tab=party/);
    await expect(page.getByText('政党ごとの比較は、議員別の額の合計です。確かな額がまだ無いため出していません', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: '議員ランキング' }).click();
    await expect(page).not.toHaveURL(/tab=party/);
    await expect(page.getByRole('note').filter({ hasText: EMPTY })).toBeVisible();
    watch.expectClean();
  });
  test('公開サイトにテスト用の仮データ画面へのリンクが無く、/demo は開けない', async ({ page }) => {
    await page.goto('/members');
    await expect(page.locator('a[href^="/demo"]')).toHaveCount(0);
    await page.goto('/demo');
    await expect(page.getByRole('heading', { level: 1, name: 'この機能は公開版に含まれていません' })).toBeVisible();
  });
});
