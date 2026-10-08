import { describe, it, expect } from 'vitest';
import { actionRevision, actionIdentity, type EvidenceEvaluationInput } from './evidence-evaluation';
import { availableRealRelease, createReleaseLoader, parseRealRelease, readRealRoute, realRouteSearch, REAL_RELEASE_MAX_BYTES, recordedIdentityCoverage, realActionHeading, type RealRelease } from './real-release-view';

describe('実投票の利用者向け見出し', () => {
  it('抽出ログではなく対象議案・日付・賛否を表示します', () => {
    const action = { namespace: 'sangiin-plenary-vote/v1', policyId: '200-8', actionDate: '2019-11-29', position: 'for' as const, description: '2019-11-29原表抽出結果（HTML marker line=300; allPublishedRowsConfirmed=True）' };
    expect(realActionHeading(action)).toBe('第200回国会・閣法第8号｜2019-11-29・参議院本会議で賛成');
    expect(realActionHeading({ ...action, position: 'not_voted' })).toContain('投票なし');
    expect(realActionHeading({ ...action, policyId: 'unknown' })).toContain('議案番号未確認');
  });
  it('他の行動の説明は勝手に投票へ変換しません', () => {
    expect(realActionHeading({ namespace: 'other', policyId: 'p', actionDate: '2020-01-01', position: 'unknown', description: '資料に記録された行動です。' })).toBe('2020-01-01・資料に記録された行動です。');
  });
});

async function fixture(): Promise<RealRelease> {
  // 架空の試験記録です。mode=realは読み取り契約の試験用で、実在人物の検証成功ではありません。
  const people = [{ id: 'p1', name: '試験人物一' }, { id: 'p2', name: '試験人物二' }];
  const input: EvidenceEvaluationInput = { schemaVersion: 'evidence-evaluation/v1', mode: 'real', options: { domain: 'economy', direction: 'harm', period: 4, asOf: '2026-10-02', weights: { economy: 70, technology: 30 } }, people, materials: [], actions: [], assessments: [] };
  const body = { schemaVersion: 'evidence-release/v1' as const, engineHash: 'a'.repeat(64), input: { evidenceEvaluation: input, materialRefs: [] },
    result: { mode: 'real' as const, rows: people.map(person => ({ person, score: null, rank: null, eligibleCount: 0, heldCount: 0, contributions: [] })), held: [], coverage: { inputActions: 0, assessedActions: 0, readableMaterials: 0 }, publicationStatus: 'requires_human_review' as const }, publicationStatus: 'requires_human_review' as const };
  return { ...body, releaseId: await actionRevision(body) };
}
async function resign(release: RealRelease) { const { releaseId: _id, ...body } = release; release.releaseId = await actionRevision(body); return JSON.stringify(release); }

