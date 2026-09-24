import { test, expect } from '@playwright/test';

test('主操作を先に見せ、条件の変化を示し、人物詳細から順位へ戻れる', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const ranking = page.locator('#ranking');
  const localInspection = page.getByRole('region', { name: '資料の取得状況' });
  await expect(ranking).toBeVisible();
  await expect(localInspection).toBeVisible();
  expect(await ranking.evaluate((node, other) => Boolean(node.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING), await localInspection.elementHandle())).toBe(true);
  await page.getByRole('button', { name: '貢献', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status').filter({ hasText: '現在の比較条件' })).toContainText('経済成長');
  await expect(page.getByRole('status').filter({ hasText: '現在の比較条件' })).toContainText('貢献');
  await page.getByRole('button', { name: '架空議員べに' }).click();
  await page.getByRole('link', { name: 'ランキングへ戻る' }).focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#ranking$/);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)).toBe('auto');
});

test('分野・方向・期間を切り替え、URLから同じ表示を復元する', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '国賊ランキング' })).toBeVisible();
  await expect(page.getByText('全人物・政策・資料が架空です。')).toBeVisible();
  await expect(page.locator('tbody tr').first()).toContainText('架空議員あおい');
  await page.getByRole('button', { name: '貢献', exact: true }).click();
  await expect(page.locator('tbody tr').first()).toContainText('架空議員べに');
  await page.getByLabel('評価分野').selectOption('technology');
  await expect(page.locator('tbody tr').first()).toContainText('架空議員こはく');
  await page.getByLabel('比較期間').selectOption('2');
  const selectedUrl = page.url();
  await page.reload();
  expect(page.url()).toBe(selectedUrl);
  await expect(page.locator('tbody tr').first()).toContainText('架空議員こはく');
  await page.getByRole('button', { name: '架空議員こはく' }).click();
  await expect(page.getByRole('heading', { name: '架空議員こはくの行動' })).toBeVisible();
  await expect(page.getByText('架空の研究開発促進策').first()).toBeVisible();
  await expect(page.getByText('fixture:action-c')).toBeVisible();
  expect(errors).toEqual([]);
});

test('準備中、未評価、検索、総合重みを区別する', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('評価分野').selectOption('fiscal');
  await expect(page.getByRole('status').filter({ hasText: '評価準備中' })).toBeVisible();
  await page.getByLabel('評価分野').selectOption('economy');
  await page.getByLabel('人物名で検索').fill('だいだい');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody tr')).toContainText('未評価');
  await page.getByLabel('人物名で検索').fill('存在しない');
  await expect(page.getByRole('status').filter({ hasText: '該当する人物がいません' })).toBeVisible();
  await page.getByLabel('人物名で検索').fill('');
  await page.getByRole('button', { name: '詳細設定' }).click();
  await page.getByLabel('評価分野').selectOption('overall');
  await expect(page.getByText('経済70％・技術30％は製品上の初期設定')).toBeVisible();
  await page.getByLabel('評価の種類').selectOption('outlook');
  await page.reload();
  await page.getByRole('button', { name: '詳細設定' }).click();
  await expect(page.getByLabel('評価の種類')).toHaveValue('outlook');
});

test('公約モードで行動実績の寄与点を表示しない', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '架空議員あおい' }).click();
  await page.getByRole('button', { name: /架空の設備投資制限制.*架空の法案を主導して提出/ }).click();
  await expect(page.locator('.policy-metrics')).toContainText('3.00');
  await page.getByRole('button', { name: '詳細設定' }).click();
  await page.getByLabel('評価の種類').selectOption('outlook');
  await expect(page.locator('.policy-metrics')).not.toContainText('3.00');
  await expect(page.locator('.policy-metrics')).toContainText('公約・見込みは未評価');
});

test('同じ政策の提出と採決を別々に選び、行動ごとの根拠を表示する', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /架空の設備投資制限制.*架空の法案を主導して提出/ }).click();
  await expect(page.locator('.evidence-detail')).toContainText('架空の法案を主導して提出');
  await expect(page.locator('.source-panel')).toContainText('fixture:action-a');
  await page.getByRole('button', { name: /架空の設備投資制限制.*架空の個人採決で賛成/ }).click();
  await expect(page.locator('.evidence-detail')).toContainText('架空の個人採決で賛成');
  await expect(page.locator('.source-panel')).toContainText('fixture:action-a-vote');
  await page.reload();
  await expect(page.locator('.evidence-detail')).toContainText('架空の個人採決で賛成');
});

