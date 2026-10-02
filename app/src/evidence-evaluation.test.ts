import { describe, it, expect } from 'vitest';
import { actionIdentity, actionRevision, assessmentRevision, evaluateEvidence, sha256, type EvidenceEvaluationInput, type TrustedContext } from './evidence-evaluation';

describe('根拠評価の安定識別子', () => {
  it('説明の訂正は同じ行動の別改訂です', async () => {
    const base = { namespace: 'test-only', sourceActionId: 'vote-1', sourceActorId: 'actor-1', policyId: 'policy-1' };
    expect(await actionIdentity(base)).toBe(await actionIdentity({ ...base }));
    expect(await actionRevision({ ...base, description: 'before' })).not.toBe(await actionRevision({ ...base, description: 'after' }));
  });
});

async function fixture() {
  const text = '公式に確認できる行動と分析資料';
  const hash = await sha256(text);
  const identity = { namespace: 'test-only', sourceActionId: 'v1', sourceActorId: 'actor1', policyId: 'p1' };
  const content = { ...identity, personId: 'person1', policyVersion: '1', actionDate: '2024-01-01', role: 'lead' as const, position: 'for' as const, description: 'テスト専用', quotes: [{ materialId: 'm1', start: 0, end: text.length, text }] };
  const action = { ...content, actionId: await actionIdentity(identity), revisionId: await actionRevision(content) };
  const assessment = { id: 'analysis1', policyId: 'p1', policyVersion: '1', position: 'for' as const, domain: 'economy' as const, direction: 'benefit' as const, impact: 2 as const, rationale: 'テスト根拠', counterEvidence: 'テスト反証', alternativeExplanation: 'テスト代替説明', criterionVersion: '1', analysisVersion: '1', evaluatedAt: '2026-01-01T00:00:00Z', quotes: structuredClone(content.quotes) };
  const material = { id: 'm1', url: 'https://www.sangiin.go.jp/test', originalHash: hash, contentHash: hash, observedAt: '2026-01-01T00:00:00Z', publishedAt: '2024-01-01' };
  const input: EvidenceEvaluationInput = { schemaVersion: 'evidence-evaluation/v1', mode: 'test-only', options: { domain: 'economy', direction: 'benefit', period: 4, asOf: '2026-01-01', weights: { economy: 70, technology: 30 } }, people: [{ id: 'person1', name: 'テスト専用人物' }], materials: [material], actions: [action], assessments: [assessment] };
  const trusted: TrustedContext = { readMaterial: async () => ({ ...material, text }), resolvedPersonIds: new Set(['person1']), verifiedActionIds: new Set([action.actionId]), verifiedAssessmentIds: new Set(['analysis1']), verifiedActionRevisions: new Map([[action.actionId, action.revisionId]]), verifiedAssessmentRevisions: new Map([['analysis1', await assessmentRevision(assessment)]]) };
  return { input, trusted };
}
describe('実根拠入口：テスト専用fixture、公開許可ではありません', () => {
  it('独立検証された一致引用だけを算定します', async () => {
    const { input, trusted } = await fixture();
    const result = await evaluateEvidence(input, trusted);
    expect(result.rows[0].score).toBe(2);
    expect(result.publicationStatus).toBe('requires_human_review');
  });
  it('入力の自己検証宣言を拒否します', async () => {
    const { input, trusted } = await fixture();
    Object.assign(input.actions[0], { verified: true });
    await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
  });
  it('実入力の独立検証がない場合は未評価です', async () => {
    const { input, trusted } = await fixture(); input.mode = 'real';
    trusted.verifiedActionIds = new Set();
    const result = await evaluateEvidence(input, trusted);
    expect(result.rows[0].score).toBeNull(); expect(result.held.length).toBeGreaterThan(0);
  });
  it('保存本文の引用改竄とハッシュ不一致を保留します', async () => {
    const { input, trusted } = await fixture();
    const read = trusted.readMaterial;
    trusted.readMaterial = async id => ({ ...(await read(id))!, text: '別の本文' });
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it.each(['unknown', 'not_voted'] as const)('個人の%sは賛否へ補完しません', async position => {
    const { input, trusted } = await fixture(); input.actions[0].position = position;
    const { actionId: _a, revisionId: _r, ...semantic } = input.actions[0]; input.actions[0].revisionId = await actionRevision(semantic);
    trusted.verifiedActionRevisions = new Map([[input.actions[0].actionId, input.actions[0].revisionId]]);
    const result = await evaluateEvidence(input, trusted);
    expect(result.rows[0].score).toBeNull(); expect(result.held[0].reason).toContain('賛否');
  });
  it('反対票を反対方向の得点へ反転しません', async () => {
    const { input, trusted } = await fixture(); input.actions[0].position = 'against';
    const { actionId: _a, revisionId: _r, ...semantic } = input.actions[0]; input.actions[0].revisionId = await actionRevision(semantic);
    trusted.verifiedActionRevisions = new Map([[input.actions[0].actionId, input.actions[0].revisionId]]);
    input.options.direction = 'harm';
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it('同一入力の重複を加点せず異なる改訂は拒否します', async () => {
    const { input, trusted } = await fixture(); input.actions.push({ ...input.actions[0] });
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBe(2);
    input.actions[1] = { ...input.actions[1], description: '訂正' };
    const { actionId: _a, revisionId: _r, ...semantic } = input.actions[1]; input.actions[1].revisionId = await actionRevision(semantic);
    await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
  });
  it('同じ人物と政策の対立した立場は保留します', async () => {
    const { input, trusted } = await fixture();
    const { actionId: _a, revisionId: _r, ...semantic } = input.actions[0];
    const other = { ...semantic, sourceActionId: 'v2', position: 'against' as const };
    const action = { ...other, actionId: await actionIdentity(other), revisionId: await actionRevision(other) };
    input.actions.push(action); trusted.verifiedActionIds = new Set(input.actions.map(a => a.actionId));
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it('期間境界を含み過去行動の訂正を現在へ加点しません', async () => {
    const { input, trusted } = await fixture(); input.actions[0].actionDate = '2022-01-01';
    const revise = async () => { const { actionId: _a, revisionId: _r, ...semantic } = input.actions[0]; input.actions[0].revisionId = await actionRevision(semantic); trusted.verifiedActionRevisions = new Map([[input.actions[0].actionId, input.actions[0].revisionId]]); };
    await revise(); expect((await evaluateEvidence(input, trusted)).rows[0].score).toBe(2);
    input.actions[0].actionDate = '2021-12-31'; await revise();
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it('丸めた0点と未評価を区別し全重み0は未評価です', async () => {
    const { input, trusted } = await fixture(); input.options.domain = 'overall'; input.options.weights = { economy: .001, technology: 100 };
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBe(0);
    input.options.weights = { economy: 0, technology: 0 };
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it('独立した両方向分析と複数分野を無制限に二重加算しません', async () => {
    const { input, trusted } = await fixture();
    input.assessments.push({ ...input.assessments[0], id: 'analysis2', direction: 'harm', impact: 1 });
    trusted.verifiedAssessmentIds = new Set(['analysis1', 'analysis2']);
    trusted.verifiedAssessmentRevisions = new Map(await Promise.all(input.assessments.map(async a => [a.id, await assessmentRevision(a)] as const)));
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBe(2);
    input.options.direction = 'harm'; expect((await evaluateEvidence(input, trusted)).rows[0].score).toBe(1);
    input.assessments.push({ ...input.assessments[0], id: 'duplicate-axis' });
    await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
  });
  it('同じIDでも検証後の行動・分析の訂正は保留します', async () => {
    const { input, trusted } = await fixture();
    input.actions[0].description = '改訂後の説明';
    const { actionId: _a, revisionId: _r, ...semantic } = input.actions[0]; input.actions[0].revisionId = await actionRevision(semantic);
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
    trusted.verifiedActionRevisions = new Map([[input.actions[0].actionId, input.actions[0].revisionId]]);
    input.assessments[0].impact = 3;
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it('人物・資料の重複IDを拒否します', async () => {
    const { input, trusted } = await fixture(); input.people.push({ ...input.people[0] });
    await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
    input.people.pop(); input.materials.push({ ...input.materials[0] });
    await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
  });
  it('観測日時なしの資料と評価改訂日時なしの分析を拒否します', async () => {
    const { input, trusted } = await fixture();
    const invalid = structuredClone(input); delete (invalid.materials[0] as Partial<typeof invalid.materials[0]>).observedAt;
    await expect(evaluateEvidence(invalid, trusted)).rejects.toThrow();
    const invalidAnalysis = structuredClone(input); delete (invalidAnalysis.assessments[0] as Partial<typeof invalidAnalysis.assessments[0]>).evaluatedAt;
    await expect(evaluateEvidence(invalidAnalysis, trusted)).rejects.toThrow();
  });
  it('改訂検証があっても原資料と一致しない引用を保留します', async () => {
    const { input, trusted } = await fixture();
    const originalAssessmentRevision = await assessmentRevision(input.assessments[0]);
    input.actions[0].quotes[0] = { ...input.actions[0].quotes[0], text: '偽'.repeat(input.actions[0].quotes[0].text.length) };
    const { actionId: _a, revisionId: _r, ...semantic } = input.actions[0]; input.actions[0].revisionId = await actionRevision(semantic);
    trusted.verifiedActionRevisions = new Map([[input.actions[0].actionId, input.actions[0].revisionId]]);
    expect(await assessmentRevision(input.assessments[0])).toBe(originalAssessmentRevision);
    expect(trusted.verifiedAssessmentRevisions.get(input.assessments[0].id)).toBe(originalAssessmentRevision);
    const result = await evaluateEvidence(input, trusted);
    expect(result.rows[0].score).toBeNull();
    expect(result.held).toEqual([{ personId: 'person1', policyId: 'p1', reason: '行動または引用が未検証です' }]);
  });
  it('人物同定または影響分析の独立検証がない場合は保留します', async () => {
    const { input, trusted } = await fixture(); trusted.resolvedPersonIds = new Set();
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
    trusted.resolvedPersonIds = new Set(['person1']); trusted.verifiedAssessmentIds = new Set();
    expect((await evaluateEvidence(input, trusted)).rows[0].score).toBeNull();
  });
  it('任意の安定ID、不正重み、不正な日付を拒否します', async () => {
    const { input, trusted } = await fixture();
    input.options.weights.economy = Number.NaN; await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
    input.options.weights.economy = 70; input.actions[0].actionDate = '2024-02-31'; await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
    input.actions[0].actionDate = '2024-01-01'; input.actions[0].actionId = '0'.repeat(64); await expect(evaluateEvidence(input, trusted)).rejects.toThrow();
  });
});
