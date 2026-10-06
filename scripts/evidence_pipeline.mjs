import { createHash, randomUUID } from 'node:crypto';
import { lstat, realpath, mkdir, readFile, writeFile, rename, unlink, link, rmdir } from 'node:fs/promises';
import { dirname, resolve, relative, isAbsolute, join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const hash = value => createHash('sha256').update(value).digest('hex');
function canonical(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  throw new Error('JSON値が不正です');
}
function fields(value, allowed) {
  if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).some(k => !allowed.includes(k))) throw new Error('未許可の入力フィールドです');
}
function freeze(value) {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
/** 能力はCLI入力ではなく独立した実行側から供給します。自己申告JSONは受理しません。 */
async function independentVerification(snapshot, stored, verifier) {
  if (!verifier) return null;
  const inputHash = hash(canonical(snapshot.evidenceEvaluation));
  const receipt = JSON.parse(canonical(await verifier(freeze(structuredClone(snapshot.evidenceEvaluation)), freeze(structuredClone(stored)), inputHash)));
  return validateVerification(snapshot.evidenceEvaluation, receipt, inputHash);
}
function validateVerification(input, receipt, inputHash = hash(canonical(input))) {
  fields(receipt, ['inputHash', 'verifierId', 'verifierVersion', 'resolvedPersonIds', 'actionRevisions', 'assessmentRevisions']);
  if (receipt.inputHash !== inputHash || !['verifierId', 'verifierVersion'].every(k => typeof receipt[k] === 'string' && receipt[k].trim())) throw new Error('独立検証の入力束縛が不一致です');
  if (!Array.isArray(receipt.resolvedPersonIds) || new Set(receipt.resolvedPersonIds).size !== receipt.resolvedPersonIds.length
    || receipt.resolvedPersonIds.some(id => typeof id !== 'string' || !input.people.some(p => p.id === id))) throw new Error('人物検証の参照が不正です');
  for (const [key, source, idKey] of [['actionRevisions', 'actions', 'actionId'], ['assessmentRevisions', 'assessments', 'id']]) {
    const entries = receipt[key];
    if (!Array.isArray(entries) || new Set(entries.map(e => e?.id)).size !== entries.length) throw new Error('改訂検証が重複または不正です');
    for (const entry of entries) {
      fields(entry, ['id', 'revisionId']);
      const target = input[source].find(a => a[idKey] === entry.id);
      const revision = source === 'actions' ? target?.revisionId : target && hash(canonical(target));
      if (!target || typeof entry.revisionId !== 'string' || !/^[a-f0-9]{64}$/.test(entry.revisionId) || revision !== entry.revisionId) throw new Error('検証した改訂が入力と不一致です');
    }
  }
  receipt.resolvedPersonIds.sort();
  receipt.actionRevisions.sort((a, b) => a.id.localeCompare(b.id));
  receipt.assessmentRevisions.sort((a, b) => a.id.localeCompare(b.id));
  return receipt;
}
function within(root, path) {
  const rel = relative(root, path);
  return rel !== '' && !isAbsolute(rel) && rel !== '..' && !rel.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`);
}
async function noLink(path) {
  try { if ((await lstat(path)).isSymbolicLink()) throw new Error('リンク経由の保存は禁止です'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
}
async function outputLocation(repoRoot, outputDir) {
  const root = await realpath(resolve(repoRoot));
  const local = join(root, '.local');
  const out = resolve(outputDir);
  if (!within(local, out)) throw new Error('出力はrepoの.local配下に限定します');
  let cursor = root;
  for (const part of relative(root, out).split(/[\\/]/)) {
    cursor = join(cursor, part);
    await noLink(cursor);
    await mkdir(cursor, { recursive: false }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    if (!(await lstat(cursor)).isDirectory()) throw new Error('保存先がdirectoryではありません');
    if (!within(root, await realpath(cursor))) throw new Error('保存先がrepo外です');
  }
  return out;
}
async function atomicJson(out, name, text) {
  const target = join(out, name);
  await noLink(target);
  const temp = join(out, `.pending-${randomUUID()}`);
  try { await writeFile(temp, text, { flag: 'wx', mode: 0o600 }); await rename(temp, target); }
  finally { await unlink(temp).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}
function validateEvaluationResult(input, result) {
  fields(result, ['mode', 'rows', 'held', 'coverage', 'publicationStatus']);
  if (!Array.isArray(result.rows) || !Array.isArray(result.held)) throw new Error('評価結果一覧が不正です');
  let contributions = 0;
  for (const row of result.rows) {
    fields(row, ['person', 'score', 'rank', 'eligibleCount', 'heldCount', 'contributions']);
    if (!Array.isArray(row.contributions) || row.eligibleCount !== row.contributions.length || !Number.isSafeInteger(row.heldCount) || row.heldCount < 0) throw new Error('人物の集計が不正です');
    const policies = new Set();
    for (const c of row.contributions) {
      fields(c, ['policyId', 'actionKey', 'actionDate', 'role', 'score']);
      if (policies.has(c.policyId) || !Number.isFinite(c.score) || c.score < 0) throw new Error('寄与点が不正または重複しています');
      policies.add(c.policyId); contributions++;
    }
  }
  for (const held of result.held) fields(held, ['personId', 'policyId', 'actionId', 'reason']);
  fields(result.coverage, ['inputActions', 'assessedActions', 'readableMaterials']);
  if (result.coverage.inputActions !== new Set(input.actions.map(a => a.actionId)).size || result.coverage.assessedActions !== contributions
    || !Object.values(result.coverage).every(n => Number.isSafeInteger(n) && n >= 0)) throw new Error('評価件数が入力・寄与と不一致です');
}

/** 公開を実行しないレビュー資料。原本全文・保存パス・AI実行ログは投影しません。 */
export function buildReviewPacket(release) {
  fields(release, ['schemaVersion', 'engineHash', 'input', 'result', 'publicationStatus', 'releaseId', 'verification']);
  const { releaseId, ...body } = release;
  if (release.schemaVersion !== 'evidence-release/v1' || !/^[a-f0-9]{64}$/.test(releaseId) || hash(canonical(body)) !== releaseId
    || release.publicationStatus !== 'requires_human_review' || release.input?.evidenceEvaluation?.mode !== 'real' || release.result?.mode !== 'real') throw new Error('実資料評価版の整合性が不正です');
  const input = release.input.evidenceEvaluation;
  fields(input.options, ['domain', 'direction', 'period', 'asOf', 'weights']);
  fields(input.options.weights, ['economy', 'technology']);
  validateEvaluationResult(input, release.result);
  const verification = release.verification ? validateVerification(input, structuredClone(release.verification)) : null;
  if (!Array.isArray(release.result.rows) || new Set(release.result.rows.map(r => r.person?.id)).size !== release.result.rows.length) throw new Error('評価人物が不正です');
  for (const row of release.result.rows) {
    const person = input.people.find(p => p.id === row.person?.id);
    if (!person || canonical(person) !== canonical(row.person) || !(row.score === null || (Number.isFinite(row.score) && row.score >= 0)) || !Array.isArray(row.contributions)) throw new Error('評価人物と入力が不一致です');
    if (row.score !== null) {
      if (!verification?.resolvedPersonIds.includes(person.id) || !row.contributions.length) throw new Error('得点に独立検証の参照がありません');
      for (const contribution of row.contributions) {
        const action = input.actions.find(a => a.actionId === contribution.actionKey && a.personId === person.id && a.policyId === contribution.policyId);
        if (!action || !verification.actionRevisions.some(v => v.id === action.actionId && v.revisionId === action.revisionId)
          || !input.assessments.some(a => a.policyId === action.policyId && a.policyVersion === action.policyVersion && a.position === action.position
            && a.direction === input.options.direction && (input.options.domain === 'overall' || a.domain === input.options.domain)
            && verification.assessmentRevisions.some(v => v.id === a.id && v.revisionId === hash(canonical(a))))) throw new Error('得点に行動・分析の検証参照がありません');
      }
    }
  }
  const source = new Map(input.materials.map(m => [m.id, m]));
  const safeText = value => {
    // 先頭の HTTPS scheme だけを除外し、本文中の連結パスも検出する。
    const inspect = typeof value === 'string' && value.startsWith('https://') ? value.slice(8) : value;
    if (typeof inspect !== 'string' || /(?:[a-z]:[\\/]|file:\/\/|\\\\|\/(?:Users|home)\/|\.local[\\/])/i.test(inspect)) throw new Error('レビュー資料へ非公開パスを含められません');
    return value;
  };
  const quote = q => {
    const material = source.get(q.materialId);
    if (!material) throw new Error('引用の資料参照がありません');
    const url = new URL(material.url);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('原資料URLが不正です');
    return { materialId: q.materialId, start: q.start, end: q.end, text: safeText(q.text), sourceUrl: url.href, originalHash: material.originalHash };
  };
  const assessedPeople = new Set(release.result.rows.filter(r => r.score !== null && Number.isFinite(r.score)).map(r => r.person.id)).size;
  // hashと保存receiptの整合性は、実行時原本再読・独立検証の成功そのものではありません。
  const needsReadback = Boolean(verification && assessedPeople >= 2 && release.result.coverage.assessedActions >= 2);
  const packet = {
    schemaVersion: 'evidence-review/v1', releaseId, engineHash: release.engineHash,
    publicationStatus: 'requires_human_review', verificationState: 'review_required',
    m2Status: needsReadback ? 'requires_independent_readback' : 'not_established',
    conditions: input.options,
    scopeNote: '収録した有限政策の接続実証です。全国を代表する順位ではありません。',
    people: release.result.rows.map(r => ({ id: r.person.id, name: safeText(r.person.name), score: r.score, rank: r.rank, eligibleCount: r.eligibleCount, heldCount: r.heldCount })),
    actions: input.actions.map(a => ({ actionId: a.actionId, revisionId: a.revisionId, personId: a.personId, policyId: a.policyId, policyVersion: a.policyVersion, actionDate: a.actionDate, role: a.role, position: a.position, description: safeText(a.description), quotes: a.quotes.map(quote) })),
    assessments: input.assessments.map(a => ({ id: a.id, policyId: a.policyId, policyVersion: a.policyVersion, position: a.position, domain: a.domain, direction: a.direction, impact: a.impact, rationale: safeText(a.rationale), counterEvidence: safeText(a.counterEvidence), alternativeExplanation: safeText(a.alternativeExplanation), criterionVersion: a.criterionVersion, analysisVersion: a.analysisVersion, quotes: a.quotes.map(quote) })),
    held: release.result.held.map(h => ({ ...(h.personId ? { personId: h.personId } : {}), ...(h.policyId ? { policyId: h.policyId } : {}), ...(h.actionId ? { actionId: h.actionId } : {}), reason: safeText(h.reason) })),
    coverage: release.result.coverage,
    reviewChecklist: ['人物の同一性・対象選挙', '行動と原資料の引用一致', '政策の立場別影響・反証・尺度', '係数と重み変更の感度', '取得範囲と未評価の表示', '引用・転載の権利', '訂正窓口', '公開内容・配信先の個別承認'],
  };
  const inspect = value => { if (typeof value === 'string') safeText(value); else if (value && typeof value === 'object') Object.values(value).forEach(inspect); };
  inspect(packet);
  return packet;
}

export async function writeReviewPacket(release, options) {
  const packet = buildReviewPacket(release);
  const out = await outputLocation(options.repoRoot, options.outputDir);
  await atomicJson(out, `review-${release.releaseId}.json`, canonical(packet) + '\n');
  return packet;
}

/** ローカル専用。入力JSONから検証済み人物・行動・分析を作らない。 */
export async function runEvidencePipeline(input, options) {
  const out = await outputLocation(options.repoRoot, options.outputDir);
  const lock = join(out, '.pipeline-lock');
  await noLink(lock);
  await mkdir(lock); // 同時実行はfail-closed。既存lockを勝手に解除しない。
  try {
    fields(input, ['materialRefs', 'evidenceEvaluation']);
    if (!Array.isArray(input.materialRefs) || !input.evidenceEvaluation) throw new Error('評価入力が不正です');
    fields(input.evidenceEvaluation, ['schemaVersion', 'mode', 'options', 'people', 'materials', 'actions', 'assessments']);
    if (!/^[a-f0-9]{64}$/.test(options.engineHash)) throw new Error('算定版hashが不正です');
    const snapshot = JSON.parse(canonical(input));
    for (const ref of snapshot.materialRefs) {
      fields(ref, ['id', 'recordPath', 'originalHash', 'selector']);
      fields(ref.selector, ['kind', 'speechId', 'billId', 'title', 'sourceLine', 'nameText']);
    }
    const stored = options.readMaterials ? await options.readMaterials(snapshot.materialRefs) : [];
    if (!Array.isArray(stored) || new Set(stored.map(m => m.id)).size !== stored.length) throw new Error('原本readbackが不正です');
    const materials = new Map(stored.map(m => [m.id, m]));
    const trusted = { readMaterial: async id => materials.get(id) ?? null,
      resolvedPersonIds: new Set(), verifiedActionIds: new Set(), verifiedAssessmentIds: new Set(),
      verifiedActionRevisions: new Map(), verifiedAssessmentRevisions: new Map() };
    const verification = await independentVerification(snapshot, stored, options.verifyEvidence);
    if (verification) {
      trusted.resolvedPersonIds = new Set(verification.resolvedPersonIds);
      trusted.verifiedActionRevisions = new Map(verification.actionRevisions.map(e => [e.id, e.revisionId]));
      trusted.verifiedAssessmentRevisions = new Map(verification.assessmentRevisions.map(e => [e.id, e.revisionId]));
      trusted.verifiedActionIds = new Set(trusted.verifiedActionRevisions.keys());
      trusted.verifiedAssessmentIds = new Set(trusted.verifiedAssessmentRevisions.keys());
    }
    const result = await options.evaluate(snapshot.evidenceEvaluation, trusted);
    validateEvaluationResult(snapshot.evidenceEvaluation, result);
    fields(result, ['mode', 'rows', 'held', 'coverage', 'publicationStatus']);
    if (result.publicationStatus !== 'requires_human_review' || result.mode !== snapshot.evidenceEvaluation.mode
      || !Array.isArray(result.rows) || !Array.isArray(result.held)) throw new Error('評価結果が不正です');
    fields(result.coverage, ['inputActions', 'assessedActions', 'readableMaterials']);
    if (Object.keys(result.coverage).length !== 3 || !Object.values(result.coverage).every(n => Number.isSafeInteger(n) && n >= 0)) throw new Error('評価集計が不正です');
    const semanticInput = { evidenceEvaluation: snapshot.evidenceEvaluation,
      materialRefs: snapshot.materialRefs.map(({ recordPath: _privatePath, ...semantic }) => semantic) };
    const body = { schemaVersion: 'evidence-release/v1', engineHash: options.engineHash, input: semanticInput, result: JSON.parse(canonical(result)), publicationStatus: 'requires_human_review' };
    if (verification) body.verification = verification;
    const releaseId = hash(canonical(body));
    const release = { ...body, releaseId };
    const bytes = canonical(release) + '\n';
    const releases = join(out, 'releases');
    await noLink(releases);
    await mkdir(releases, { recursive: true });
    const target = join(releases, `${releaseId}.json`);
    await noLink(target);
    const temp = join(releases, `.pending-${randomUUID()}`);
    try {
      await writeFile(temp, bytes, { flag: 'wx', mode: 0o600 });
      try { await link(temp, target); }
      catch (error) { if (error.code !== 'EEXIST') throw error; }
      if (await readFile(target, 'utf8') !== bytes) throw new Error('既存の同一版が一致しません');
    } finally { await unlink(temp).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
    // currentの変更を最後にする。失敗記録が壊れていた場合も正常版を保持する。
    await atomicJson(out, 'last-attempt.json', canonical({ status: 'succeeded', releaseId }) + '\n');
    await atomicJson(out, 'current.json', bytes);
    return release;
  } catch (error) {
    await atomicJson(out, 'last-attempt.json', canonical({ status: 'failed', errorType: 'PipelineError' }) + '\n').catch(() => {});
    throw error;
  } finally { await rmdir(lock); }
}

async function readOriginals(refs, repoRoot, materialRoot, readableEvidence) {
  return new Promise((accept, reject) => {
    const child = spawn('python', ['-m', 'scripts.read_evidence_materials', '--material-root', materialRoot], { cwd: repoRoot, env: { ...process.env, PYTHONUTF8: '1' }, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', size = 0;
    child.stdout.setEncoding('utf8');
    const timer = setTimeout(() => { child.kill(); reject(new Error('原本readbackが時間切れです')); }, 30_000);
    child.stdout.on('data', chunk => { size += Buffer.byteLength(chunk); if (size > 64 * 1024 * 1024) { child.kill(); reject(new Error('原本readbackの上限超過です')); } else stdout += chunk; });
    child.stderr.resume();
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => { clearTimeout(timer); if (code !== 0) reject(new Error('原本readbackに失敗しました')); else { try { accept(JSON.parse(stdout)); } catch (error) { reject(error); } } });
    child.stdin.on('error', () => {});
    child.stdin.end(canonical(readableEvidence === undefined ? refs : { materialRefs: refs, readableEvidence }));
  });
}

async function main() {
  const args = process.argv.slice(2), values = {};
  if (args.length === 1 && args[0] === '--help') { console.log('node scripts/evidence_pipeline.mjs --input <JSON> --material-root <保存原本> --output-dir <repo/.local配下>\nnode scripts/evidence_pipeline.mjs --review-input <保存評価版JSON> --output-dir <repo/.local配下>'); return; }
  for (let i = 0; i < args.length; i += 2) {
    if (!['--input', '--material-root', '--output-dir', '--review-input'].includes(args[i]) || !args[i + 1] || values[args[i]]) throw new Error('CLI引数が不正です');
    values[args[i]] = args[i + 1];
  }
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  if (values['--review-input']) {
    if (Object.keys(values).length !== 2 || !values['--output-dir']) throw new Error('review-input/output-dirだけを指定してください');
    const text = await readFile(resolve(values['--review-input']), 'utf8');
    if (Buffer.byteLength(text) > 5_000_000) throw new Error('入力上限超過です');
    const packet = await writeReviewPacket(JSON.parse(text), { repoRoot, outputDir: resolve(values['--output-dir']) });
    console.log(JSON.stringify({ releaseId: packet.releaseId, m2Status: packet.m2Status, publicationStatus: packet.publicationStatus }));
    return;
  }
  if (Object.keys(values).length !== 3 || !values['--input'] || !values['--material-root'] || !values['--output-dir']) throw new Error('input/material-root/output-dirが必要です');
  const raw = await readFile(resolve(values['--input']), 'utf8');
  if (Buffer.byteLength(raw) > 5_000_000) throw new Error('入力上限超過です');
  const saved = JSON.parse(raw);
  // 既存の閲覧用packも入力にできるが、信頼情報を含む未知のfieldは拒否する。
  fields(saved, ['materialRefs', 'evidenceEvaluation', 'asOf', 'coverage', 'evidence', 'fictional', 'held', 'involvements', 'people', 'policies', 'policySelection', 'readableEvidence', 'schemaVersion']);
  const input = { materialRefs: saved.materialRefs, evidenceEvaluation: saved.evidenceEvaluation };
  const vite = await import(pathToFileURL(join(repoRoot, 'app/node_modules/vite/dist/node/index.js')).href);
  const built = await vite.build({ configFile: false, root: join(repoRoot, 'app'), logLevel: 'silent', build: { write: false, minify: false, target: 'esnext', lib: { entry: join(repoRoot, 'app/src/evidence-evaluation.ts'), formats: ['es'] } } });
  const chunks = (Array.isArray(built) ? built : [built]).flatMap(bundle => bundle.output);
  const chunk = chunks.find(item => item.type === 'chunk' && item.isEntry);
  if (!chunk || chunk.imports.length) throw new Error('算定コードのbundleが不正です');
  const evaluator = await import(`data:text/javascript;base64,${Buffer.from(chunk.code).toString('base64')}`);
  const release = await runEvidencePipeline(input, { repoRoot, outputDir: resolve(values['--output-dir']), engineHash: hash(chunk.code), evaluate: evaluator.evaluateEvidence,
    readMaterials: refs => readOriginals(refs, repoRoot, resolve(values['--material-root']), saved.readableEvidence) });
  console.log(JSON.stringify({ releaseId: release.releaseId, publicationStatus: release.publicationStatus, coverage: release.result.coverage, held: release.result.held.length }));
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) main().catch(() => { console.error('ローカル評価版の生成に失敗しました。公開・送信はしていません。'); process.exitCode = 1; });
