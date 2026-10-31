import { expect, test } from '@playwright/test';
import { leadingNumber, watchPage } from './helpers';

test.describe('/ranking（法律ランキング）', () => {
  test('一覧・件数・title・データ応答が正しい', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking');
    await expect(page).toHaveTitle(/法律・政策ランキング/);
    await expect(page.getByRole('heading', { level: 1, name: '法律と政策ごとの損失と便益' })).toBeVisible();
    await expect(page.getByRole('region', { name: '法律と政策の一覧' })).toBeVisible();
    const rows = page.locator('.laws-list > li');
    await expect(rows.first()).toBeVisible();
    expect(leadingNumber(await page.locator('.laws-count').textContent())).toBeGreaterThan(0);
    // 検証を通った確かな額が無い間は、棒の代わりに空状態の説明を出す。確かな額が戻れば棒が出る。
    const top = page.getByRole('region', { name: '額の大きい順' });
    await expect(top.locator('svg, [role="img"], ol, ul, .empty-state').first()).toBeVisible();
    await expect(top.getByText('確かな額がまだ無いため、額の大きい順の棒は出していません。', { exact: false })).toBeVisible();
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

    await page.getByRole('group', { name: '向きで絞る' }).getByRole('button', { name: '額が出た（参考を含む）' }).click();
    await expect(page).toHaveURL(/side=amount/);
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
  test('共有額の参考：既定では経済全体の分を畳み、押すと出る。1本ごとの額は出さず、合計の一部として見せる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking');
    const fold = page.locator('.laws-fold', { hasText: '経済全体の共有額の参考が付いた法律' });
    await expect(fold).toBeVisible();
    await expect(fold).toContainText('490本は畳んでいます');
    const sharedRows = page.locator('.laws-row.is-shared');
    await expect(sharedRows.first()).toBeVisible();
    await expect(sharedRows.first().locator('.laws-row-amount')).toContainText('共有額の参考');
    await expect(sharedRows.first().locator('.laws-row-amount')).toContainText('0〜');
    await expect(sharedRows.first().getByRole('note', { name: '共有額の参考値の注意' })).toContainText('この法律だけの効果ではない');
    await fold.getByRole('button', { name: '経済全体の共有額も表示' }).click();
    await expect(page.locator('.laws-fold', { hasText: '経済全体（産業コード _T）' })).toContainText('経済全体（産業コード _T）の共有額も並べています');
    watch.expectClean();
  });

  test('共有額の参考で絞ると全行に注意が付き、行を開くと根拠カード（使った前提）が出る。降格の印とは別', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking?side=shared');
    await expect(page.getByRole('group', { name: '向きで絞る' }).getByRole('button', { name: '共有額の参考' })).toHaveAttribute('aria-pressed', 'true');
    const rows = page.locator('.laws-row.is-shared');
    await expect(rows.first()).toBeVisible();
    expect(await page.locator('.laws-list > li').count()).toBe(await rows.count());
    await expect(page.getByText('検証で降格')).toHaveCount(0);
    const head = rows.first().locator('.laws-row-head');
    const detailResponse = page.waitForResponse(r => r.url().includes('/distribution/laws-detail/'));
    await head.click();
    expect((await detailResponse).ok()).toBe(true);
    const basis = rows.first().getByRole('region', { name: '根拠カード（使った前提）' });
    await expect(basis).toContainText('使った前提');
    await expect(basis).toContainText('OECD 表6');
    await expect(rows.first().locator('.laws-formula')).toHaveCount(0);
    watch.expectClean();
  });
});
