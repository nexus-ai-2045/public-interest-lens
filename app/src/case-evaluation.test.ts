import { describe, expect, it } from 'vitest';
import caseSource from '../../data/distribution/case-source.json';
import { buildCaseEvaluationInput, FINANCIAL_REVIVAL_DRAFT, type CaseEvaluationSpec, type CaseMaterialText } from './case-evaluation';
import { assessmentRevision, evaluateEvidence, type EvidenceEvaluationInput, type TrustedContext } from './evidence-evaluation';

// 人工入力です。金融庁原本・業態別の比率・在職記録は使っていません。数値や影響段階は実在評価ではありません。
const comparison = { treatedGroup: '主要行（人工）', controlGroup: '地域銀行（人工）', observationFrom: '2002-10-30', observationTo: '2005-05-25',
  citations: [{ id: 'test-npl-by-category', url: 'https://www.fsa.go.jp/test-only/npl-by-category', quote: '人工の業態別不良債権比率の表' }] };

function artificialSpec(change: (spec: CaseEvaluationSpec) => void = () => {}): CaseEvaluationSpec {
  const spec = structuredClone(FINANCIAL_REVIVAL_DRAFT);
  spec.mode = 'test-only';
  spec.namespace = 'test-only';
  spec.assessments[0].impact = 2;
  delete spec.assessments[0].series;
  spec.assessments[0].comparison = structuredClone(comparison);
  change(spec);
  return spec;
}

function artificialTexts(): Map<string, CaseMaterialText> {
  const quotes = [...caseSource.citations, ...comparison.citations, ...FINANCIAL_REVIVAL_DRAFT.assessments.flatMap(a => a.comparison?.citations ?? [])];
  return new Map(quotes.map(c => [c.id, { text: `人工の保存本文。${c.quote}。人工の後続文。`, observedAt: '2026-10-09T00:00:00Z', publishedAt: null }]));
}

async function trustedFor(input: EvidenceEvaluationInput, texts: Map<string, CaseMaterialText>, unresolved: string[] = []): Promise<TrustedContext> {
  const materials = new Map(input.materials.map(m => [m.id, m]));
  return {
    readMaterial: async id => { const m = materials.get(id); const t = texts.get(id); return m && t ? { ...m, text: t.text } : null; },
    resolvedPersonIds: new Set(input.people.map(p => p.id).filter(id => !unresolved.includes(id))),
    verifiedActionIds: new Set(input.actions.map(a => a.actionId)),
    verifiedActionRevisions: new Map(input.actions.map(a => [a.actionId, a.revisionId])),
    verifiedAssessmentIds: new Set(input.assessments.map(a => a.id)),
    verifiedAssessmentRevisions: new Map(await Promise.all(input.assessments.map(async a => [a.id, await assessmentRevision(a)] as const))),
  };
}

async function evaluate(spec: CaseEvaluationSpec, unresolved: string[] = []) {
  const texts = artificialTexts();
  const { input, notes } = await buildCaseEvaluationInput(caseSource, spec, texts);
  const result = await evaluateEvidence(input, await trustedFor(input, texts, unresolved));
  const row = (id: string) => result.rows.find(r => r.person.id === id)!;
  return { input, notes, result, row, heldReasons: (id: string) => result.held.filter(h => h.personId === id).map(h => h.reason) };
}

