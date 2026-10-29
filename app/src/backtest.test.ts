// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { foreignSignLabel, formatPercent, formatRate, parseBacktest, signLabel } from './backtest';

describe('バックテストの配布データ', () => {
  const data = parseBacktest(readFileSync(new URL('../public/distribution/backtest.json', import.meta.url), 'utf8'));
  it('v1 が最初の測定として入っている', () => expect(data.runs[0].label).toBe('v1'));
  it('件数が10件未満の段は判定不能で、達成と書かない', () => {
    for (const run of data.runs) for (const lv of run.levels) if (lv.n < run.min_n) expect(lv.verdict).toBe('判定不能');
  });
  it('一致した数が採点した数を超えない', () => {
    for (const run of data.runs) for (const lv of run.levels) { expect(lv.hits).toBeLessThanOrEqual(lv.n); expect(lv.cases.length).toBe(lv.n); }
  });
  it('形が違うデータは読まない', () => expect(() => parseBacktest('{"schema":"x"}')).toThrow());
});
describe('外国の研究から日本の向きを当てる（v2）', () => {
  const data = parseBacktest(readFileSync(new URL('../public/distribution/backtest.json', import.meta.url), 'utf8'));
  const v2 = data.runs.find(r => r.label === 'v2');
  it('v2 の測定が入っていて、v1 は残っている', () => { expect(v2?.transplant).toBeTruthy(); expect(data.runs[0].label).toBe('v1'); });
  it('件数か政策グループが足りない段は判定不能で、達成と書かない', () => {
    for (const run of data.runs) if (run.transplant) for (const lv of run.transplant.levels) if (lv.n < run.transplant.min_n || lv.groups < run.transplant.min_groups) expect(lv.verdict).toBe('判定不能');
  });
  it('一致した数が予測を出せた数を超えず、出せなかった事例は外れに数えない', () => {
    for (const run of data.runs) if (run.transplant) for (const lv of run.transplant.levels) {
      const predicted = lv.cases.filter(c => c.predicted !== null);
      expect(predicted.length).toBe(lv.n);
      expect(lv.hits).toBeLessThanOrEqual(lv.n);
      for (const c of lv.cases) if (c.predicted === null) expect(c.hit).toBe(false);
    }
  });
  it('外国の向きを読む', () => { expect(foreignSignLabel(0)).toBe('効果なし'); expect(foreignSignLabel(null)).toBe('—'); });
});
describe('表示の整形', () => {
  it('一致率と区間を読む', () => {
    expect(formatRate({ rate: 1 / 9, wilson95: [0.02, 0.44] })).toBe('11%（2〜44%）');
    expect(formatRate({ rate: null, wilson95: null })).toBe('—');
    expect(formatPercent(0.95)).toBe('95%');
  });
  it('向きを読む', () => { expect(signLabel(1)).toContain('国士'); expect(signLabel(-1)).toContain('国賊'); });
});
