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
    // 振り分けの当て直し中（app/src/interim-display.ts）は、額の順位（棒）を止め、注記を出す。切り替えを切れば元の棒・空状態に戻る。
    await expect(page.getByRole('note', { name: '振り分けの当て直し中' })).toContainText('額の順位を止め');
    const top = page.getByRole('region', { name: '額の順位（一時停止中）' });
    await expect(top.getByRole('heading', { name: '額の順位は一時停止中です' })).toBeVisible();
    await expect(top.locator('svg')).toHaveCount(0);
    await expect(page.getByRole('region', { name: /損失の大きい順|便益の大きい順|額の大きい順/ })).toHaveCount(0);
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

  test('並べ替えは URL で保たれる：初回の指定を上書きせず、額の大きい順も共有・再読み込みで残る', async ({ page }) => {
    const watch = watchPage(page);
    const sort = page.getByRole('combobox', { name: '並べ替え' });
    // 国賊（既定の向き）でも、URL で便益順を指定して開いたらそのまま。
    await page.goto('/ranking?sort=benefit');
    await expect(page.locator('.laws-list > li').first()).toBeVisible();
    await expect(sort).toHaveValue('benefit');
    await expect(page).toHaveURL(/[?&]sort=benefit/);
    // 額の大きい順を選ぶと URL に明示され、再読み込みしても向き別の並びに戻らない。
    await sort.selectOption('amount');
    await expect(page).toHaveURL(/[?&]sort=amount/);
    await page.reload();
    await expect(page.locator('.laws-list > li').first()).toBeVisible();
    await expect(sort).toHaveValue('amount');
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
  test('振り分けの当て直し中は、参考の額と共有額の参考（産業ごとの分も）を既定で畳み、押すと出る。1本ごとの額は出さず、合計の一部として見せる', async ({ page }) => {
    const watch = watchPage(page);
    await page.goto('/ranking');
    await expect(page.locator('.laws-list > li').first()).toBeVisible();
    // 本数は配布データ（laws.json）から、画面と同じ数え方で数える。試験に数字を写して持たない（データが変わると古くなる）。
    type Row = { step: string; shared?: { whole?: boolean } | null };
    const catalog = await (await page.request.get('/distribution/laws.json')).json() as { laws: Row[]; policies: Row[] };
    const rows = [...catalog.laws, ...catalog.policies];
    const reference = rows.filter(row => row.step === 'amounted').length;
    const shared = rows.filter(row => row.shared && row.step !== 'amounted').length;
    expect(reference).toBeGreaterThan(0);
    expect(shared).toBeGreaterThan(0);
    const refFold = page.locator('.laws-fold', { hasText: '参考の額が付いた法律' });
    await expect(refFold).toContainText(`振り分けの当て直し中のため、参考の額が付いた法律${reference.toLocaleString('ja-JP')}本は畳んでいます`);
    const fold = page.locator('.laws-fold', { hasText: '共有額の参考が付いた法律' });
    await expect(fold).toContainText(`振り分けの当て直し中のため、共有額の参考が付いた法律${shared.toLocaleString('ja-JP')}本は畳んでいます`);
    await expect(page.locator('.laws-row.is-shared')).toHaveCount(0);
    await expect(page.locator('.laws-row.has-amount')).toHaveCount(0);
    await fold.getByRole('button', { name: '共有額の参考も表示' }).click();
    const sharedRows = page.locator('.laws-row.is-shared');
    await expect(sharedRows.first()).toBeVisible();
    await expect(sharedRows.first().locator('.laws-row-amount')).toContainText('共有額の参考');
    await expect(sharedRows.first().locator('.laws-row-amount')).toContainText('0〜');
    await expect(sharedRows.first().getByRole('note', { name: '共有額の参考値の注意' })).toContainText('この法律だけの効果ではない');
    await expect(page.locator('.laws-fold', { hasText: '共有額の参考も並べています' })).toBeVisible();
    await refFold.getByRole('button', { name: '参考の額も表示' }).click();
    await expect(page.locator('.laws-row.has-amount').first()).toBeVisible();
    watch.expectClean();
  });

  test('抜き取り2回目で不合格のまま訂正待ちの額は参考に下げ、理由を出す', async ({ page }) => {
    // 個別の額の3本（衆法-189-20・閣法-193-61・閣法-196-2）は訂正表で値が直り、標本2を判定し直すと合格になった（衆法-189-20 は評価対象外として額の行から外れる）。
    // 衆法-201-10 は訂正候補を退けたので、標本2の判定では訂正待ちのまま参考に下げる
    const watch = watchPage(page);
    await page.goto('/ranking#%E8%A1%86%E6%B3%95-201-10');
    const row = page.locator('[id="law-衆法-201-10"]');
    await expect(row).toBeVisible();
    await expect(row.locator('.laws-row-amount')).toContainText('参考値（検証で降格）');
    await expect(row.getByRole('note', { name: '参考値の理由と根拠' })).toContainText('抜き取り2回目で不合格');
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
