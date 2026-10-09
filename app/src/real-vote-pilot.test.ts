import { describe, expect, it } from 'vitest';
import { evaluateEvidence, assessmentRevision } from './evidence-evaluation';

const moduleUrl = new URL('../../scripts/real_vote_pilot.mjs', import.meta.url).href;
const pilot = await import(/* @vite-ignore */ moduleUrl);
const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path', cryptoModule = 'node:crypto';
const { mkdtemp, mkdir, writeFile, rm } = await import(/* @vite-ignore */ fsModule);
const { tmpdir } = await import(/* @vite-ignore */ osModule);
const { join } = await import(/* @vite-ignore */ pathModule);
const { createHash } = await import(/* @vite-ignore */ cryptoModule);
const voteKey = (name: string, policyId = '221-53', date = '2026-07-10') =>
  createHash('sha256').update(JSON.stringify([policyId, date, name.replace(/\s+/gu, '')])).digest('hex');

const material = (id: string, position: 'for' | 'against' | 'not_voted' | 'unknown', name: string) => ({
  id, text: `${position} ${name}`, url: 'https://www.sangiin.go.jp/japanese/touhyoulist/221/221-0710-v001.htm',
  originalHash: 'a'.repeat(64), contentHash: 'b'.repeat(64), observedAt: '2026-10-03T00:00:00Z', publishedAt: null,
  sourceRecord: { _kind: 'vote', id, nameText: name, date: '2026-07-10', policyId: '221-53',
    position, locator: 'HTML line=1; allPublishedRowsConfirmed=True' },
});

