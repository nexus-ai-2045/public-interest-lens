import { expect, it } from 'vitest';
import config from '../vite.config';

it('依存を共有しても生成キャッシュは作業先ごとに分離する', () => {
  expect(config.cacheDir).toBe('.local/vite');
});
