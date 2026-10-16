/** パスの包含判定の唯一の実装。比較する両辺を実体パスへそろえてから判定する。 */
import { realpath } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path';

export async function canonicalPath(path) {
  const absolute = resolve(path);
  const missing = [];
  let cursor = absolute;
  for (;;) {
    try {
      return join(await realpath(cursor), ...missing.reverse());
    } catch (error) {
      if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') throw error;
      const parent = dirname(cursor);
      if (parent === cursor) throw error;
      missing.push(basename(cursor));
      cursor = parent;
    }
  }
}

export function isStrictlyInside(root, path) {
  const rel = relative(root, path);
  return rel !== '' && !isAbsolute(rel) && rel !== '..' && !rel.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`);
}

export function sameTrailingParts(canonical, lexical, relativePart) {
  const count = relativePart.split(/[\\/]/).filter(Boolean).length;
  const foldCase = process.platform === 'darwin' || process.platform === 'win32';
  const tail = path => {
    const joined = path.split(/[\\/]/).filter(Boolean).slice(-count).join('/');
    return foldCase ? joined.toLowerCase() : joined;
  };
  return count > 0 && tail(canonical) === tail(lexical);
}

export async function isInsideCanonical(root, path) {
  return isStrictlyInside(await canonicalPath(root), await canonicalPath(path));
}