describe('有限の実投票入口', () => {
  it('分析資料と独立callbackを接続し、人工の複数人物だけを採点します', async () => {
    const rows = [material('r1', 'for', '試験 一郎'), material('r2', 'against', '試験 二郎')];
    rows.forEach(row => { row.contentHash = createHash('sha256').update(row.text).digest('hex'); });
    const profiles = new Map(rows.map((row, i) => [voteKey(row.sourceRecord.nameText), { id: `person${i}`, name: row.sourceRecord.nameText }]));
    const analysis = { ...material('analysis', 'for', '人工分析'), text: '人工の影響・反証資料' };
    analysis.contentHash = createHash('sha256').update(analysis.text).digest('hex');
    const assessments = ['for', 'against'].map((position, i) => ({ id: `assessment${i}`, policyId: '221-53', policyVersion: '221-53@2026-07-10', position, domain: 'economy', direction: 'benefit', impact: 2, rationale: '人工の理由', counterEvidence: '人工反証', alternativeExplanation: '人工代替説明', criterionVersion: 'fixture1', analysisVersion: 'fixture1', evaluatedAt: '2026-10-03T00:00:00Z', quotes: [{ materialId: analysis.id, start: 0, end: analysis.text.length, text: analysis.text }] }));
    const { input } = pilot.makePilotInput(rows, profiles, '2026-10-03', '221-53', 4, { assessments, analysisMaterials: [analysis] });
    expect(input.assessments).toHaveLength(2);
    const read = [...rows, analysis];
    const check = async (candidate = input, verifier?: (value: any) => Promise<any>) => {
      const receipt = await pilot.verifyPilotAssessments(candidate, rows, profiles, 'c'.repeat(64), [analysis], verifier);
      return evaluateEvidence(candidate, { readMaterial: async id => read.find(m => m.id === id) ?? null, resolvedPersonIds: new Set(receipt.resolvedPersonIds), verifiedActionIds: new Set(receipt.actionRevisions.map((r: any) => r.id)), verifiedActionRevisions: new Map(receipt.actionRevisions.map((r: any) => [r.id, r.revisionId])), verifiedAssessmentIds: new Set(receipt.assessmentRevisions.map((r: any) => r.id)), verifiedAssessmentRevisions: new Map(receipt.assessmentRevisions.map((r: any) => [r.id, r.revisionId])) });
    };
    const independentlyReviewed = await Promise.all(assessments.map(async a => ({ id: a.id, revisionId: await assessmentRevision(a as any) })));
    const verifier = async () => independentlyReviewed;
    expect((await check()).coverage.assessedActions).toBe(0);
    const materialsOnly = structuredClone(input); materialsOnly.assessments = [];
    expect((await check(materialsOnly)).coverage.assessedActions).toBe(0);
    expect((await check(input, async () => [])).coverage.assessedActions).toBe(0);
    const success = await check(input, verifier);
    expect(success.coverage.assessedActions).toBe(2);
    expect(success.rows.map(row => row.score)).toEqual([0.5, 0.5]);
    expect(success.publicationStatus).toBe('requires_human_review');
    for (const field of ['policyVersion', 'position', 'domain', 'direction']) {
      const wrong = structuredClone(input); wrong.assessments[0][field] = { policyVersion: 'wrong', position: 'against', domain: 'technology', direction: 'harm' }[field];
      wrong.assessments = [wrong.assessments[0]];
      const fresh = async () => [{ id: wrong.assessments[0].id, revisionId: await assessmentRevision(wrong.assessments[0]) }];
      expect((await check(wrong, fresh)).rows.find(row => row.person.id === 'person0')?.score).toBeNull();
    }
    for (const field of ['impact', 'rationale', 'criterionVersion', 'quotes']) {
      const revised = structuredClone(input); revised.assessments[0][field] = field === 'impact' ? 3 : field === 'quotes' ? [{ ...revised.assessments[0].quotes[0], text: '改竄引用' }] : '改訂';
      await expect(check(revised, verifier)).rejects.toThrow();
    }
    const changed = structuredClone(input); changed.people[0].name = '別人';
    await expect(check(changed, verifier)).rejects.toThrow('不一致');
    const selfApproved = structuredClone(input); selfApproved.assessments[0].verified = true;
    await expect(check(selfApproved)).rejects.toThrow();
    const quoteOnly = structuredClone(input); quoteOnly.assessments[0].rationale = '';
    await expect(check(quoteOnly)).rejects.toThrow('影響分析');
    const editedVote = structuredClone(input); editedVote.actions[0].position = 'against';
    await expect(check(editedVote, verifier)).rejects.toThrow('不一致');
    const badOriginal = { ...analysis, text: '原本の引用不一致' };
    await expect(pilot.verifyPilotAssessments(input, rows, profiles, 'c'.repeat(64), [badOriginal], verifier)).rejects.toThrow('引用');
    const outOfRange = structuredClone(input); outOfRange.assessments[0].quotes[0].end++;
    const freshOutOfRange = async () => Promise.all(outOfRange.assessments.map(async (a: any) => ({ id: a.id, revisionId: await assessmentRevision(a) })));
    await expect(pilot.verifyPilotAssessments(outOfRange, rows, profiles, 'c'.repeat(64), [analysis], freshOutOfRange)).rejects.toThrow('引用');
    for (const invalid of [[independentlyReviewed[0], independentlyReviewed[0]], [{ id: 'missing', revisionId: 'a'.repeat(64) }], [{ ...independentlyReviewed[0], revisionId: 'a'.repeat(64) }]]) {
      await expect(pilot.verifyPilotAssessments(input, rows, profiles, 'c'.repeat(64), [analysis], async () => invalid)).rejects.toThrow('分析検証');
    }
    for (const position of ['unknown', 'not_voted'] as const) {
      const heldRows = structuredClone(rows); heldRows[0].sourceRecord.position = position;
      const heldInput = pilot.makePilotInput(heldRows, profiles, '2026-10-03', '221-53', 4, { assessments, analysisMaterials: [analysis] }).input;
      const receipt = await pilot.verifyPilotAssessments(heldInput, heldRows, profiles, 'c'.repeat(64), [analysis], verifier);
      const result = await evaluateEvidence(heldInput, { readMaterial: async id => read.find(m => m.id === id) ?? null, resolvedPersonIds: new Set(receipt.resolvedPersonIds), verifiedActionIds: new Set(receipt.actionRevisions.map((r: any) => r.id)), verifiedActionRevisions: new Map(receipt.actionRevisions.map((r: any) => [r.id, r.revisionId])), verifiedAssessmentIds: new Set(receipt.assessmentRevisions.map((r: any) => r.id)), verifiedAssessmentRevisions: new Map(receipt.assessmentRevisions.map((r: any) => [r.id, r.revisionId])) });
      expect(result.rows.find(row => row.person.id === 'person0')?.score).toBeNull();
    }
  });
  it('賛成・反対・投票なしを全行保持し、影響分析を創作しません', () => {
    const rows = [material('r1', 'for', '試験 一郎'), material('r2', 'against', '試験 二郎'),
      material('r3', 'not_voted', '試験 三郎')];
    const resolved = new Map([[voteKey('試験 一郎'), { id: 'sangiin-1234567', name: '試験 一郎', house: '参議院' }]]);
    const { input, counts } = pilot.makePilotInput(rows, resolved, '2026-10-03', '221-53');
    expect(counts).toEqual({ for: 1, against: 1, not_voted: 1, unknown: 0 });
    expect(input.actions).toHaveLength(3);
    expect(input.assessments).toEqual([]);
    expect(input.people[1].id).toMatch(/^vote-observation-[a-f0-9]{64}$/);
    expect(pilot.verifyPilot(input, rows, resolved, 'c'.repeat(64)).resolvedPersonIds).toEqual(['sangiin-1234567']);
  });

  it('投票行の訂正を同じ行動の別改訂として再検証します', () => {
    const before = material('r1', 'for', '試験 一郎');
    const first = pilot.makePilotInput([before], new Map(), '2026-10-03', '221-53').input;
    // 登録原本の訂正で行IDと資料IDが変わる実経路を模擬する。
    const corrected = material('r1-revised', 'against', '試験 一郎');
    corrected.originalHash = 'c'.repeat(64);
    const second = pilot.makePilotInput([corrected], new Map(), '2026-10-03', '221-53').input;
    expect(second.actions[0].actionId).toBe(first.actions[0].actionId);
    expect(second.actions[0].revisionId).not.toBe(first.actions[0].revisionId);
    expect(() => pilot.verifyPilot(first, [corrected], new Map(), 'c'.repeat(64))).toThrow('不一致');
    expect(pilot.verifyPilot(second, [corrected], new Map(), 'c'.repeat(64)).actionRevisions[0].revisionId)
      .toBe(second.actions[0].revisionId);
  });

  it('公式議員一覧・個別プロフィール・通常選挙の三点を一致させます', async () => {
    const root = await mkdtemp(join(tmpdir(), 'vote-identity-'));
    const save = async (name: string, url: string, html: string) => {
      const dir = join(root, name); await mkdir(dir);
      await writeFile(join(dir, 'original.html'), html, 'utf8');
      const bytes = new TextEncoder().encode(html);
      const record = { schema_version: 'external-material/v1', source_url: url, saved_filename: 'original.html',
        bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
      const path = join(dir, 'record.json'); await writeFile(path, JSON.stringify(record), 'utf8'); return path;
    };
    try {
      const listRecordPath = await save('list', 'https://www.sangiin.go.jp/japanese/joho1/kousei/giin/221/giin.htm',
        '<a href="../profile/1234567.htm" class="Graylink">試験　　一郎</a>');
      const profileRecordPath = await save('profile', 'https://www.sangiin.go.jp/japanese/joho1/kousei/giin/profile/1234567.htm',
        '<h1 class="profile-name">試験　一郎（しけん）</h1><dd>通常選挙／比例代表選出／令和4年／当選 1 回</dd>');
      const manifest = { schemaVersion: 'vote-identities/v1', listRecordPath,
        profiles: [{ voteKey: voteKey('試験 一郎'), profileId: '1234567', electionYear: 2022,
          electionKind: 'regular', district: '比例代表', profileRecordPath }] };
      const votes = [material('r1', 'for', '試験 一郎')];
      expect((await pilot.resolveProfiles(manifest, votes, root)).get(voteKey('試験 一郎')).electionIds)
        .toEqual(['sangiin-regular-2022-比例代表']);
      expect((await pilot.resolveProfiles(manifest, [material('r1-corrected', 'against', '試験 一郎')], root))
        .get(voteKey('試験 一郎')).id).toBe('sangiin-1234567');
      await expect(pilot.resolveProfiles({ ...manifest, profiles: [{ ...manifest.profiles[0], electionYear: 2025 }] },
        votes, root)).rejects.toThrow('一致');
      await expect(pilot.resolveProfiles({ ...manifest, profiles: [{ ...manifest.profiles[0], electionKind: 'supplemental' }] },
        votes, root)).rejects.toThrow('不正');
      const historicalRecord = await save('historical', 'https://www.sangiin.go.jp/japanese/joho1/kousei/giin/profile/1234567.htm',
        '<h1 class="profile-name">試験　一郎（しけん）</h1><dd>通常選挙／比例代表選出／平成22年、28年、令和4年／当選 3 回</dd>');
      const oldVote = material('old-row', 'for', '試験 一郎');
      oldVote.sourceRecord.policyId = '200-8';
      oldVote.sourceRecord.date = '2019-11-29';
      const historicalEntry = { ...manifest.profiles[0], voteKey: voteKey('試験 一郎', '200-8', '2019-11-29'),
        mandateYear: 2016, profileRecordPath: historicalRecord };
      expect((await pilot.resolveProfiles({ ...manifest, profiles: [historicalEntry] }, [oldVote], root))
        .get(historicalEntry.voteKey).id).toBe('sangiin-1234567');
      const { mandateYear: _mandateYear, ...missingMandate } = historicalEntry;
      await expect(pilot.resolveProfiles({ ...manifest, profiles: [missingMandate] }, [oldVote], root))
        .rejects.toThrow('投票時');
      const sameYearRecord = await save('same-year', 'https://www.sangiin.go.jp/japanese/joho1/kousei/giin/profile/1234567.htm',
        '<h1 class="profile-name">試験　一郎（しけん）</h1><dd>通常選挙／比例代表選出／令和元年／当選 1 回</dd>');
      await expect(pilot.resolveProfiles({ ...manifest, profiles: [{ ...historicalEntry,
        electionYear: 2019, mandateYear: 2019, profileRecordPath: sameYearRecord }] }, [oldVote], root))
        .rejects.toThrow('投票時');
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
