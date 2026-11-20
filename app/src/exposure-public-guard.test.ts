// @ts-nocheck
// @vitest-environment node
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { distributionExposureUrl, MEMBER_RANKING_HIDDEN } from './MembersPage';

/**
 * 曝露ランキング（議員の実名つきの額）は、ADR 0008 のねくの確認まで公開しない。
 * 出力は data/derived/exposure-v1/（公開ディレクトリの外）だけ。app/public（そのまま配信される）に入ったら落とす。
 */
const publicDir = fileURLToPath(new URL('../public', import.meta.url));
const walk = (dir: string): string[] => readdirSync(dir).flatMap(name => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? walk(path) : [path];
});
const TEXT = /\.(json|csv|txt|js|mjs|html|xml|tsv|md)$/i;

describe('曝露ランキングを公開ディレクトリに置かない', () => {
  it('app/public に、名前に exposure・曝露を含むファイルが無い', () => {
    const hits = walk(publicDir).filter(p => /exposure|曝露/i.test(p.slice(publicDir.length)));
    expect(hits).toEqual([]);
  });

  it('app/public のどのファイルにも、曝露ランキングの形式名と額の欄が無い', () => {
    const hits = walk(publicDir).filter(p => TEXT.test(p)).filter(p => {
      const text = readFileSync(p, 'utf8');
      return text.includes('exposure-ranking/v') || text.includes('"exposureYen"');
    });
    expect(hits).toEqual([]);
  });

  it('画面は隠したまま（MEMBER_RANKING_HIDDEN）で、読みに行く先は公開ディレクトリの中に無い', () => {
    expect(MEMBER_RANKING_HIDDEN).toBe(true);
    const target = join(publicDir, distributionExposureUrl);
    expect(() => statSync(target)).toThrow();
  });
});
