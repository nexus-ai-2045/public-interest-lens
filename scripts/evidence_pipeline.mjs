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
    const result = await options.evaluate(snapshot.evidenceEvaluation, trusted);
    fields(result, ['mode', 'rows', 'held', 'coverage', 'publicationStatus']);
    if (result.publicationStatus !== 'requires_human_review' || result.mode !== snapshot.evidenceEvaluation.mode
      || !Array.isArray(result.rows) || !Array.isArray(result.held)) throw new Error('評価結果が不正です');
    fields(result.coverage, ['inputActions', 'assessedActions', 'readableMaterials']);
    if (Object.keys(result.coverage).length !== 3 || !Object.values(result.coverage).every(n => Number.isSafeInteger(n) && n >= 0)) throw new Error('評価集計が不正です');
    const semanticInput = { evidenceEvaluation: snapshot.evidenceEvaluation,
      materialRefs: snapshot.materialRefs.map(({ recordPath: _privatePath, ...semantic }) => semantic) };
    const body = { schemaVersion: 'evidence-release/v1', engineHash: options.engineHash, input: semanticInput, result: JSON.parse(canonical(result)), publicationStatus: 'requires_human_review' };
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
  if (args.length === 1 && args[0] === '--help') { console.log('node scripts/evidence_pipeline.mjs --input <JSON> --material-root <保存原本> --output-dir <repo/.local配下>'); return; }
  for (let i = 0; i < args.length; i += 2) {
    if (!['--input', '--material-root', '--output-dir'].includes(args[i]) || !args[i + 1] || values[args[i]]) throw new Error('CLI引数が不正です');
    values[args[i]] = args[i + 1];
  }
  if (Object.keys(values).length !== 3) throw new Error('input/material-root/output-dirが必要です');
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
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
