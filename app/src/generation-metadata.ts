import { SPEC_VERSION } from './method-spec';

export type GenerationMetadata = { methodSpecVersion: string; codeHashes: Record<string, string> };

/** 古い方法版・欠落した来歴・端末の絶対パスを配布データとして受け付けない。 */
export function validGenerationMetadata(value: unknown, required: string[] = []): value is GenerationMetadata {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const v = value as GenerationMetadata;
  if (Object.keys(v).sort().join(',') !== 'codeHashes,methodSpecVersion' || v.methodSpecVersion !== SPEC_VERSION) return false;
  if (!v.codeHashes || typeof v.codeHashes !== 'object' || Array.isArray(v.codeHashes) || !Object.hasOwn(v.codeHashes, 'app/src/method-spec.ts')) return false;
  if (!required.every(path => Object.hasOwn(v.codeHashes, path))) return false;
  return Object.entries(v.codeHashes).every(([path, hash]) =>
    /^(app\/src\/[A-Za-z0-9_./-]+\.tsx?|scripts\/[A-Za-z0-9_.-]+\.(py|mjs)|app\/package-lock\.json)$/.test(path)
    && !path.split('/').includes('..') && typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash));
}
