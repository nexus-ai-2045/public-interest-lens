// Node の型定義を入れずに、保存済みの対応表だけを読むため型検査を外します。
// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { EXPANSION_MAP, parseCsv } from './impact-batch';

describe('保存済みの v1 対応表', () => {
  it('22行の旧系列のままで、今の対応表の行を含まない', () => {
    const saved = parseCsv(readFileSync(new URL('../../data/derived/impact-v1/indicator-map.csv', import.meta.url), 'utf8'));
    const expansion = new Set(EXPANSION_MAP.map(row => row.indicator));
    expect(saved).toHaveLength(22);
    expect(saved.find(r => r['指標'] === '労働生産性')['国際比較_指標コード']).toBe('WB:NY.GDP.MKTP.KD ÷ WB:SL.TLF.TOTL.IN');
    expect(saved.some(r => r['国際比較_指標コード'].includes('SL.GDP.PCAP.EM.KD'))).toBe(false);
    expect(saved.some(r => expansion.has(r['指標']) || r['指標'] === '金融・保険業の付加価値')).toBe(false);
    expect(saved.find(r => r['指標'] === '客室数')['対応']).toBe('系列なし');
  });
});
