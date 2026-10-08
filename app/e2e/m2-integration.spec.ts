import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const canonical = (v: unknown): string => Array.isArray(v) ? `[${v.map(canonical).join(',')}]` : v && typeof v === 'object' ? `{${Object.entries(v).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, x]) => `${JSON.stringify(k)}:${canonical(x)}`).join(',')}}` : JSON.stringify(v);
function fixture() {
  const people = [{ id: 'matched', name: '照合済みの人工記載名' }, { id: 'unresolved', name: '未照合の人工記載名' }];
  const body = { schemaVersion: 'evidence-release/v1', engineHash: 'a'.repeat(64), publicationStatus: 'requires_human_review',
    input: { materialRefs: [], evidenceEvaluation: { schemaVersion: 'evidence-evaluation/v1', mode: 'real', options: { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-10-03', weights: { economy: 70, technology: 30 } }, people, materials: [], actions: [], assessments: [] } },
    verification: { resolvedPersonIds: ['matched'] },
    result: { mode: 'real', publicationStatus: 'requires_human_review', rows: people.map(person => ({ person, score: null, rank: null, eligibleCount: 0, heldCount: 0, contributions: [] })), held: [], coverage: { inputActions: 0, assessedActions: 0, readableMaterials: 0 } } };
  return { ...body, releaseId: createHash('sha256').update(canonical(body)).digest('hex') };
}

test('ローカル保存版の自動読込・照合範囲・人物・同じ版の再読込', async ({ page }) => {
  const release = fixture();
  await page.route('**/__local__/evaluation**', r => r.fulfill({ json: release }));
  await page.goto('/evaluation');
  await expect(page.getByText('保存版の照合済み 1人', { exact: true })).toBeVisible();
  await expect(page.getByText('照合未確認 1人', { exact: true })).toBeVisible();
  await expect(page.getByText('評価可能 0人', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /未照合の人工記載名/ }).click();
  await expect(page.getByText('人物照合：未確認です。記載名だけで本人と認定しません。')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '未照合の人工記載名', exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(release.releaseId));
});

test('指定版がない・違う版が返る場合は自動置換しません', async ({ page }) => {
  await page.route('**/__local__/evaluation**', r => r.fulfill({ json: fixture() }));
  await page.goto('/evaluation?release=' + 'b'.repeat(64));
  await expect(page.getByRole('alert')).toContainText('実評価版を読み取れませんでした');
  await expect(page.getByRole('heading', { name: '実評価データ未読込', exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp('b'.repeat(64)));
  await expect(page.getByText('未照合の人工記載名', { exact: true })).toHaveCount(0);
});

test('保存済み実評価の引用・保留・公式リンクをPCとスマホで確認します', async ({ page }, info) => {
  test.skip(!process.env.REAL_RELEASE_SMOKE_INPUT, '非公開保存版を指定した場合に実行します');
  const release = JSON.parse(await readFile(process.env.REAL_RELEASE_SMOKE_INPUT!, 'utf8'));
  const catalog = process.env.POLICY_CATALOG_SMOKE_INPUT ? JSON.parse(await readFile(process.env.POLICY_CATALOG_SMOKE_INPUT, 'utf8')) : null;
  if (catalog) await page.route('**/__local__/policy-context**', r => r.fulfill({ json: catalog }));
  const matched = release.verification.resolvedPersonIds[0] ?? release.input.evidenceEvaluation.people[0]?.id;
  test.skip(!matched, '人物が未収録の版は人物詳細を確認できません');
  const person = release.input.evidenceEvaluation.people.find((p: { id: string }) => p.id === matched);
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await page.route('**/__local__/evaluation**', r => r.fulfill({ json: release }));
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/evaluation');
    await expect(page.getByText(`保存版の照合済み ${release.verification.resolvedPersonIds.length}人`, { exact: true })).toBeVisible();
    await expect(page.getByText(`評価可能 ${release.result.rows.filter((r: { score: number | null }) => r.score !== null).length}人`, { exact: true })).toBeVisible();
    const button = page.getByRole('button', { name: new RegExp(person.name) });
    await button.focus(); await page.keyboard.press('Enter');
    const detail = page.getByRole('region', { name: '実評価の人物詳細' });
    await detail.locator('summary').first().click();
    const action = release.input.evidenceEvaluation.actions.find((a: { personId: string }) => a.personId === person.id);
    const material = release.input.evidenceEvaluation.materials.find((m: { id: string }) => m.id === action.quotes[0].materialId);
    if (catalog) {
      const policy = catalog.policies.find((p: { policyId: string }) => p.policyId === action.policyId);
      await expect(detail.locator('summary').first()).toHaveText(policy.formalTitle);
      await expect(detail.getByText(policy.summary, { exact: true })).toBeVisible();
      await expect(detail.getByRole('link', { name: '国会の議案説明を読む' })).toHaveAttribute('href', policy.officialUrl);
      await expect(page.getByText(/vote-observation-/)).toHaveCount(0);
      await expect(detail.getByText(action.description, { exact: true })).not.toBeVisible();
    }
    await expect(detail.getByRole('link', { name: '原資料を開く' }).first()).toHaveAttribute('href', material.url);
    await expect(detail.getByRole('heading', { name: '保留理由', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`m2-private-${width}.png`) });
  }
  expect(errors).toEqual([]);
});
