// Viteが実際に読み込んだ依存グラフを使う。独自のTypeScript解析器は作らない。
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { join, relative } from 'node:path';
import { isInsideCanonical } from './path_guard.mjs';

export async function generationMetadata(server, root, entries, extras = []) {
  const logicalRoot = root;
  root = realpathSync(root);
  const { SPEC_VERSION } = await server.ssrLoadModule('/src/method-spec.ts');
  if (!/^method-spec-v\d+\.\d+(?:\.\d+)?$/.test(SPEC_VERSION)) throw new Error('計算方法の版が不正です');
  const graph = server.environments.ssr.moduleGraph;
  const files = new Set(['app/src/method-spec.ts', 'scripts/generation_provenance.mjs', 'scripts/path_guard.mjs', 'app/package-lock.json', ...extras]);
  const seen = new Set();
  function walk(node) {
    if (!node || !node.file) throw new Error('生成ソースの依存を特定できません');
    if (seen.has(node)) return;
    seen.add(node);
    files.add(relative(root, realpathSync(node.file)).split('\\').join('/'));
    for (const child of node.importedModules) walk(child);
  }
  for (const entry of [...entries, 'app/src/method-spec.ts']) walk(graph.getModuleById(join(root, entry)) ?? graph.getModuleById(join(logicalRoot, entry)));
  const codeHashes = {};
  for (const file of [...files].sort()) {
    const path = realpathSync(join(root, file));
    const name = relative(root, path).split('\\').join('/');
    if (!await isInsideCanonical(root, path)) throw new Error('生成ソースがリポジトリの外を参照しています');
    codeHashes[name] = createHash('sha256').update(readFileSync(path)).digest('hex');
  }
  return { methodSpecVersion: SPEC_VERSION, codeHashes };
}
