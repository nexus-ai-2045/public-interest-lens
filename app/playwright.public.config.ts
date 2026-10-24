import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

// 公開版（VITE_PUBLIC_SITE=true のビルド）を vite preview で出して確かめる。
// クラウドでは同梱の Chromium、無ければ（Mac など）Playwright 既定のブラウザ。
const executablePath = process.env.CHROMIUM_PATH ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);

export default defineConfig({
  testDir: './e2e/public',
  workers: 1,
  retries: 0,
  timeout: 30000,
  expect: { timeout: 8000 },
  use: { baseURL: 'http://127.0.0.1:4181', browserName: 'chromium', headless: true, launchOptions: { executablePath } },
  projects: [
    { name: 'pc', use: { viewport: { width: 1280, height: 900 } } },
    { name: 'phone', use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: `${process.env.E2E_NO_BUILD === '1' ? '' : 'VITE_PUBLIC_SITE=true npm run build && '}npx vite preview --host 127.0.0.1 --port 4181 --strictPort`,
    url: 'http://127.0.0.1:4181',
    reuseExistingServer: false,
    timeout: 180000,
  },
});
