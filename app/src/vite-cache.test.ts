import { expect, it } from 'vitest';
const configUrl = new URL('../vite.config.ts', import.meta.url).href;
const { default: config } = await import(/* @vite-ignore */ configUrl);

it('依存を共有しても生成キャッシュは作業先ごとに分離する', () => {
  expect(config.cacheDir).toBe('.local/vite');
});
