import { describe, it, expect } from 'vitest';
// Node専用の開発serverをブラウザappの型設定へ取り込まない既存の検査方式です。
const serverUrl = new URL('../local-records-server.ts', import.meta.url).href;
const { localRecordsPlugin, localRequestAllowed, readLocalRecords, readLocalEvaluation } = await import(/* @vite-ignore */ serverUrl);
import { actionRevision } from './evidence-evaluation';
const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path';
const { mkdtemp, mkdir, writeFile, rm } = await import(/* @vite-ignore */ fsModule);
const { tmpdir, homedir } = await import(/* @vite-ignore */ osModule);
const { join } = await import(/* @vite-ignore */ pathModule);

describe('実資料の開発時限定入口', () => {
  const smokePath = (globalThis as unknown as { process?: { env: Record<string, string | undefined> } }).process?.env.REAL_RELEASE_SMOKE_PATH;
  it.skipIf(!smokePath)('保存済み実評価版をローカル入口の検査で読みます', async () => {
    const path = 'node:path'; const { dirname } = await import(/* @vite-ignore */ path);
    const text = await readLocalEvaluation(smokePath!, dirname(smokePath!));
    const release = JSON.parse(text);
    expect(release.result.rows).toHaveLength(release.input.evidenceEvaluation.people.length);
    expect(release.result.publicationStatus).toBe('requires_human_review');
    expect(text).not.toContain('recordPath');
  }, 30_000);
  it('保存評価版の版一致と私的項目の非混入を要求します', async () => {
    const root = await mkdtemp(join(tmpdir(), 'local-evaluation-'));
    try {
      const body = { schemaVersion: 'evidence-release/v1', engineHash: 'a'.repeat(64), publicationStatus: 'requires_human_review',
        input: { materialRefs: [], evidenceEvaluation: { schemaVersion: 'evidence-evaluation/v1', mode: 'real', options: { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-10-03', weights: { economy: 70, technology: 30 } }, people: [], materials: [], actions: [], assessments: [] } },
        result: { mode: 'real', rows: [], held: [], coverage: { inputActions: 0, assessedActions: 0, readableMaterials: 0 }, publicationStatus: 'requires_human_review' } };
      const releaseId = await actionRevision(body), file = join(root, 'current.json');
      await writeFile(file, JSON.stringify({ ...body, releaseId }));
      expect(JSON.parse(await readLocalEvaluation(file, root, releaseId)).releaseId).toBe(releaseId);
      await expect(readLocalEvaluation(file, root, 'b'.repeat(64))).rejects.toThrow('ReleaseMismatch');
      const privateBody = { ...body, verification: { internalLog: 'C:/private/log' } };
      await writeFile(file, JSON.stringify({ ...privateBody, releaseId: await actionRevision(privateBody) }));
      await expect(readLocalEvaluation(file, root)).rejects.toThrow('PrivateField');
      const privatePath: string = join(homedir(), 'test-fixture', 'credential-notes');
      const escapedBody = { ...body, verification: { verifierId: privatePath } };
      const encoded = JSON.stringify({ ...escapedBody, releaseId: await actionRevision(escapedBody) }).replace(JSON.stringify(privatePath), '"' + privatePath.split('').map(c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')).join('') + '"');
      await writeFile(file, encoded);
      await expect(readLocalEvaluation(file, root)).rejects.toThrow('PrivateField');
      const publicBody = { ...body, verification: { verifierId: 'https://example.test/users/public' } };
      await writeFile(file, JSON.stringify({ ...publicBody, releaseId: await actionRevision(publicBody) }));
      expect(JSON.parse(await readLocalEvaluation(file, root)).verification.verifierId).toBe(publicBody.verification.verifierId);
      const syntheticPosixPath = ['', 'home', 'test-fixture', 'private', 'source.json'].join('/');
      const syntheticUncPath = ['\\', 'fixture-host', 'private', 'source.json'].join('\\');
      for (const value of [syntheticUncPath, `source=${syntheticPosixPath}`, `https://example.test/public source=${syntheticPosixPath}`, 'https://fixture:private@example.test/public']) {
        const mixed = { ...body, verification: { verifierId: value } };
        await writeFile(file, JSON.stringify({ ...mixed, releaseId: await actionRevision(mixed) }));
        await expect(readLocalEvaluation(file, root)).rejects.toThrow('PrivateField');
      }
    } finally { await rm(root, { recursive: true, force: true }); }
  });
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
