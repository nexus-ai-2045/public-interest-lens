import { describe, expect, it as test } from 'vitest';

// 実ファイルの照合・排他・原子的更新を試す統合検査です。
// CPUのみの単体検査とは分け、保存処理の待ち時間を有限の30秒にします。
const it = (name: string, run: () => Promise<void>) => test(name, run, 30_000);
// ブラウザappの型設定にNode型依存を追加せず、VitestのNode実行環境で解決する。
const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path';
const { mkdtemp, readFile, writeFile, mkdir, rm, symlink } = await import(/* @vite-ignore */ fsModule);
const { tmpdir } = await import(/* @vite-ignore */ osModule);
const { join } = await import(/* @vite-ignore */ pathModule);

const moduleUrl = new URL('../../scripts/evidence_pipeline.mjs', import.meta.url).href;
const pipeline = await import(/* @vite-ignore */ moduleUrl);
const input = () => ({ materialRefs: [], evidenceEvaluation: { schemaVersion: 'evidence-evaluation/v1', mode: 'test-only',
  options: { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-10-01', weights: { economy: 70, technology: 30 } },
  people: [], materials: [], actions: [], assessments: [] } });
const evaluated = { mode: 'test-only', rows: [], held: [], coverage: { inputActions: 0, assessedActions: 0, readableMaterials: 0 }, publicationStatus: 'requires_human_review' };

describe('非公開評価版の生成と復旧', () => {
  it('原本保存場所の移動では評価版を変えず、private pathを版へ含めない', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    try {
      const options = { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64), evaluate: async () => evaluated };
      const withRef = (recordPath: string) => ({ ...input(), materialRefs: [{ id: 'material', originalHash: 'b'.repeat(64), recordPath, selector: { kind: 'ndl-speech', speechId: 'speech' } }] });
      const first = await pipeline.runEvidencePipeline(withRef('private-a/record.json'), options);
      const second = await pipeline.runEvidencePipeline(withRef('private-b/record.json'), options);
      expect(first.releaseId).toBe(second.releaseId);
      expect(await readFile(join(options.outputDir, 'current.json'), 'utf8')).not.toContain('recordPath');
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('入力から信頼集合を作らず、算定器へ空の検証文脈だけを渡す', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    try {
      await pipeline.runEvidencePipeline(input(), { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64),
        evaluate: async (_input: unknown, trusted: { resolvedPersonIds: Set<string>; verifiedActionIds: Set<string>; verifiedAssessmentIds: Set<string>; verifiedActionRevisions: Map<string, string>; verifiedAssessmentRevisions: Map<string, string> }) => {
          expect([...trusted.resolvedPersonIds]).toEqual([]);
          expect([...trusted.verifiedActionIds]).toEqual([]);
          expect([...trusted.verifiedAssessmentIds]).toEqual([]);
          expect([...trusted.verifiedActionRevisions]).toEqual([]);
          expect([...trusted.verifiedAssessmentRevisions]).toEqual([]);
          return evaluated;
        } });
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('保存先のリンク逸脱と残存lockを拒否する', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    const outside = await mkdtemp(join(tmpdir(), 'evidence-outside-'));
    try {
      await mkdir(join(root, '.local'));
      await symlink(outside, join(root, '.local', 'escape'), 'junction');
      const options = { repoRoot: root, outputDir: join(root, '.local', 'escape', 'release'), engineHash: 'a'.repeat(64), evaluate: async () => evaluated };
      await expect(pipeline.runEvidencePipeline(input(), options)).rejects.toThrow();
      const out = join(root, '.local', 'release');
      await mkdir(join(out, '.pipeline-lock'), { recursive: true });
      await expect(pipeline.runEvidencePipeline(input(), { ...options, outputDir: out })).rejects.toThrow();
    } finally { await rm(root, { recursive: true, force: true }); await rm(outside, { recursive: true, force: true }); }
  });
  it('同一入力は同じ評価版となり、自己承認せず再実行できる', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    try {
      const out = join(root, '.local', 'release');
      const options = { repoRoot: root, outputDir: out, engineHash: 'a'.repeat(64), evaluate: async () => evaluated };
      const first = await pipeline.runEvidencePipeline(input(), options);
      const second = await pipeline.runEvidencePipeline(input(), options);
      expect(second.releaseId).toBe(first.releaseId);
      expect(first.publicationStatus).toBe('requires_human_review');
      expect(JSON.parse(await readFile(join(out, 'current.json'), 'utf8')).releaseId).toBe(first.releaseId);
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('構造矛盾と自己検証フラグで直前の正常版を壊さない', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    try {
      const out = join(root, '.local', 'release');
      const options = { repoRoot: root, outputDir: out, engineHash: 'a'.repeat(64), evaluate: async () => evaluated };
      await pipeline.runEvidencePipeline(input(), options);
      const before = await readFile(join(out, 'current.json'), 'utf8');
      await expect(pipeline.runEvidencePipeline({ ...input(), trustedContext: { verified: true } }, options)).rejects.toThrow();
      expect(await readFile(join(out, 'current.json'), 'utf8')).toBe(before);
      expect(JSON.parse(await readFile(join(out, 'last-attempt.json'), 'utf8')).status).toBe('failed');
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('公開済みの自己申告と保管先外の出力を拒否する', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    try {
      const options = { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64),
        evaluate: async () => ({ ...evaluated, publicationStatus: 'published' }) };
      await expect(pipeline.runEvidencePipeline(input(), options)).rejects.toThrow();
      await expect(pipeline.runEvidencePipeline(input(), { ...options, outputDir: join(root, 'public') })).rejects.toThrow();
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('既存の不一致な同一版を上書きしない', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-release-'));
    try {
      const out = join(root, '.local', 'release');
      const options = { repoRoot: root, outputDir: out, engineHash: 'a'.repeat(64), evaluate: async () => evaluated };
      const release = await pipeline.runEvidencePipeline(input(), options);
      const file = join(out, 'releases', release.releaseId + '.json');
      await writeFile(file, 'broken');
      await expect(pipeline.runEvidencePipeline(input(), options)).rejects.toThrow();
      expect(await readFile(file, 'utf8')).toBe('broken');
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
