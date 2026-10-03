import { test, expect } from '@playwright/test';

test('旧リンクを短い行動IDへ移行し、根拠と共有条件を復元する', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/people/fiction-a');
  await page.getByRole('tab', { name: '根拠', exact: true }).click();
  await page.locator('[data-evidence-id="e-impact-e"]').getByRole('button', { name: 'この根拠を選択' }).click();
  await expect(page).toHaveURL(/\/actions\/fiction-a-bill\?/);
  await expect(page).toHaveURL(/evidence=e-impact-e/);
  expect(page.url()).not.toContain('action=%5B');
  expect(page.url()).not.toContain('economy=70');
  await page.reload();
  await expect(page.locator('[data-evidence-id="e-impact-e"]')).toHaveClass(/selected-source/);
  await page.getByRole('button', { name: 'この結果を共有', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'リンクをコピー' })).toBeVisible();
  const shared = await page.evaluate(() => navigator.clipboard.readText());
  expect(shared).toContain('version=');
  expect(shared).toContain('evidence=e-impact-e');
  await page.goto(shared);
  await page.getByRole('button', { name: '全履歴', exact: true }).click();
  await expect(page).toHaveURL(/version=/);
});

test('人物ページの空検索は例外を出さず、履歴と再読込で条件を戻す', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/people/fiction-a');
  await page.getByRole('searchbox', { name: '人物名で検索' }).fill('存在しない人物');
  await expect(page).toHaveURL(/\/ranking$/);
  await expect(page.locator('tbody tr')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('searchbox', { name: '人物名で検索' })).toHaveValue('存在しない人物');
  await page.getByRole('searchbox', { name: '人物名で検索' }).fill('');
  await expect(page.locator('tbody tr')).toHaveCount(4);
  expect(errors).toEqual([]);
});

test('短い既定URLと、存在しない版・行動の停止を維持する', async ({ page }) => {
  await page.goto('/ranking');
  await expect(page).toHaveURL(/\/ranking$/);
  await page.getByRole('button', { name: '貢献', exact: true }).click();
  await expect(page).toHaveURL(/\/ranking\?view=benefit$/);
  await page.goto('/actions/missing');
  await expect(page.getByRole('alert')).toContainText('見つかりません');
  await expect(page.locator('tbody tr')).toHaveCount(0);
  await page.goto('/ranking?version=unknown');
  await expect(page.getByRole('alert')).toContainText('評価版は利用できません');
});
