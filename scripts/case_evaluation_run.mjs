/**
 * 金融再生プログラムの事例評価（FINANCIAL_REVIVAL_DRAFT）を、登録済み原本から非公開レビュー資料へつなぐローカル専用の実行入口。
 * 何も公開・送信しない。出力は repo の .local 配下だけ。点数は公開前に人間レビューが必要（requires_human_review）。
 *
 *   node scripts/case_evaluation_run.mjs \
 *     --case-source data/distribution/case-source.json \
 *     --material-root .local/external-materials \
 *     --identities .local/identities/fsa-financial-revival.json \
 *     --output-dir .local/case-runs/fsa-financial-revival-2002
 *
 * 登録原本の形式（scripts/register_external_material.py）: <material-root>/<task>/<id>/record.json
 * （schema_version=external-material/v1, source_url, sha256, bytes, observed_at, saved_filename）。
 * 引用の出典は source_url の一致で登録原本へ結び付ける。同じURLに別ハッシュの登録が複数あれば曖昧として停止する。
 * 本文は scripts.read_evidence_materials（registered-text）が、ハッシュ照合のうえ厳格UTF-8で再読したものだけを使う。
 *
 * 人物照合台帳（identity manifest）の形式:
 *   {
 *     "schemaVersion": "case-identities/v1",
 *     "people": {
 *       "<評価仕様の personId>": [
 *         { "materialUrl": "<登録済み公式名簿ページのURL>", "quote": "<その本文に逐語で現れる一節>" }
 *       ]
 *     }
 *   }
 * 人物が「照合済み」になるのは、(1) 台帳に1件以上あり、(2) 全件の materialUrl が登録原本に対応し、
 * (3) 独立に再読した本文に quote が逐語で含まれ、(4) 評価仕様の name が quote に含まれる（空白は無視）ときだけ。
 * 1件でも満たさなければ未照合で、その人物の行は保留になる。名前だけ・台帳の自己申告だけでは照合済みにならない。
 * 在職時期や役職まで読めるよう、quote には名前と役職・在任期間を含む一節を選ぶこと（人間レビューの確認項目）。
 *
 * 独立検証（verifyEvidence）は実行側の関数で、原本を readMaterials とは別に再読して受領書を作る。
 * 受領書JSONをCLI入力から受け取ることはしない。受領書に載るのは次だけ:
 *   - 照合済み人物
 *   - 全引用が [start,end) で再読本文と一致し、入力が原本から再構成できる行動
 *   - impact が仕様の系列から再計算した judgeImpact(series).stage と等しく、引用も一致する分析
 *     （系列を持たず影響段階を手で入れた分析は独立に確かめられないため載せない）
 */
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { chmod, lstat, mkdir, mkdtemp, rm, readFile, readdir, realpath, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { runEvidencePipeline, writeReviewPacket } from './evidence_pipeline.mjs';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const digest = value => createHash('sha256').update(value).digest('hex');
const canonical = value => Array.isArray(value)
  ? `[${value.map(canonical).join(',')}]`
  : value && typeof value === 'object'
    ? `{${Object.keys(value).filter(k => value[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`
    : JSON.stringify(value);
const requireThat = (condition, reason) => { if (!condition) throw new Error(reason); };
const compact = value => value.replace(/\s+/gu, '');
const HELP = `使い方: node scripts/case_evaluation_run.mjs --case-source <case-source.json> --material-root <登録原本の保管先> --identities <人物照合台帳JSON> --output-dir <repo/.local配下>
ローカル専用。公開・送信はしません。人物照合台帳の形式はこのファイルの冒頭コメントを参照してください。`;

export function parseArgs(args) {
  const required = ['--case-source', '--material-root', '--identities', '--output-dir'];
  requireThat(args.length === 8, `必要な引数: ${required.join(' ')}`);
  const values = {};
  for (let i = 0; i < args.length; i += 2) {
    requireThat(required.includes(args[i]) && !Object.hasOwn(values, args[i]) && args[i + 1] && !args[i + 1].startsWith('--'), 'CLI引数が不正または重複しています');
    values[args[i]] = args[i + 1];
  }
  requireThat(required.every(k => Object.hasOwn(values, k)), `必要な引数: ${required.join(' ')}`);
  return values;
}

/** 登録原本の台帳を引く。URLに対して別ハッシュの登録が複数あれば曖昧として止める。 */
export async function indexRegistered(materialRoot) {
  const root = await realpath(materialRoot);
  const byUrl = new Map();
  const dirs = async path => (await readdir(path, { withFileTypes: true }).catch(() => [])).filter(e => e.isDirectory() && !e.isSymbolicLink()).map(e => join(path, e.name)).sort();
  for (const task of await dirs(root)) for (const item of await dirs(task)) {
    const recordPath = join(item, 'record.json');
    let record;
    try {
      if ((await lstat(recordPath)).isSymbolicLink()) continue;
      record = JSON.parse(await readFile(recordPath, 'utf8'));
    } catch { continue; }
    if (record?.schema_version !== 'external-material/v1' || typeof record.source_url !== 'string' || !/^[a-f0-9]{64}$/.test(record.sha256 ?? '')) continue;
    const found = byUrl.get(record.source_url);
    if (found && found.originalHash !== record.sha256) throw new Error(`同じ出典URLに別ハッシュの登録原本があり曖昧です: ${record.source_url}`);
    if (!found) byUrl.set(record.source_url, { recordPath, originalHash: record.sha256 });
  }
  return byUrl;
}

/** Python側で登録原本をハッシュ照合して再読する。呼び出しごとに別プロセス。 */
export function readRefs(refs, materialRoot) {
  return new Promise((accept, reject) => {
    const child = spawn(process.platform === 'win32' ? 'python' : 'python3', ['-m', 'scripts.read_evidence_materials', '--material-root', materialRoot],
      { cwd: repoRoot, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' }, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', size = 0;
    const timer = setTimeout(() => { child.kill(); reject(new Error('原本照合が時間切れです')); }, 60_000);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      size += Buffer.byteLength(chunk);
      if (size > 64_000_000) { child.kill(); reject(new Error('原本照合の出力上限を超えました')); } else output += chunk;
    });
    child.stderr.resume();
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error('登録原本を再読できません（ハッシュ不一致または形式不正）'));
      else { try { accept(JSON.parse(output)); } catch (error) { reject(error); } }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(canonical(refs));
  });
}

