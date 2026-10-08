import { open, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, relative, isAbsolute, dirname, basename } from 'node:path';
import type { Plugin } from 'vite';
import { parseLocalInspection } from './src/local-inspection';
import { parseRealRelease } from './src/real-release-view';
import { parsePolicyCatalog } from './src/policy-context';
import { parseEconomicSnapshot } from './src/economy-view';

export async function readLocalPolicyContext(root: string, expectedRelease: string): Promise<string> {
  const text = await readPrivateText(resolve(root, 'current.json'), root);
  const current = JSON.parse(text);
  if (current?.schemaVersion === 'policy-context/v1') {
    const parsed = parsePolicyCatalog(text, expectedRelease);
    if (containsPrivateData(parsed)) throw new Error('PrivateFieldError');
    return JSON.stringify(parsed);
  }
  if (current?.schemaVersion !== 'policy-catalog-current/v1' || current.releaseId !== expectedRelease || !/^[a-f0-9]{64}$/.test(current.generation) || current.contextPath !== `generations/${current.generation}/context.json` || current.databasePath !== `generations/${current.generation}/catalog.sqlite3` || !/^[a-f0-9]{64}$/.test(current.contextSha256)) throw new Error('InvalidCatalogGeneration');
  const context = await readPrivateText(resolve(root, current.contextPath), root);
  if (createHash('sha256').update(context).digest('hex') !== current.contextSha256) throw new Error('CatalogHashMismatch');
  const parsed = parsePolicyCatalog(context, expectedRelease);
  if (containsPrivateData(parsed)) throw new Error('PrivateFieldError');
  return JSON.stringify(parsed);
}

const MAX_BYTES = 5_000_000;
/** dev serverだけの固定入口。原本保存パス・分析ログ・評価入力を返しません。 */
async function readPrivateText(input: string, privateRoot: string): Promise<string> {
  const [root, target] = await Promise.all([realpath(privateRoot), realpath(input)]);
  const rel = relative(root, target);
  if (!rel || isAbsolute(rel) || rel === '..' || rel.startsWith('../') || rel.startsWith('..\\')) throw new Error('PrivateRootError');
  const handle = await open(target, 'r');
  try {
    if (!(await handle.stat()).isFile()) throw new Error('InputTypeError');
    const buffer = Buffer.alloc(MAX_BYTES + 1);
    let size = 0;
    while (size < buffer.length) {
      const result = await handle.read(buffer, size, buffer.length - size, null);
      if (!result.bytesRead) break;
      size += result.bytesRead;
    }
    if (size > MAX_BYTES) throw new Error('InputSizeError');
    return buffer.subarray(0, size).toString('utf8');
  } finally { await handle.close(); }
}
export async function readLocalRecords(input: string, privateRoot: string): Promise<string> {
    const inspection = parseLocalInspection(await readPrivateText(input, privateRoot));
    return JSON.stringify({ schemaVersion: 'ranking-dataset/v1', fictional: false,
      asOf: inspection.asOf, coverage: { scope: inspection.scope, assessedPeople: 0, sourceRecords: inspection.sourceRecords, sourceStatus: inspection.sourceStatus },
      people: [], policies: [], involvements: [], evidence: [], held: inspection.held,
      readableEvidence: inspection.readableEvidence, policySelection: inspection.policySelection });
}

function containsPrivateData(value: unknown): boolean {
  if (typeof value === 'string') {
    const urls = /https:\/\/[^\s"'<>]+/gi;
    for (const match of value.matchAll(urls)) {
      try { const url = new URL(match[0]); if (url.username || url.password) return true; }
      catch { return true; }
    }
    const remainder = value.replace(urls, '');
    return /file:|[a-z]:[\\/]|\\\\[^\\\s]+\\|\/(?:Users|home|root)\//i.test(remainder);
  }
  if (Array.isArray(value)) return value.some(containsPrivateData);
  if (value && typeof value === 'object') return Object.entries(value).some(([key, item]) => ['recordpath', 'internallog'].includes(key.toLowerCase()) || containsPrivateData(item));
  return false;
}

/** 保存版のハッシュを維持します。私的項目がある版は加工せず拒否します。 */
export async function readLocalEvaluation(input: string, privateRoot: string, expectedRelease = ''): Promise<string> {
  const text = await readPrivateText(input, privateRoot);
  const release = await parseRealRelease(text);
  // 復号後を検査します。Unicode escapeされたキーやパスも生文字列と同じ扱いにします。
  if (containsPrivateData(release)) throw new Error('PrivateFieldError');
  const response = JSON.stringify(release);
  if (release.verification !== undefined) {
    const verification = release.verification;
    if (!verification || typeof verification !== 'object' || Array.isArray(verification) || Object.keys(verification).some(k => !['inputHash', 'verifierId', 'verifierVersion', 'resolvedPersonIds', 'actionRevisions', 'assessmentRevisions'].includes(k))) throw new Error('PrivateFieldError');
  }
  if (expectedRelease && release.releaseId !== expectedRelease) throw new Error('ReleaseMismatch');
  return response;
}

export function localRequestAllowed(remoteAddress: string | undefined, host: string | undefined, origin: string | undefined, fetchSite: string | undefined): boolean {
  if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(remoteAddress ?? '') || !host || fetchSite === 'cross-site') return false;
  try {
    const local = new URL(`http://${host}`);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(local.hostname) || local.username || local.password) return false;
    return !origin || origin === local.origin;
  } catch { return false; }
}

