import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';

// 人工記録で保存版の操作契約だけを検証します。実在人物の採点成功ではありません。
const canonical = (v: unknown): string => Array.isArray(v) ? `[${v.map(canonical).join(',')}]` : v && typeof v === 'object' ? `{${Object.entries(v).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, x]) => `${JSON.stringify(k)}:${canonical(x)}`).join(',')}}` : JSON.stringify(v);
function fixture(direction: 'harm' | 'benefit') {
  const people = [{ id: 'e2e-person', name: '操作試験用の人工人物' }];
  const body = {
    schemaVersion: 'evidence-release/v1', engineHash: 'a'.repeat(64), publicationStatus: 'requires_human_review',
    input: { materialRefs: [], evidenceEvaluation: { schemaVersion: 'evidence-evaluation/v1', mode: 'real',
      options: { domain: 'economy', direction, period: 4, asOf: '2026-10-02', weights: { economy: 70, technology: 30 } },
      people, materials: [], actions: [], assessments: [] } },
    result: { mode: 'real', publicationStatus: 'requires_human_review',
      rows: people.map(person => ({ person, score: null, rank: null, eligibleCount: 0, heldCount: 0, contributions: [] })),
      held: [], coverage: { inputActions: 0, assessedActions: 0, readableMaterials: 0 } },
  };
  return { ...body, releaseId: createHash('sha256').update(canonical(body)).digest('hex') };
}
for (const width of [390, 1440]) for (const direction of ['harm', 'benefit'] as const) {
  test(`非公開保存版の入口・復元・保持 ${direction} ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto('/?dataset=real&release=' + 'b'.repeat(64));
    await expect(page.getByRole('heading', { name: '実評価データ未読込', exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: '実評価版の読み込み案内' })).toContainText('該当版のファイルを開いてください');
    await expect(page.getByText('架空比較人物', { exact: false })).toHaveCount(0);
    const release = fixture(direction);
    await page.locator('input[type=file]').setInputFiles({ name: 'e2e-artificial-release.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(release)) });
    await expect(page.getByRole('heading', { name: direction === 'harm' ? '国賊ランキング' : '国士ランキング', exact: true })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`release=${release.releaseId}`));
    await expect(page.getByText('評価可能 0人', { exact: true })).toBeVisible();
    const person = page.getByRole('button', { name: /操作試験用の人工人物/ });
    await person.focus(); await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/realPerson=e2e-person/);
    await expect(page.getByRole('heading', { name: '操作試験用の人工人物', exact: true })).toBeVisible();
    await page.locator('input[type=file]').setInputFiles({ name: 'broken.json', mimeType: 'application/json', buffer: Buffer.from('{}') });
    await expect(page.getByRole('alert')).toContainText('直前の正常版は保持');
    await expect(page.getByRole('heading', { name: '操作試験用の人工人物', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`real-${direction}-${width}.png`), fullPage: true });
    await page.goBack();
    await expect(page).not.toHaveURL(/realPerson=/);
    await page.reload();
    await expect(page.getByRole('heading', { name: '実評価データ未読込', exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: '実評価版の読み込み案内' })).toContainText('該当版のファイルを開いてください');
    await page.getByRole('button', { name: '架空デモへ切り替える' }).click();
    await expect(page.getByText('全人物・政策・資料が架空です。', { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}
