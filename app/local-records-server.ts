import { open, realpath } from 'node:fs/promises';
import { resolve, relative, isAbsolute } from 'node:path';
import type { Plugin } from 'vite';
import { parseLocalInspection } from './src/local-inspection';

const MAX_BYTES = 5_000_000;
/** dev serverだけの固定入口。原本保存パス・分析ログ・評価入力を返しません。 */
export async function readLocalRecords(input: string, privateRoot: string): Promise<string> {
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
    const inspection = parseLocalInspection(buffer.subarray(0, size).toString('utf8'));
    return JSON.stringify({ schemaVersion: 'ranking-dataset/v1', fictional: false,
      asOf: inspection.asOf, coverage: { scope: inspection.scope, assessedPeople: 0, sourceRecords: inspection.sourceRecords, sourceStatus: inspection.sourceStatus },
      people: [], policies: [], involvements: [], evidence: [], held: inspection.held,
      readableEvidence: inspection.readableEvidence, policySelection: inspection.policySelection });
  } finally { await handle.close(); }
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
    server.middlewares.use(async (req, res, next) => {
      if (req.url !== '/__local__/records') return next();
      res.setHeader('Cache-Control', 'no-store'); res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      if (req.method !== 'GET' || !localRequestAllowed(req.socket.remoteAddress, req.headers.host,
        typeof req.headers.origin === 'string' ? req.headers.origin : undefined,
        typeof req.headers['sec-fetch-site'] === 'string' ? req.headers['sec-fetch-site'] : undefined)) {
        res.statusCode = 403; res.end('{"error":"local_access_only"}'); return;
      }
      try {
        res.end(await readLocalRecords(resolve(repo, '.local/m1-integration-20261002/current.json'), resolve(repo, '.local')));
      } catch {
        res.statusCode = 404; res.end('{"error":"local_records_unavailable"}');
      }
    });
  } };
}
