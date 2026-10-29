// 公開版をローカルでビルドして localhost に出し、主要な画面を開いて確かめる（Vercel を待たない確認）。
// 使い方（app/ で）：npm run preview:check   画像は ../.local/preview/<日付>/ に保存（Git に入れない）。
// 手順と落とし穴は docs/ローカルで画面を確かめる.md。
import { spawn, execSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from '@playwright/test';

const PORT = Number(process.env.PREVIEW_PORT ?? 4180);
const BASE = `http://127.0.0.1:${PORT}`;
// 画面ごとのタイトル（document.title に含まれる語）。h1 はサイト共通の題になったので使わない。
// ルートが消えても SPA のフォールバックは 200 で別の画面を出すので、タイトルで確かめる。
const PAGES = {
  '/': '議員・実名',
  '/ranking': '法律・政策ランキング',
  '/members': '議員・実名',
  '/world': '世界のGDP比較',
  '/stop-side': '技術を止めた側と判決',
  '/methodology': '計算方法',
};
const out = resolve('..', '.local', 'preview', new Date().toISOString().slice(0, 10));

if (!process.argv.includes('--no-build')) {
  execSync('VITE_PUBLIC_SITE=true npm run build', { stdio: 'inherit' });
}
mkdirSync(out, { recursive: true });

const server = spawn('npx', ['vite', 'preview', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], { stdio: ['ignore', 'pipe', 'pipe'], detached: true });
let exited = null;
let announced = false;
// 起動した vite preview 自身が自分の URL を出したときだけ「起動した」とみなす。
// ポートが使用中なら --strictPort で子が終わるので、別のサーバーの 200 を成功と取り違えない。
server.stdout.on('data', chunk => { if (String(chunk).includes(`${PORT}`)) announced = true; });
server.stderr.on('data', () => {});
server.on('exit', code => { exited = code; });
// npx の下で動く vite まで止める（子だけ止めると vite が残り、次の回でポートが埋まる）。
const stop = () => { try { process.kill(-server.pid); } catch { /* もう止まっている */ } };
process.on('exit', stop);

async function waitForServer() {
  for (let i = 0; i < 120; i++) {
    if (exited !== null) throw new Error(`vite preview が終了した（コード ${exited}）。ポート ${PORT} が使用中なら PREVIEW_PORT で変える`);
    if (announced) {
      try { if ((await fetch(BASE)).ok) return; } catch { /* まだ起動中 */ }
    }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`${BASE} が起動しない`);
}

// クラウドの環境では同梱の Chromium を使う。Mac では Playwright 既定のブラウザ。
const executablePath = process.env.CHROMIUM_PATH ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);

let failed = 0;
try {
  await waitForServer();
  const browser = await chromium.launch({ headless: true, executablePath });
  for (const [label, viewport] of [['pc', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
    const page = await browser.newPage({ viewport });
    for (const [path, expected] of Object.entries(PAGES)) {
      const errors = [];
      page.removeAllListeners('pageerror');
      page.removeAllListeners('response');
      page.removeAllListeners('requestfailed');
      page.on('pageerror', e => errors.push(String(e)));
      // 画面はデータの読み込みに失敗しても例外を出さずにエラー表示へ切り替えるので、配布データの応答そのものを見る。
      // 無いファイルは SPA のフォールバックで 200 の HTML が返るので、JSON であることも確かめる。
      page.on('response', r => {
        if (!r.url().includes('/distribution/')) return;
        const type = r.headers()['content-type'] ?? '';
        if (!r.ok() || !type.includes('json')) errors.push(`データ ${new URL(r.url()).pathname} が ${r.status()} ${type}`);
      });
      page.on('requestfailed', r => { if (r.url().includes('/distribution/')) errors.push(`データ ${new URL(r.url()).pathname} の取得に失敗`); });
      const res = await page.goto(BASE + path, { waitUntil: 'networkidle' });
      const text = (await page.locator('body').innerText()).trim();
      const title = await page.title();
      const ok = res?.ok() && errors.length === 0 && text.length > 0 && title.includes(expected) && exited === null;
      if (!ok) failed++;
      const file = `${label}${path.replaceAll('/', '_') || '_'}.png`;
      await page.screenshot({ path: resolve(out, file), fullPage: false });
      console.log(`${ok ? 'OK  ' : 'NG  '}${exited !== null ? `（vite preview が終了：${exited}）` : ''}${label} ${path}${errors.length ? `  エラー：${errors[0]}` : ''}${text ? '' : '  本文が空'}${title.includes(expected) ? '' : `  タイトルに「${expected}」が無い（${title || 'タイトルなし'}）`}`);
    }
    await page.close();
  }
  await browser.close();
} finally {
  stop();
}
console.log(`画像：${out}`);
process.exit(failed ? 1 : 0);
