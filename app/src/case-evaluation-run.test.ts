import { describe, expect, it } from 'vitest';
import caseSource from '../../data/distribution/case-source.json';
import { FINANCIAL_REVIVAL_DRAFT, type CaseEvaluationSpec } from './case-evaluation';

// 人工の原本・人工の名簿だけを使う。実在の登録原本・名簿・在職記録は使わない。氏名は評価仕様にすでにある「竹中平蔵」以外は架空。
const moduleUrl = new URL('../../scripts/case_evaluation_run.mjs', import.meta.url).href;
const run = await import(/* @vite-ignore */ moduleUrl);
const fsModule = 'node:fs/promises', osModule = 'node:os', pathModule = 'node:path', cryptoModule = 'node:crypto';
const { mkdtemp, mkdir, writeFile, rm, readFile, stat } = await import(/* @vite-ignore */ fsModule);
const { tmpdir } = await import(/* @vite-ignore */ osModule);
const { join } = await import(/* @vite-ignore */ pathModule);
const { createHash } = await import(/* @vite-ignore */ cryptoModule);
const repoRoot = new URL('../../', import.meta.url).pathname;

const ROSTER = 'https://example.test/artificial-roster';
const names = { 'takenaka-heizo': '竹中平蔵', 'ito-20021030': '試験乙', 'ito-20050525': '試験丁', 'okamoto-fsa': '試験丙' } as const;
const rosterText = '人工名簿。竹中平蔵 金融担当大臣。試験乙 副大臣。試験丁 大臣。試験丙 室長。';

function artificialSpec(change: (spec: CaseEvaluationSpec) => void = () => {}): CaseEvaluationSpec {
  const spec = structuredClone(FINANCIAL_REVIVAL_DRAFT);
  for (const p of spec.people) p.name = names[p.personId as keyof typeof names];
  change(spec);
  return spec;
}