const refFor = (id, found) => ({ id, recordPath: found.recordPath, originalHash: found.originalHash, selector: { kind: 'registered-text' } });

/** 仕様と事例に出る引用を、出典URLで登録原本へ対応させる。 */
export function citationList(source, spec) {
  const citations = new Map();
  for (const c of [...source.citations, ...spec.assessments.flatMap(a => a.comparison?.citations ?? [])]) {
    requireThat(!citations.has(c.id) || citations.get(c.id).url === c.url, '引用IDが競合しています');
    citations.set(c.id, c);
  }
  return [...citations.values()];
}

export function parseManifest(manifest, spec) {
  requireThat(manifest?.schemaVersion === 'case-identities/v1' && Object.keys(manifest).length === 2
    && manifest.people && typeof manifest.people === 'object' && !Array.isArray(manifest.people), '人物照合台帳が不正です');
  const known = new Set(spec.people.map(p => p.personId));
  for (const [personId, entries] of Object.entries(manifest.people)) {
    requireThat(known.has(personId) && Array.isArray(entries) && entries.every(e => e && Object.keys(e).sort().join() === 'materialUrl,quote'
      && typeof e.materialUrl === 'string' && typeof e.quote === 'string' && e.quote.trim()), `人物照合台帳の行が不正です: ${personId}`);
  }
  return manifest.people;
}

/** 再読した名簿本文だけから人物を照合する。 */
export function resolvePeople(spec, people, rosterTexts) {
  const audit = spec.people.map(person => {
    const entries = people[person.personId] ?? [];
    const reasons = [];
    if (!entries.length) reasons.push('照合台帳に行がありません');
    for (const e of entries) {
      const text = rosterTexts.get(e.materialUrl);
      if (text === undefined) reasons.push(`登録原本がありません: ${e.materialUrl}`);
      else if (!text.includes(e.quote)) reasons.push(`名簿本文に引用が逐語で見つかりません: ${e.materialUrl}`);
      else if (!compact(e.quote).includes(compact(person.name))) reasons.push(`引用に評価仕様の氏名「${person.name}」がありません`);
    }
    return { personId: person.personId, status: reasons.length ? 'unresolved' : 'resolved', ...(reasons.length ? { reasons } : {}) };
  });
  return { audit, resolvedIds: audit.filter(r => r.status === 'resolved').map(r => r.personId) };
}

