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
  it('hashを付け直した偽の検証receiptと得点も拒否します', async () => {
    const cryptoModule = 'node:crypto';
    const { createHash } = await import(/* @vite-ignore */ cryptoModule);
    const canonical = (v: unknown): string => Array.isArray(v) ? `[${v.map(canonical).join(',')}]` : v && typeof v === 'object' ? `{${Object.entries(v).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => `${JSON.stringify(k)}:${canonical(x)}`).join(',')}}` : JSON.stringify(v);
    const real = input(); real.evidenceEvaluation.mode = 'real';
    const body = { schemaVersion: 'evidence-release/v1', engineHash: 'a'.repeat(64), input: real,
      publicationStatus: 'requires_human_review', result: { ...evaluated, mode: 'real', rows: [{ person: { id: 'unknown', name: '人工テスト' }, score: 1, contributions: [] }], coverage: { inputActions: 2, assessedActions: 2, readableMaterials: 0 } },
      verification: { inputHash: 'b'.repeat(64), verifierId: 'fake', verifierVersion: '1', resolvedPersonIds: [], actionRevisions: [], assessmentRevisions: [] } };
    const forged = { ...body, releaseId: createHash('sha256').update(canonical(body)).digest('hex') };
    expect(() => pipeline.buildReviewPacket(forged)).toThrow();
    body.verification.inputHash = createHash('sha256').update(canonical(real.evidenceEvaluation)).digest('hex');
    expect(() => pipeline.buildReviewPacket({ ...body, releaseId: createHash('sha256').update(canonical(body)).digest('hex') })).toThrow();
  });
  it('実入力の全件保留をM2成立や公開許可へ変換しません', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-review-'));
    try {
      const real = input(); real.evidenceEvaluation.mode = 'real';
      const release = await pipeline.runEvidencePipeline(real, { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64), evaluate: async () => ({ ...evaluated, mode: 'real' }) });
      const review = await pipeline.writeReviewPacket(release, { repoRoot: root, outputDir: join(root, '.local', 'review') });
      expect(review.m2Status).toBe('not_established');
      expect(review.publicationStatus).toBe('requires_human_review');
      expect(review).not.toHaveProperty('materialRefs');
      expect(JSON.parse(await readFile(join(root, '.local', 'review', `review-${release.releaseId}.json`), 'utf8')).releaseId).toBe(release.releaseId);
      release.result.coverage.assessedActions = 100;
      expect(() => pipeline.buildReviewPacket(release)).toThrow();
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('公式https URLをレビュー資料へ通し、ローカルパスは拒否します', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-review-url-'));
    try {
      const real = input(); real.evidenceEvaluation.mode = 'real';
      real.evidenceEvaluation.materials = [{ id: 'official', url: 'https://www.sangiin.go.jp/japanese/touhyoulist/test.htm',
        originalHash: 'a'.repeat(64), contentHash: 'b'.repeat(64), observedAt: '2026-10-03T00:00:00Z', publishedAt: null }] as never[];
      const release = await pipeline.runEvidencePipeline(real, { repoRoot: root, outputDir: join(root, '.local', 'release'),
        engineHash: 'a'.repeat(64), evaluate: async () => ({ ...evaluated, mode: 'real' }) });
      expect(pipeline.buildReviewPacket(release).publicationStatus).toBe('requires_human_review');
      const syntheticUserPath = join('C:', 'Users', 'test-fixture', 'record.json').replaceAll('\\', '/');
      for (const [index, reason] of [syntheticUserPath, 'noteC:\\private\\secret.txt'].entries()) {
        const unsafe = await pipeline.runEvidencePipeline(real, { repoRoot: root, outputDir: join(root, '.local', `unsafe-${index}`),
          engineHash: 'a'.repeat(64), evaluate: async () => ({ ...evaluated, mode: 'real', held: [{ reason }] }) });
        expect(() => pipeline.buildReviewPacket(unsafe)).toThrow('非公開パス');
      }
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('人工入力を実公開候補へ変換しません', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-review-'));
    try {
      const release = await pipeline.runEvidencePipeline(input(), { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64), evaluate: async () => evaluated });
      expect(() => pipeline.buildReviewPacket(release)).toThrow();
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('検証器の保留結果に紛れた非公開パスを保存・投影しません', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-review-'));
    try {
      const real = input(); real.evidenceEvaluation.mode = 'real';
      await expect(pipeline.runEvidencePipeline(real, { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64),
        evaluate: async () => ({ ...evaluated, mode: 'real', held: [{ reason: '人工テスト保留', privateLogPath: 'C:/private/log.json' }] }),
      })).rejects.toThrow();
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  it('独立実行側の検証結果だけを入力のhashへ束縛します', async () => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-verifier-'));
    try {
      const pilot = input();
      pilot.evidenceEvaluation.people = [{ id: 'person-test' }] as never[];
      const release = await pipeline.runEvidencePipeline(pilot, {
        repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: 'a'.repeat(64),
        verifyEvidence: async (_input: unknown, _materials: unknown, inputHash: string) => ({
          inputHash, verifierId: 'test-only-verifier', verifierVersion: '1',
          resolvedPersonIds: ['person-test'], actionRevisions: [], assessmentRevisions: [],
        }),
        evaluate: async (_input: unknown, trusted: { resolvedPersonIds: Set<string> }) => {
          expect([...trusted.resolvedPersonIds]).toEqual(['person-test']);
          return { ...evaluated, rows: [{ person: { id: 'person-test' }, score: null, rank: null, eligibleCount: 0, heldCount: 0, contributions: [] }] };
        },
      });
      expect(release.verification.verifierId).toBe('test-only-verifier');
      expect(release.verification.inputHash).toMatch(/^[a-f0-9]{64}$/);
    } finally { await rm(root, { recursive: true, force: true }); }
  });
  test.each(['wrong-hash', 'unknown-person', 'unknown-action', 'duplicate-person'])('独立検証の%sを拒否し前正常版を保持します', async kind => {
    const root = await mkdtemp(join(tmpdir(), 'evidence-verifier-'));
    try {
      const out = join(root, '.local', 'release');
      const options = { repoRoot: root, outputDir: out, engineHash: 'a'.repeat(64), evaluate: async () => evaluated };
      await pipeline.runEvidencePipeline(input(), options);
      const before = await readFile(join(out, 'current.json'), 'utf8');
      const pilot = input(); pilot.evidenceEvaluation.people = [{ id: 'person-test' }] as never[];
      await expect(pipeline.runEvidencePipeline(pilot, { ...options,
        verifyEvidence: async (_input: unknown, _materials: unknown, inputHash: string) => ({
          inputHash: kind === 'wrong-hash' ? 'b'.repeat(64) : inputHash,
          verifierId: 'test-only', verifierVersion: '1',
          resolvedPersonIds: kind === 'unknown-person' ? ['missing'] : kind === 'duplicate-person' ? ['person-test', 'person-test'] : [],
          actionRevisions: kind === 'unknown-action' ? [{ id: 'missing', revisionId: 'c'.repeat(64) }] : [], assessmentRevisions: [],
        }),
      })).rejects.toThrow();
      expect(await readFile(join(out, 'current.json'), 'utf8')).toBe(before);
    } finally { await rm(root, { recursive: true, force: true }); }
  });
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