describe('金融再生プログラムの事例を既存の根拠評価へ接続する（人工入力）', () => {
  it('竹中=lead・伊藤=coauthor・岡本=contextの役割係数で結果期間評価が成立します', async () => {
    const { row, heldReasons, input } = await evaluate(artificialSpec());
    expect(input.assessments[0].evidenceMethod).toBe('quantitative');
    expect(row('takenaka-heizo').score).toBe(2);
    expect(row('takenaka-heizo').rank).toBe(1);
    expect(row('ito-fsa').score).toBe(1);
    expect(row('okamoto-fsa').score).toBeNull();
    expect(heldReasons('okamoto-fsa')).toEqual(['行動または引用が未検証です']);
    // 同じ人物・同じ結果への複数行動は、最も強い役割の1件だけを数える。
    expect(row('takenaka-heizo').contributions).toHaveLength(1);
  });

  it('伊藤の同一性が未確定なら伊藤だけを保留し、他の人物の評価は変えません', async () => {
    const { row, heldReasons } = await evaluate(artificialSpec(), ['ito-fsa']);
    expect(row('ito-fsa').score).toBeNull();
    expect(heldReasons('ito-fsa')).toEqual(['人物照合が未検証です']);
    expect(row('takenaka-heizo').score).toBe(2);
  });

  it('対照群が無い前後比較だけでは、影響を保留します', async () => {
    const { row, heldReasons, input, notes } = await evaluate(artificialSpec(spec => { spec.assessments[0].comparison = null; }));
    expect(input.assessments[0].evidenceMethod).toBe('association');
    expect(notes).toContainEqual({ assessmentId: 'npl-ratio-major-banks', reason: '対照群が無く前後比較のみです' });
    for (const id of ['takenaka-heizo', 'ito-fsa']) {
      expect(row(id).score).toBeNull();
      expect(heldReasons(id)).toEqual(['実施済みの実績・結果期間・因果寄与の根拠が不足しています']);
    }
  });

  it('影響段階が未確定の仕様は全員保留で、仮の点数を作りません', async () => {
    const spec = structuredClone({ ...FINANCIAL_REVIVAL_DRAFT, mode: 'test-only' as const });
    spec.assessments[0].impact = null;
    delete spec.assessments[0].series;
    const { result, notes, input } = await evaluate(spec);
    expect(input.assessments).toHaveLength(0);
    expect(notes.map(n => n.reason)).toEqual(['影響の段階が未確定のため分析を作りません']);
    expect(result.rows.every(r => r.score === null)).toBe(true);
    expect(result.coverage.assessedActions).toBe(0);
  });

  it('現在の仕様は判定ルールが実測から段階を決め、開始前のばらつきが大きいため全員保留になります', async () => {
    const { result, input, notes } = await evaluate({ ...FINANCIAL_REVIVAL_DRAFT, mode: 'test-only' });
    expect(input.assessments).toHaveLength(0);
    expect(notes[0].reason).toMatch(/^判定ルール impact-rule-v1: 効果-1\.575（開始前のばらつき1\.2/);
    expect(notes[1].reason).toBe('影響の段階が未確定のため分析を作りません');
    expect(result.rows.every(r => r.score === null)).toBe(true);
  });

  it('判定ルールが段階1を出す系列なら、竹中1点・伊藤0.5点で、結果観測後の行動は使いません', async () => {
    const spec = structuredClone({ ...FINANCIAL_REVIVAL_DRAFT, mode: 'test-only' as const });
    // 人工の系列（開始前の差がほぼ一定）。実在の統計ではありません。
    spec.assessments[0].series!.target = [0, 0.1, -0.1, -0.5, -3, -3, -3, -3].map((g, i) => ({ asOf: `${2000 + i}-03-31`, treated: 8 + g, control: 8 }));
    const { row, input, heldReasons } = await evaluate(spec);
    expect(input.assessments[0]).toMatchObject({ impact: 1, evidenceMethod: 'quantitative', observationFrom: '2002-03-31', observationTo: '2005-03-31' });
    expect(row('takenaka-heizo').score).toBe(1);
    expect(row('ito-fsa').score).toBe(0.5);
    expect(row('ito-fsa').contributions[0].actionDate).toBe('2002-10-30');
    expect(row('okamoto-fsa').score).toBeNull();
    expect(heldReasons('okamoto-fsa')).toEqual(['行動または引用が未検証です']);
  });

  it('実測の系列があるのに段階を手で入れた仕様は止めます', async () => {
    const spec = structuredClone({ ...FINANCIAL_REVIVAL_DRAFT, mode: 'test-only' as const });
    spec.assessments[0].impact = 1;
    await expect(buildCaseEvaluationInput(caseSource, spec, artificialTexts())).rejects.toThrow('判定ルールに任せて');
  });

  it('引用が保存本文に無い、または行動を二重に割り当てた仕様は変換で止めます', async () => {
    const texts = artificialTexts();
    texts.set('ito20050525', { ...texts.get('ito20050525')!, text: '引用を含まない本文' });
    await expect(buildCaseEvaluationInput(caseSource, artificialSpec(), texts)).rejects.toThrow('保存原本の本文に見つかりません');
    const duplicate = artificialSpec(spec => { spec.people[2].actorIds.push('takenaka-20021030'); });
    await expect(buildCaseEvaluationInput(caseSource, duplicate, artificialTexts())).rejects.toThrow('複数人物に割り当て');
  });
});

describe('既存の非公開評価パイプラインへ通す（人工入力）', () => {
  it('独立検証receipt経由で評価版を.local配下へ保存し、公開扱いにしません', async () => {
    const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path';
    const { mkdtemp, rm } = await import(/* @vite-ignore */ fsModule);
    const { tmpdir } = await import(/* @vite-ignore */ osModule);
    const { join } = await import(/* @vite-ignore */ pathModule);
    const pipeline = await import(/* @vite-ignore */ new URL('../../scripts/evidence_pipeline.mjs', import.meta.url).href);
    const texts = artificialTexts();
    const { input } = await buildCaseEvaluationInput(caseSource, artificialSpec(), texts);
    const stored = input.materials.map(m => ({ ...m, text: texts.get(m.id)!.text }));
    const root = await mkdtemp(join(tmpdir(), 'case-evaluation-'));
    try {
      const release = await pipeline.runEvidencePipeline({ materialRefs: [], evidenceEvaluation: input }, {
        repoRoot: root, outputDir: join(root, '.local', 'case'), engineHash: 'a'.repeat(64), evaluate: evaluateEvidence,
        readMaterials: async () => stored,
        verifyEvidence: async (evaluation: EvidenceEvaluationInput, _stored: unknown, inputHash: string) => ({
          inputHash, verifierId: 'test-only-verifier', verifierVersion: '1',
          resolvedPersonIds: evaluation.people.map(p => p.id),
          actionRevisions: evaluation.actions.map(a => ({ id: a.actionId, revisionId: a.revisionId })),
          assessmentRevisions: await Promise.all(evaluation.assessments.map(async a => ({ id: a.id, revisionId: await assessmentRevision(a) }))),
        }),
      });
      expect(release.publicationStatus).toBe('requires_human_review');
      expect(release.result.mode).toBe('test-only');
      expect(release.result.rows.find((r: { person: { id: string } }) => r.person.id === 'takenaka-heizo').score).toBe(2);
    } finally { await rm(root, { recursive: true, force: true }); }
  }, 30_000);
});
