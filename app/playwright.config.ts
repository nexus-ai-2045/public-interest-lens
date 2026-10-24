import { existsSync } from 'node:fs';
import { defineConfig } from '@playwright/test';

// クラウドの環境では内蔵の Chromium を使う（設計決定0011）。Mac では Playwright 既定のブラウザ。
const executablePath = process.env.CHROMIUM_PATH ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);

export default defineConfig({
  testDir: './e2e',
  testIgnore: 'public/**', // 公開版の spec は playwright.public.config.ts で回す
  workers: 1,
  timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:4179', browserName: 'chromium', headless: true, launchOptions: { executablePath } },
  webServer: {
    command: 'npm run dev -- --port 4179 --strictPort',
    url: 'http://127.0.0.1:4179',
    reuseExistingServer: false,
    timeout: 120000,
  },
});
