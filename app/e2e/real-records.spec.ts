import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

// 人工の原資料行で操作だけを検証します。本人照合や実評価の成功ではありません。
const pack = (name = '試験記載名') => ({ schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24',
  coverage: { scope: '操作試験の限定資料', assessedPeople: 0, sourceRecords: 1, sourceStatus: 'pages_captured' },
  people: [], policies: [], involvements: [], evidence: [], held: [],
  readableEvidence: { verificationState: 'unverified', selectionScope: '操作試験', speeches: [], votes: [{ id: 'test-row', nameText: name, date: '2026-07-10', position: 'for', title: '試験議案', policyId: 'test-policy', text: `賛成 ${name}`, sourceUrl: 'https://www.sangiin.go.jp/japanese/touhyoulist/test.htm', locator: 'HTML line=1', observedAt: '2026-09-24T00:00:00Z', sha256: 'a'.repeat(64) }], counts: { savedRecords: 1, readableSpeechBodies: 0, sourceVoteRows: 1, confirmedActionEvidence: 0 } } });

test('通常の入口で実資料を読み、架空順位に変換しない', async ({ page }) => {
  await page.route('**/__local__/records', route => route.fulfill({ json: pack() }));
  await page.goto('/records');
  await expect(page.getByRole('button', { name: '試験記載名', exact: true })).toBeVisible();
  await expect(page.locator('.real-records-table')).toContainText('未評価');
  await expect(page.getByText('架空議員あおい', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '試験記載名', exact: true }).click();
  await expect(page.getByRole('region', { name: '選択した投票行の詳細' })).toContainText('試験議案');
  await expect(page.getByRole('link', { name: '公式の原資料を開く' })).toHaveAttribute('href', /sangiin/);
  await page.getByRole('button', { name: '架空デモ', exact: true }).click();
  await expect(page).toHaveURL(/\/ranking$/);
  await expect(page.getByText('全人物・政策・資料が架空です。', { exact: true })).toBeVisible();
});

test('未取得時は手動入口を示し、不正な次入力で実資料を失わない', async ({ page }) => {
  await page.route('**/__local__/records', route => route.fulfill({ status: 404, json: { error: 'local_records_unavailable' } }));
  await page.goto('/records');
  await expect(page.getByRole('alert')).toContainText('閲覧用JSON');
  const input = page.getByLabel('閲覧用JSONを開く');
  await input.setInputFiles({ name: 'test.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(pack())) });
  await expect(page.getByRole('button', { name: '試験記載名', exact: true })).toBeVisible();
  await input.setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{}') });
  await expect(page.getByRole('alert')).toContainText('直前の正常な資料は保持');
  await expect(page.getByRole('button', { name: '試験記載名', exact: true })).toBeVisible();
});

test('保存済み247投票行を主画面で表示し、原資料へたどる', async ({ page }, info) => {
  const input = process.env.READABLE_EVIDENCE_INPUT;
  test.skip(!input, '非公開資料を指定するローカル試験だけで実行します');
  const payload = readFileSync(input!, 'utf8');
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await page.route('**/__local__/records', route => route.fulfill({ contentType: 'application/json', body: payload }));
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/records');
    await expect(page.getByText('投票行 247件', { exact: true })).toBeVisible();
    const first = page.locator('.real-records-table tbody button').first(); await first.focus(); await page.keyboard.press('Enter');
    await expect(page.getByRole('region', { name: '選択した投票行の詳細' })).toContainText('情報通信技術');
    await expect(page.getByRole('link', { name: '公式の原資料を開く' })).toHaveAttribute('href', /sangiin.go.jp/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`actual-records-${width}.png`), fullPage: true });
  }
  expect(errors).toEqual([]);
});