test('ローカルの実データJSONは収録範囲と保留だけを閲覧でき、採点しない', async ({ page }) => {
  const external: string[] = [];
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4179')) external.push(request.url()); });
  await page.goto('/');
  const localData = {
    schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24',
    coverage: { scope: '限定スモーク', assessedPeople: 0, targetPeople: null, sourceStatus: 'capped', sourceRecords: 1, assessedPolicies: 0, candidatePolicies: 1 },
    people: [], policies: [], involvements: [], evidence: [],
    held: [{ id: 'hold-1', reason: '個人の賛否を確認できない', sourceSpeechId: 'speech-1' }],
  };
  await page.getByLabel('ローカル評価データJSONを開く').setInputFiles({ name: 'current.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(localData)) });
  await expect(page.getByRole('heading', { name: 'ローカル実データの確認' })).toBeVisible();
  await expect(page.getByText('算定可能 0人')).toBeVisible();
  await expect(page.getByText('個人の賛否を確認できない')).toBeVisible();
  await expect(page.getByText('資料取得は上限到達')).toBeVisible();
  await expect(page.locator('tbody tr').first()).toContainText('架空議員あおい');
  expect(external).toEqual([]);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'ローカル実データの確認' })).toHaveCount(0);
});

test('公式議案3ページの限定取得結果を保留3件・算定0人として表示する', async ({ page }) => {
  await page.goto('/');
  const localData = {
    schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24',
    coverage: { scope: '公式議案3ページの限定取得', assessedPeople: 0, targetPeople: null, sourceStatus: 'pages_captured', sourceRecords: 3, assessedPolicies: 0, candidatePolicies: 3 },
    people: [], policies: [], involvements: [], evidence: [],
    held: [1, 2, 3].map(id => ({ id: `bill-${id}`, reason: 'impact_unverified', title: `公式議案${id}`, submittedAt: '2026-06-01', sourceUrl: `https://www.sangiin.go.jp/japanese/joho1/kousei/gian/220/meisai/m220${id}.htm`, voteUrl: id === 1 ? 'https://www.sangiin.go.jp/japanese/joho1/kousei/vote/220/vote1.htm' : null, recordPath: 'C:/private/record.json' })),
  };
  await page.getByLabel('ローカル評価データJSONを開く').setInputFiles({ name: 'current.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(localData)) });
  await expect(page.getByRole('heading', { name: 'ローカル実データの確認' })).toBeVisible();
  await expect(page.getByText('指定した公式議案ページを取得、全件網羅ではない')).toBeVisible();
  await expect(page.getByText('算定可能 0人')).toBeVisible();
  await expect(page.getByRole('heading', { name: '保留 3件' })).toBeVisible();
  await expect(page.locator('.inspection-result li')).toHaveCount(3);
  await expect(page.getByText('公式議案1')).toBeVisible();
  await expect(page.getByText('2026-06-01').last()).toBeVisible();
  await expect(page.getByRole('link', { name: '公式資料を開く' }).first()).toHaveAttribute('href', 'https://www.sangiin.go.jp/japanese/joho1/kousei/gian/220/meisai/m2201.htm');
  await expect(page.getByRole('link', { name: '採決資料を開く' })).toHaveAttribute('href', 'https://www.sangiin.go.jp/japanese/joho1/kousei/vote/220/vote1.htm');
  await expect(page.getByText('C:/private/record.json')).toHaveCount(0);
});

test('実データ内の非公式・非HTTPSリンクを拒否する', async ({ page }) => {
  await page.goto('/');
  const base = { schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24', coverage: { scope: '限定取得', assessedPeople: 0, targetPeople: null, sourceStatus: 'pages_captured', sourceRecords: 1 }, people: [], policies: [], involvements: [], evidence: [] };
  for (const sourceUrl of ['javascript:alert(1)', 'https://example.com/bill', 'http://www.sangiin.go.jp/bill']) {
    await page.getByLabel('ローカル評価データJSONを開く').setInputFiles({ name: 'current.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ ...base, held: [{ id: 'bill-1', reason: 'impact_unverified', sourceUrl }] })) });
    await expect(page.getByRole('alert')).toContainText('公式資料URL');
    await expect(page.getByRole('link', { name: '公式資料を開く' })).toHaveCount(0);
  }
});

test('PC・390pxで横はみ出しがなく、架空データ版は外部通信をしない', async ({ page }, testInfo) => {
  const external: string[] = [];
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4179')) external.push(request.url()); });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByText('全人物・政策・資料が架空です。')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`ranking-${width}.png`), fullPage: true });
  }
  expect(external).toEqual([]);
});
