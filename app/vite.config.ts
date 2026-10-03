import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { localRecordsPlugin } from './local-records-server';

export default defineConfig({
  // 作業先で依存を共有しても、別サーバーの生成キャッシュへ書き込まないようにします。
  cacheDir: '.local/vite',
  plugins: [react(), localRecordsPlugin()],
});