async function register(root: string, url: string, text: string, n: number) {
  const dir = join(root, `task-${n}`, `2026-10-09-${n}`);
  await mkdir(dir, { recursive: true });
  const bytes = new TextEncoder().encode(text);
  await writeFile(join(dir, 'original.txt'), bytes);
  await writeFile(join(dir, 'record.json'), JSON.stringify({ schema_version: 'external-material/v1', source_url: url, observed_at: '2026-10-09T00:00:00+00:00',
    saved_filename: 'original.txt', bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') }));
}

async function fixture(spec: CaseEvaluationSpec, roster: Record<string, { materialUrl: string; quote: string }[]>) {
  const dir = await mkdtemp(join(tmpdir(), 'case-run-'));
  const materialRoot = join(dir, 'materials');
  const quotes = new Map<string, string[]>();
  for (const c of [...caseSource.citations, ...spec.assessments.flatMap(a => a.comparison?.citations ?? [])]) quotes.set(c.url, [...(quotes.get(c.url) ?? []), c.quote]);
  let n = 0;
  for (const [url, list] of quotes) await register(materialRoot, url, `人工の保存本文。${list.join('。人工の区切り。')}。人工の後続文。`, n++);
  await register(materialRoot, ROSTER, rosterText, n++);
  const identities = join(dir, 'identities.json');
  await writeFile(identities, JSON.stringify({ schemaVersion: 'case-identities/v1', people: roster }));
  const casePath = join(dir, 'case-source.json');
  await writeFile(casePath, JSON.stringify(caseSource));
  const outputDir = join(repoRoot, '.local', `test-case-run-${Math.random().toString(16).slice(2)}`);
  const args = ['--case-source', casePath, '--material-root', materialRoot, '--identities', identities, '--output-dir', outputDir];
  return { args, outputDir, cleanup: () => Promise.all([rm(dir, { recursive: true, force: true }), rm(outputDir, { recursive: true, force: true })]) };
}

const allResolved = () => Object.fromEntries(Object.entries(names).map(([id, name]) => [id, [{ materialUrl: ROSTER, quote: `${name} ` }]]));

describe('事例評価の非公開実行入口', () => {
  it('人工の登録原本から、独立検証つきのレビュー資料と点数を作る', async () => {
    const spec = artificialSpec();
    const f = await fixture(spec, allResolved());
    try {
      const { summary, review, release } = await run.runCaseEvaluation({ args: f.args, spec });
      expect(summary).toMatchObject({ resolvedPeople: 4, verifiedActions: 5, verifiedAssessments: 1, assessedActions: 2, held: 2, publicationStatus: 'requires_human_review' });
      expect(summary.scores).toHaveLength(4);
      // 岡本（context）は役割上の保留。2005-05-25の候補は観測窓の後なので点数にしない。
      expect(summary.scores.filter((s: { score: number | null }) => s.score !== null && s.score > 0)).toHaveLength(2);
      expect(summary.scores.find((s: { personId: string }) => s.personId === 'ito-20021030')).toMatchObject({ score: 0.5 });
      expect(summary.scores.find((s: { personId: string }) => s.personId === 'ito-20050525')).toMatchObject({ score: null });
      expect(release.result.held).toEqual(expect.arrayContaining([
        expect.objectContaining({ personId: 'ito-20050525', reason: '結果観測後の行動は因果寄与へ結べません' }),
        expect.objectContaining({ personId: 'okamoto-fsa', reason: '行動または引用が未検証です' }),
      ]));
      expect(review.m2Status).toBe('requires_independent_readback');
      expect(((await stat(join(f.outputDir, 'run-summary.json'))).mode & 0o777)).toBe(0o600);
      expect(JSON.parse(await readFile(join(f.outputDir, 'identity-audit.json'), 'utf8')).rows.every((r: { status: string }) => r.status === 'resolved')).toBe(true);
    } finally { await f.cleanup(); }
  }, 120_000);

  it('名簿の引用が無い人物は照合済みにならず、その行は保留になる', async () => {
    const spec = artificialSpec();
    const roster = allResolved();
    roster['ito-20021030'] = [{ materialUrl: ROSTER, quote: '試験乙 事務次官' }];
    const f = await fixture(spec, roster);
    try {
      const { summary } = await run.runCaseEvaluation({ args: f.args, spec });
      expect(summary.resolvedPeople).toBe(3);
      expect(summary.held).toBeGreaterThan(0);
      expect(summary.scores.find((s: { personId: string }) => s.personId === 'ito-20021030')).toMatchObject({ score: null, heldCount: 1 });
      expect(summary.scores.filter((s: { score: number | null }) => s.score !== null)).toHaveLength(1);
      const audit = JSON.parse(await readFile(join(f.outputDir, 'identity-audit.json'), 'utf8')).rows;
      expect(audit.find((r: { personId: string }) => r.personId === 'ito-20021030').status).toBe('unresolved');
      expect(audit.find((r: { personId: string }) => r.personId === 'ito-20050525').status).toBe('resolved');
    } finally { await f.cleanup(); }
  }, 120_000);

  it('引用に評価仕様の氏名が無い人物や台帳に無い人物も照合済みにならない', async () => {
    const spec = artificialSpec();
    const roster = allResolved();
    roster['ito-20021030'] = [{ materialUrl: ROSTER, quote: '副大臣。' }];
    delete (roster as Record<string, unknown>)['okamoto-fsa'];
    const f = await fixture(spec, roster);
    try {
      const { summary } = await run.runCaseEvaluation({ args: f.args, spec });
      expect(summary.resolvedPeople).toBe(2);
      const audit = JSON.parse(await readFile(join(f.outputDir, 'identity-audit.json'), 'utf8')).rows;
      expect(audit.find((r: { personId: string }) => r.personId === 'ito-20021030').status).toBe('unresolved');
      expect(audit.find((r: { personId: string }) => r.personId === 'ito-20050525').status).toBe('resolved');
    } finally { await f.cleanup(); }
  }, 120_000);

  it('系列を持たず手で影響段階を置いた分析は独立に確認できず、点数を作らない', async () => {
    const spec = artificialSpec(s => { delete s.assessments[0].series; s.assessments[0].impact = 2; });
    const f = await fixture(spec, allResolved());
    try {
      const { summary } = await run.runCaseEvaluation({ args: f.args, spec });
      expect(summary.verifiedAssessments).toBe(0);
      expect(summary.scores.every((s: { score: number | null }) => s.score === null)).toBe(true);
    } finally { await f.cleanup(); }
  }, 120_000);

  it('判定ルールと影響段階が食い違う入力は、独立検証が受領書を作らず止まる', async () => {
    const spec = artificialSpec();
    const bundle = await run.loadBundle();
    const f = await fixture(spec, allResolved());
    try {
      const { release } = await run.runCaseEvaluation({ args: f.args, spec });
      const tampered = structuredClone(release.input.evidenceEvaluation);
      tampered.assessments[0].impact = tampered.assessments[0].impact === 3 ? 2 : 3;
      const registered = await run.indexRegistered(f.args[3]);
      const source = JSON.parse(await readFile(f.args[1], 'utf8'));
      const refs = run.citationList(source, spec).map((c: { id: string; url: string }) => ({ id: c.id, ...registered.get(c.url), selector: { kind: 'registered-text' } }));
      const independentTexts = await run.readRefs(refs, f.args[3]);
      await expect(run.verifyCaseEvidence({ snapshot: tampered, inputHash: 'a'.repeat(64), source, spec, people: {}, bundle, independent: independentTexts, rosterTexts: new Map() })).rejects.toThrow();
    } finally { await f.cleanup(); }
  }, 120_000);

  it('読み戻しの対象は行動・評価・比較から参照される引用だけで、参照されない引用は登録原本がなくても止めない', async () => {
    const spec = artificialSpec();
    const ids = run.citationList(caseSource, spec).map((c: { id: string }) => c.id);
    expect(ids).not.toContain('fsaRules');
    expect(ids).toEqual(expect.arrayContaining(['danwa20050525', 'ito20050525', 'okamoto20021219', 'fsaNplTable1']));
    const unused = caseSource.citations.filter(c => !ids.includes(c.id)).map(c => c.id);
    expect(unused).toEqual(['fsaRules', 'ito20021003', 'ito20040927', 'fsa20050511']);
    // fsaRules だけ登録しない原本で全件実行が止まらない。
    const f = await fixture(spec, allResolved());
    try {
      const { rm: rmFile } = await import(/* @vite-ignore */ fsModule);
      const registered = await run.indexRegistered(f.args[3]);
      const rules = registered.get(caseSource.citations.find(c => c.id === 'fsaRules')!.url);
      await rmFile(rules.recordPath);
      const { summary } = await run.runCaseEvaluation({ args: f.args, spec });
      expect(summary.verifiedActions).toBe(5);
    } finally { await f.cleanup(); }
  }, 120_000);

  it('未知・重複の引数と自己申告の受領書は受け付けない', () => {
    const ok = ['--case-source', 'a', '--material-root', 'b', '--identities', 'c', '--output-dir', 'd'];
    expect(run.parseArgs(ok)['--output-dir']).toBe('d');
    expect(() => run.parseArgs([...ok.slice(0, 6), '--receipt', 'x.json'])).toThrow();
    expect(() => run.parseArgs([...ok.slice(0, 6), '--identities', 'x'])).toThrow();
    expect(() => run.parseArgs(ok.slice(0, 6))).toThrow();
  });
});