describe('非公開実評価保存版の読み取り', () => {
  it('同じ政策の異なる結果を保存して再読込できます', async () => {
    const r = await fixture();
    r.input.evidenceEvaluation.options.timeBasis = 'outcome';
    const m = { id: 'source', url: 'https://www.sangiin.go.jp/test', originalHash: 'c'.repeat(64), contentHash: 'd'.repeat(64), observedAt: '2026-10-01T00:00:00Z', publishedAt: null };
    r.input.evidenceEvaluation.materials = [m]; r.input.materialRefs = [{ id: m.id, originalHash: m.originalHash, selector: {} }];
    for (const outcomeId of ['result-one', 'result-two']) {
      const semantic = { namespace: 'fixture', sourceActionId: outcomeId, sourceActorId: 'p1', policyId: 'policy', personId: 'p1', policyVersion: 'v1', actionDate: '2024-01-01', role: 'vote' as const, position: 'for' as const, description: '人工の投票', outcomeId, quotes: [{ materialId: m.id, start: 0, end: 1, text: '票' }] };
      const action = { ...semantic, actionId: await actionIdentity(semantic), revisionId: await actionRevision(semantic) };
      r.input.evidenceEvaluation.actions.push(action);
      r.result.rows[0].contributions.push({ policyId: 'policy', actionKey: action.actionId, actionDate: action.actionDate, role: action.role, score: .25, outcomeId });
    }
    Object.assign(r.result.rows[0], { score: .5, rank: 1, eligibleCount: 2 });
    r.result.coverage = { inputActions: 2, assessedActions: 2, readableMaterials: 1 };
    expect((await parseRealRelease(await resign(r))).result.rows[0].score).toBe(.5);
    r.result.rows[0].contributions[1].outcomeId = 'result-one';
    await expect(parseRealRelease(await resign(r))).rejects.toThrow();
  });
  it('団体だけの集計を保存し、個人を欠落扱いしません', async () => {
    const r = await fixture();
    r.input.evidenceEvaluation.options.actorGroup = 'organizations';
    r.input.evidenceEvaluation.people.push({ id: 'org', name: '人工団体', actorType: 'organization' });
    r.result.rows = [{ person: r.input.evidenceEvaluation.people[2], score: null, rank: null, eligibleCount: 0, heldCount: 0, contributions: [] }];
    expect((await parseRealRelease(await resign(r))).result.rows).toHaveLength(1);
  });
  it('正本pipelineが生成したwrapped wireをそのまま読みます', async () => {
    const fs = 'node:fs/promises', os = 'node:os', path = 'node:path';
    const { mkdtemp, rm } = await import(/* @vite-ignore */ fs);
    const { tmpdir } = await import(/* @vite-ignore */ os);
    const { join } = await import(/* @vite-ignore */ path);
    const moduleUrl = new URL('../../scripts/evidence_pipeline.mjs', import.meta.url).href;
    const { runEvidencePipeline } = await import(/* @vite-ignore */ moduleUrl);
    const r = await fixture(); const root = await mkdtemp(join(tmpdir(), 'release-view-'));
    try {
      const saved = await runEvidencePipeline(r.input, { repoRoot: root, outputDir: join(root, '.local', 'release'), engineHash: r.engineHash, evaluate: async () => r.result });
      const parsed = await parseRealRelease(JSON.stringify(saved));
      expect(parsed.releaseId).toBe(saved.releaseId); expect(parsed.input.evidenceEvaluation.mode).toBe('real');
      expect(parsed.input).not.toHaveProperty('mode');
    } finally { await rm(root, { recursive: true, force: true }); }
  }, 30_000);
  it('任意の検証receiptを保持しても信頼文脈へ昇格しません', async () => {
    const r = await fixture(); r.verification = { inputHash: await actionRevision(r.input.evidenceEvaluation), verifierId: '試験', verifierVersion: '1', resolvedPersonIds: ['p1'], actionRevisions: [], assessmentRevisions: [] };
    const parsed = await parseRealRelease(await resign(r));
    expect(parsed.verification).toEqual(r.verification); expect(parsed.result.rows[0].score).toBeNull();
  });
  const smokePath = (globalThis as unknown as { process?: { env: Record<string, string | undefined> } }).process?.env.REAL_RELEASE_SMOKE_PATH;
  it.skipIf(!smokePath)('保存済みの実資料評価版を読み取ります（非公開の指定入力）', async () => {
    const fs = 'node:fs/promises'; const { readFile } = await import(/* @vite-ignore */ fs);
    const r = await parseRealRelease(await readFile(smokePath!, 'utf8'));
    expect(r.input.evidenceEvaluation.mode).toBe('real'); expect(r.publicationStatus).toBe('requires_human_review');
  }, 30_000);
  it('実評価版を読み、未評価を0点にしません', async () => {
    const r = await parseRealRelease(JSON.stringify(await fixture()));
    expect(r.result.rows).toHaveLength(2); expect(r.result.rows[0].score).toBeNull(); expect(r.publicationStatus).toBe('requires_human_review');
  });
  it('内容を変えた不正ハッシュを拒否します', async () => {
    const r = await fixture(); r.input.evidenceEvaluation.people[0].name = '改ざん';
    await expect(parseRealRelease(JSON.stringify(r))).rejects.toThrow('ハッシュ');
  });
  it('架空専用の評価モードを実評価として開きません', async () => {
    const r = await fixture(); r.input.evidenceEvaluation.mode = 'test-only';
    await expect(parseRealRelease(await resign(r))).rejects.toThrow('非公開実評価');
  });
  it('点数の不正値・参照の不一致・自己検証を拒否します', async () => {
    const score = await fixture(); score.result.rows[0].score = -1; score.result.rows[0].rank = 1;
    await expect(parseRealRelease(await resign(score))).rejects.toThrow();
    const ref = await fixture(); ref.result.rows[0].person = { id: 'unknown', name: '不明' };
    await expect(parseRealRelease(await resign(ref))).rejects.toThrow();
    const approval = await fixture(); Object.assign(approval.input.evidenceEvaluation, { verified: true });
    await expect(parseRealRelease(await resign(approval))).rejects.toThrow();
  });
  it('人物の欠落と内訳の水増しを拒否します', async () => {
    const r = await fixture(); r.result.rows.pop(); await expect(parseRealRelease(await resign(r))).rejects.toThrow('欠落');
    const c = await fixture(); c.result.rows[0].eligibleCount = 1; await expect(parseRealRelease(await resign(c))).rejects.toThrow();
  });
  it('5MBを超えるファイルを読みません', async () => {
    await expect(parseRealRelease(' '.repeat(REAL_RELEASE_MAX_BYTES + 1))).rejects.toThrow('5MB');
  });
});

