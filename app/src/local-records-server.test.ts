import { describe, it, expect } from 'vitest';
// Node専用の開発serverをブラウザappの型設定へ取り込まない既存の検査方式です。
const serverUrl = new URL('../local-records-server.ts', import.meta.url).href;
const { localRecordsPlugin, localRequestAllowed, readLocalRecords } = await import(/* @vite-ignore */ serverUrl);
const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path';
const { mkdtemp, mkdir, writeFile, rm } = await import(/* @vite-ignore */ fsModule);
const { tmpdir } = await import(/* @vite-ignore */ osModule);
const { join } = await import(/* @vite-ignore */ pathModule);

describe('実資料の開発時限定入口', () => {
  it('loopback同一originだけを許可します', () => {
    expect(localRequestAllowed('127.0.0.1', '127.0.0.1:5174', 'http://127.0.0.1:5174', 'same-origin')).toBe(true);
    expect(localRequestAllowed('::1', '[::1]:5174', undefined, undefined)).toBe(true);
    expect(localRequestAllowed('10.0.0.2', '127.0.0.1:5174', undefined, undefined)).toBe(false);
    expect(localRequestAllowed('127.0.0.1', 'evil.example', undefined, undefined)).toBe(false);
    expect(localRequestAllowed('127.0.0.1', 'localhost:5174', 'https://evil.example', 'cross-site')).toBe(false);
    expect(localRequestAllowed('127.0.0.1', 'localhost:5174', 'http://localhost:5175', 'same-site')).toBe(false);
    expect(localRequestAllowed('127.0.0.1', 'localhost:5174', 'null', undefined)).toBe(false);
  });
  it('本番buildにはdev handlerを登録しません', () => {
    const plugin = localRecordsPlugin();
    expect(plugin.apply).toBe('serve');
    expect(plugin.configurePreviewServer).toBeUndefined();
    expect(plugin.generateBundle).toBeUndefined();
  });
  it('私的パスと評価入力を投影せず、保管先外を拒否します', async () => {
    const root = await mkdtemp(join(tmpdir(), 'local-records-'));
    try {
      const local = join(root, '.local'); await mkdir(local);
      const pack = { schemaVersion: 'ranking-dataset/v1', fictional: false, asOf: '2026-09-24', coverage: { scope: '人工検査', assessedPeople: 0, sourceRecords: 0, sourceStatus: 'pages_captured' },
        people: [], policies: [], involvements: [], evidence: [], held: [], materialRefs: [{ recordPath: 'C:/private/source.json' }], evidenceEvaluation: { internalLog: '秘密の検査用文字列' } };
      const file = join(local, 'current.json'); await writeFile(file, JSON.stringify(pack));
      const result = await readLocalRecords(file, local);
      expect(result).not.toContain('recordPath'); expect(result).not.toContain('秘密'); expect(result).not.toContain('evidenceEvaluation');
      const outside = join(root, 'outside.json'); await writeFile(outside, JSON.stringify(pack));
      await expect(readLocalRecords(outside, local)).rejects.toThrow('PrivateRoot');
      await writeFile(file, ' '.repeat(5_000_001)); await expect(readLocalRecords(file, local)).rejects.toThrow('InputSize');
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
