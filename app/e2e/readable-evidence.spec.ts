import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

test('実資料の本文・投票行を検索し原資料へたどれるが架空順位へ混ぜない', async ({ page }) => {
  const evidence = { verificationState: 'unverified', selectionScope: '限定研究開発資料', speeches: [{ id: 's1', speakerName: '記載名甲', date: '2025-01-15', text: '研究開発の本文です。\n<script>alert(1)</script>', sourceUrl: 'https://kokkai.ndl.go.jp/api/speech', observedAt: '2026-10-01T00:00:00Z', sha256: 'a'.repeat(64), locator: 'speechRecord[0]' }], votes: Array.from({ length: 25 }, (_, i) => ({ id: `v${i}`, nameText: `記載名${i}`, date: '2025-01-15', position: 'not_voted', title: '研究開発議案', policyId: 'policy-1', text: '原資料の投票なし一覧です。', sourceUrl: 'https://www.sangiin.go.jp/vote', observedAt: '2026-10-01T00:00:00Z', sha256: 'b'.repeat(64), locator: `投票なし行${i}` })), counts: { savedRecords: 2, readableSpeechBodies: 1, sourceVoteRows: 25, confirmedActionEvidence: 0 } };
  const data = { schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-10-01', coverage: { scope: '限定取得', assessedPeople: 0, sourceStatus: 'pages_captured', sourceRecords: 2 }, people: [], policies: [], involvements: [], evidence: [], held: [], readableEvidence: evidence };
  await page.goto('/');
  const external: string[] = [];
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4179')) external.push(request.url()); });
  const input = page.getByLabel('ローカル評価データJSONを開く');
  await input.setInputFiles({ name: 'readable.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(data)) });
  const panel = page.getByRole('region', { name: '読める実資料（未採点）' });
  await expect(panel.locator('details')).toHaveCount(10);
  await panel.getByText('発言：記載名甲・2025-01-15', { exact: true }).click();
  await expect(panel).toContainText('<script>alert(1)</script>');
  await expect(panel.locator('script')).toHaveCount(0);
  await expect(panel.getByRole('link', { name: '原資料を開く' }).first()).toHaveAttribute('href', evidence.speeches[0].sourceUrl);
  await panel.getByRole('button', { name: '次の資料' }).click();
  await expect(panel.getByRole('status')).toContainText('2 / 3');
  await panel.getByRole('searchbox', { name: '記載名・本文を検索' }).fill('記載名24');
  await expect(panel.locator('details')).toHaveCount(1);
  await panel.locator('summary').click();
  await expect(panel).toContainText('欠席・棄権・反対を推定しません');
  await expect(page.locator('tbody tr').first()).toContainText('架空議員あおい');
  await input.setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ ...data, readableEvidence: { ...evidence, verificationState: 'verified' } })) });
  await expect(page.getByRole('alert')).toContainText('直前に読み取れた結果を保持');
  await expect(panel).toContainText('限定研究開発資料');
  expect(external).toEqual([]);
});

test('保存済み実資料を両テーマ・PCとスマホで閲覧する', async ({ page }) => {
  const inputPath = process.env.READABLE_EVIDENCE_INPUT;
  test.skip(!inputPath, '非公開の原本由来データを明示したローカル検証だけで実行します');
  const raw = readFileSync(inputPath!, 'utf8');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const direction of ['harm', 'benefit']) {
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(`/?direction=${direction}`);
      await page.getByLabel('ローカル評価データJSONを開く').setInputFiles({
        name: 'registered-readable.json', mimeType: 'application/json', buffer: Buffer.from(raw),
      });
      const panel = page.getByRole('region', { name: '読める実資料（未採点）' });
      await expect(panel).toBeVisible();
      await expect(panel).toContainText('397');
      await expect(panel).toContainText('247');
      await panel.locator('summary').first().click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `../.local/readable-${direction}-${width}.png`, fullPage: true });
    }
  }
  expect(errors).toEqual([]);
});