describe('版と人物をURLへ束縛する入口', () => {
  it('同じ版・人物条件を復元します', () => {
    const route = { dataset: 'real' as const, release: 'a'.repeat(64), person: 'person/one' };
    expect(readRealRoute(realRouteSearch(route))).toEqual(route);
    expect(realRouteSearch({ dataset: 'fiction', release: route.release, person: route.person })).toBe('?dataset=fiction');
  });
  it('再読込と戻るで参照版がなければ架空や別版へ置換しません', async () => {
    const r = await fixture(); const route = { dataset: 'real' as const, release: r.releaseId, person: '' };
    expect(availableRealRelease(route, null)).toBeNull();
    expect(availableRealRelease({ ...route, release: 'b'.repeat(64) }, r)).toBeNull();
    expect(availableRealRelease(route, r)).toBe(r);
  });
});

describe('非同期ファイル選択', () => {
  it('指定された版以外を採用しません', async () => {
    const accepted: RealRelease[] = [], errors: string[] = [];
    const loader = createReleaseLoader(r => accepted.push(r), e => errors.push(e));
    await loader.load({ size: 1, text: async () => JSON.stringify(await fixture()) }, 'b'.repeat(64));
    expect(accepted).toEqual([]); expect(errors).toHaveLength(1);
  });
  it('保存照合記録と記載人数を分け、未知IDや重複を昇格しません', async () => {
    const r = await fixture();
    expect(recordedIdentityCoverage(r)).toBeNull();
    r.verification = { resolvedPersonIds: ['p1'] };
    expect(recordedIdentityCoverage(r)).toEqual({ matched: 1, unresolved: 1 });
    r.verification = { resolvedPersonIds: ['p1', 'p1'] };
    expect(recordedIdentityCoverage(r)).toBeNull();
    r.verification = { resolvedPersonIds: ['unknown'] };
    expect(recordedIdentityCoverage(r)).toBeNull();
  });
  it('連続選択は最後の結果だけを採用します', async () => {
    const accepted: RealRelease[] = []; const errors: string[] = [];
    const loader = createReleaseLoader(r => accepted.push(r), e => errors.push(e));
    let firstText!: (text: string) => void;
    const first = loader.load({ size: 1, text: () => new Promise(resolve => { firstText = resolve; }) });
    const r = await fixture(); await loader.load({ size: 1, text: async () => JSON.stringify(r) });
    firstText('invalid'); await first;
    expect(accepted).toEqual([r]); expect(errors).toEqual([]);
  });
  it('不正な次入力で前の正常版を置換しません', async () => {
    const accepted: RealRelease[] = []; const errors: string[] = [];
    const loader = createReleaseLoader(r => accepted.push(r), e => errors.push(e));
    await loader.load({ size: 1, text: async () => JSON.stringify(await fixture()) });
    await loader.load({ size: 1, text: async () => '{}' });
    expect(accepted).toHaveLength(1); expect(errors).toHaveLength(1);
  });
  it('画面遷移・解除後の読み取り結果を採用しません', async () => {
    const accepted: RealRelease[] = []; const loader = createReleaseLoader(r => accepted.push(r), () => {});
    let text!: (value: string) => void;
    const request = loader.load({ size: 1, text: () => new Promise(resolve => { text = resolve; }) });
    loader.cancel(); text(JSON.stringify(await fixture())); await request; expect(accepted).toEqual([]);
  });
});