export function localRecordsPlugin(): Plugin {
  return { name: 'private-local-records', apply: 'serve', configureServer(server) {
    const repo = resolve(server.config.root, '..');
    const canonicalRepo = basename(dirname(repo)) === '.worktrees' ? resolve(repo, '../..') : repo;
    async function configuredPrivateRoot(root: string) {
      const realRoot = await realpath(root), privateRel = relative(await realpath(canonicalRepo), realRoot);
      if (isAbsolute(privateRel) || privateRel === '..' || privateRel.startsWith('..\\') || privateRel.startsWith('../') || !privateRel.split(/[\\/]/).includes('.local')) throw new Error('PrivateRootError');
      return realRoot;
    }
    server.middlewares.use(async (req, res, next) => {
      const evaluation = req.url === '/__local__/evaluation' || req.url?.startsWith('/__local__/evaluation?');
      const policyContext = req.url?.startsWith('/__local__/policy-context?');
      const economy = req.url === '/__local__/economy' || req.url?.startsWith('/__local__/economy?');
      if (req.url !== '/__local__/records' && !evaluation && !policyContext && !economy) return next();
      res.setHeader('Cache-Control', 'no-store'); res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      if (req.method !== 'GET' || !localRequestAllowed(req.socket.remoteAddress, req.headers.host,
        typeof req.headers.origin === 'string' ? req.headers.origin : undefined,
        typeof req.headers['sec-fetch-site'] === 'string' ? req.headers['sec-fetch-site'] : undefined)) {
        res.statusCode = 403; res.end('{"error":"local_access_only"}'); return;
      }
      try {
        if (economy) {
          const url = new URL(req.url!, 'http://local.invalid');
          const edition = url.searchParams.get('edition') ?? '';
          if ([...url.searchParams.keys()].some(key => key !== 'edition') || url.searchParams.getAll('edition').length > 1 || (edition && !/^[a-f0-9]{64}$/.test(edition))) throw new Error('InvalidEdition');
          const root = await configuredPrivateRoot(resolve(repo, '.local/economy'));
          const snapshot = parseEconomicSnapshot(await readPrivateText(resolve(root, edition ? `releases/${edition}.json` : 'current.json'), root));
          if (edition && snapshot.snapshotId !== edition) throw new Error('EditionMismatch');
          if (containsPrivateData(snapshot)) throw new Error('PrivateFieldError');
          res.end(JSON.stringify(snapshot));
        } else if (policyContext) {
          const url = new URL(req.url!, 'http://local.invalid');
          const releaseId = url.searchParams.get('release') ?? '';
          if ([...url.searchParams.keys()].some(k => k !== 'release') || url.searchParams.getAll('release').length !== 1 || !/^[a-f0-9]{64}$/.test(releaseId)) throw new Error('InvalidRelease');
          const root = await configuredPrivateRoot(resolve(repo, '.local/policy-catalog'));
          res.end(await readLocalPolicyContext(root, releaseId));
        } else if (evaluation) {
          const url = new URL(req.url!, 'http://local.invalid');
          const releaseId = url.searchParams.get('release') ?? '';
          if ([...url.searchParams.keys()].some(k => k !== 'release') || url.searchParams.getAll('release').length > 1 || (releaseId && !/^[a-f0-9]{64}$/.test(releaseId))) throw new Error('InvalidRelease');
          const root = process.env.LENS_EVALUATION_ROOT || resolve(repo, '.local/evaluation');
          const realRoot = await configuredPrivateRoot(root);
          res.end(await readLocalEvaluation(resolve(realRoot, releaseId ? `releases/${releaseId}.json` : 'current.json'), realRoot, releaseId));
        } else {
          const root = await configuredPrivateRoot(process.env.LENS_RECORDS_ROOT || resolve(repo, '.local/m1-integration-20261002'));
          res.end(await readLocalRecords(resolve(root, 'current.json'), root));
        }
      } catch {
        res.statusCode = 404; res.end('{"error":"local_records_unavailable"}');
      }
    });
  } };
}