let bundlePromise;
/** vite で評価コード一式を単一bundleにする。 */
export function loadBundle() {
  bundlePromise ??= (async () => {
    const vite = await import(pathToFileURL(join(repoRoot, 'app/node_modules/vite/dist/node/index.js')).href);
    const src = name => join(repoRoot, 'app/src', name);
    const entry = `export * from ${JSON.stringify(src('evidence-evaluation.ts'))};\nexport * from ${JSON.stringify(src('case-evaluation.ts'))};\nexport { judgeImpact } from ${JSON.stringify(src('impact-rule.ts'))};\n`;
    const scratch = await mkdtemp(join(tmpdir(), 'case-run-bundle-'));
    const entryFile = join(scratch, 'entry.ts');
    let built;
    try {
      await writeFile(entryFile, entry, { mode: 0o600 });
      built = await vite.build({ configFile: false, root: join(repoRoot, 'app'), logLevel: 'silent',
        build: { write: false, minify: false, target: 'esnext', lib: { entry: entryFile, formats: ['es'] } } });
    } finally { await rm(scratch, { recursive: true, force: true }); }
    const chunk = (Array.isArray(built) ? built : [built]).flatMap(b => b.output).find(item => item.type === 'chunk' && item.isEntry);
    requireThat(chunk && chunk.imports.length === 0, '算定bundleが不正です');
    return { code: chunk.code, engineHash: digest(chunk.code), module: await import(`data:text/javascript;base64,${Buffer.from(chunk.code).toString('base64')}`) };
  })();
  return bundlePromise;
}

/** 資料の並びは buildCaseEvaluationInput の非同期順に依存するため、IDで整列して版を決定的にする。 */
const normalized = input => ({ ...input, materials: [...input.materials].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0) });

const quoteHolds = (q, texts) => {
  const material = texts.get(q.materialId);
  return Boolean(material) && digest(material.text) === material.contentHash && Number.isSafeInteger(q.start) && Number.isSafeInteger(q.end)
    && q.start >= 0 && q.end > q.start && q.end <= material.text.length && material.text.slice(q.start, q.end) === q.text;
};

/** 実行側の独立検証。再読した原本と仕様の系列だけから受領書を作る。 */
export async function verifyCaseEvidence({ snapshot, inputHash, source, spec, people, bundle, independent, rosterTexts }) {
  const texts = new Map(independent.map(m => [m.id, { text: m.text, contentHash: m.contentHash }]));
  const rebuilt = await bundle.module.buildCaseEvaluationInput(source, spec,
    new Map(independent.map(m => [m.id, { text: m.text, observedAt: m.observedAt, publishedAt: m.publishedAt, originalHash: m.originalHash }])));
  requireThat(canonical(normalized(rebuilt.input)) === canonical(snapshot), '独立に再読した原本から評価入力を再構成できません');
  const { audit, resolvedIds } = resolvePeople(spec, people, rosterTexts);
  const snapshotPeople = new Set(snapshot.people.map(p => p.id));
  const actionRevisions = snapshot.actions.filter(a => a.quotes.length > 0 && a.quotes.every(q => quoteHolds(q, texts)))
    .map(a => ({ id: a.actionId, revisionId: a.revisionId }));
  const assessmentRevisions = [];
  for (const a of snapshot.assessments) {
    const specAssessment = spec.assessments.find(s => s.id === a.id);
    if (!specAssessment?.series) continue;
    const judged = bundle.module.judgeImpact(structuredClone(specAssessment.series));
    if (judged.stage !== null && a.impact === judged.stage && a.quotes.length > 0 && a.quotes.every(q => quoteHolds(q, texts)))
      assessmentRevisions.push({ id: a.id, revisionId: digest(canonical(a)) });
  }
  return { audit, receipt: { inputHash, verifierId: 'case-evaluation-readback', verifierVersion: '1',
    resolvedPersonIds: resolvedIds.filter(id => snapshotPeople.has(id)), actionRevisions, assessmentRevisions } };
}

const writePrivate = async (path, text) => { await writeFile(path, text, { flag: 'w', mode: 0o600 }); await chmod(path, 0o600); };

