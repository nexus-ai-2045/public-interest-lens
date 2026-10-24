import { expect, type Page } from '@playwright/test';

/** ページエラーと /distribution/ の応答（ok かつ JSON）を集める。無いファイルは SPA のフォールバックで 200 の HTML が返るので、種類も見る。 */
export function watchPage(page: Page) {
  const pageErrors: string[] = [];
  const dataProblems: string[] = [];
  const dataUrls: string[] = [];
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('response', response => {
    if (!response.url().includes('/distribution/')) return;
    const path = new URL(response.url()).pathname;
    dataUrls.push(path);
    const type = response.headers()['content-type'] ?? '';
    if (!response.ok() || !type.includes('json')) dataProblems.push(`${path} が ${response.status()} ${type}`);
  });
  page.on('requestfailed', request => { if (request.url().includes('/distribution/')) dataProblems.push(`${new URL(request.url()).pathname} の取得に失敗`); });
  return {
    dataUrls,
    expectClean() {
      expect(pageErrors, 'pageerror').toEqual([]);
      expect(dataProblems, '配布データの応答').toEqual([]);
    },
  };
}

/** 「123件」「45人を表示」のような文の先頭の数を取る。 */
export function leadingNumber(text: string | null): number {
  const match = (text ?? '').replace(/,/g, '').match(/\d+/);
  if (!match) throw new Error(`数が見つからない：${text}`);
  return Number(match[0]);
}