/** spec と bundle は試験用の差し替え口。CLIは常に FINANCIAL_REVIVAL_DRAFT を使う。 */
export async function runCaseEvaluation({ args = process.argv.slice(2), spec: specOverride, repoRootOverride } = {}) {
  const values = parseArgs(args);
  const root = repoRootOverride ?? repoRoot;
  const bundle = await loadBundle();
  const spec = specOverride ?? bundle.module.FINANCIAL_REVIVAL_DRAFT;
  const source = JSON.parse(await readFile(resolve(values['--case-source']), 'utf8'));
  requireThat(source && Array.isArray(source.actors) && Array.isArray(source.citations) && source.caseId === spec.policyId, '事例入力が評価仕様と一致しません');
  const materialRoot = resolve(values['--material-root']), outputDir = resolve(values['--output-dir']);
  const manifest = JSON.parse(await readFile(resolve(values['--identities']), 'utf8'));
  const people = parseManifest(manifest, spec);
  const rosterUrls = [...new Set(Object.values(people).flat().map(e => e.materialUrl))].sort();

  const registered = await indexRegistered(materialRoot);
  const citations = citationList(source, spec);
  const missing = citations.filter(c => !registered.has(c.url));
  requireThat(!missing.length, `登録原本がない引用: ${missing.map(c => `${c.id}(${c.url})`).join(', ')}`);
  const citationRefs = citations.map(c => refFor(c.id, registered.get(c.url)));
  const rosterRefs = rosterUrls.filter(u => registered.has(u)).map(u => refFor(`roster-${digest(u).slice(0, 16)}`, registered.get(u)));
  const readAll = async () => {
    const all = await readRefs([...citationRefs, ...rosterRefs], materialRoot);
    const rosterTexts = new Map(all.slice(citationRefs.length).map(m => [m.url, m.text]));
    return { independent: all.slice(0, citationRefs.length), rosterTexts };
  };

  const first = await readAll();
  const input = normalized((await bundle.module.buildCaseEvaluationInput(source, spec,
    new Map(first.independent.map(m => [m.id, { text: m.text, observedAt: m.observedAt, publishedAt: m.publishedAt, originalHash: m.originalHash }])))).input);
  let lastAudit = [];
  const release = await runEvidencePipeline({ materialRefs: citationRefs, evidenceEvaluation: input }, {
    repoRoot: root, outputDir, engineHash: bundle.engineHash, evaluate: bundle.module.evaluateEvidence,
    readMaterials: async () => readRefs(citationRefs, materialRoot),
    verifyEvidence: async (snapshot, _stored, inputHash) => {
      const again = await readAll();
      const { audit, receipt } = await verifyCaseEvidence({ snapshot, inputHash, source, spec, people, bundle, ...again });
      lastAudit = audit;
      return receipt;
    },
  });
  const review = await writeReviewPacket(release, { repoRoot: root, outputDir });
  await mkdir(outputDir, { recursive: true });
  await writePrivate(join(outputDir, 'candidate-input.json'), canonical({ evidenceEvaluation: input, materialRefs: citationRefs.map(({ recordPath: _p, ...ref }) => ref) }) + '\n');
  await writePrivate(join(outputDir, 'identity-audit.json'), canonical({ schemaVersion: 'case-identity-audit/v1', caseId: source.caseId, rows: lastAudit }) + '\n');
  const summary = { releaseId: release.releaseId, caseId: source.caseId, m2Status: review.m2Status, publicationStatus: review.publicationStatus,
    resolvedPeople: release.verification.resolvedPersonIds.length, verifiedActions: release.verification.actionRevisions.length,
    verifiedAssessments: release.verification.assessmentRevisions.length, inputActions: release.result.coverage.inputActions,
    assessedActions: release.result.coverage.assessedActions, held: release.result.held.length,
    scores: release.result.rows.map(r => ({ personId: r.person.id, name: r.person.name, score: r.score, rank: r.rank, eligibleCount: r.eligibleCount, heldCount: r.heldCount })) };
  await writePrivate(join(outputDir, 'run-summary.json'), canonical(summary) + '\n');
  console.log(JSON.stringify(summary));
  return { release, review, summary };
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  if (process.argv.length === 3 && process.argv[2] === '--help') console.log(HELP);
  else runCaseEvaluation().catch(error => { console.error(error.message); process.exitCode = 1; });
}
