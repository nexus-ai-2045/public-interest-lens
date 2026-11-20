/**
 * 評価エンジン数値説明（docs/hyoka-engine-suuchi-setsumei.md）の特性テスト。
 * 挙動は変えない。文書に書いた定数・境界が実装と一致することを固定する。
 */
import { describe, expect, it } from 'vitest';
import { SCORING_CONSTANTS, meetsCertaintyFloor } from './scoring-constants';
import {
  DEFAULT_ROLE_RATIO, HOUSE_SPLIT, HIDDEN_DOMINANCE_REST_MIN, buildExposureRanking,
  type ExposureGroup, type Involvement, type Range,
} from './exposure-ranking';
import { judgeImpact, type ImpactPoint, type ImpactSeries } from './impact-rule';
import { ACTION_WEIGHT, POSITION_WEIGHT, allocateLoss, MAX_LOSS_YEARS } from './loss-rule';
import { ROLE_FACTOR } from './ranking';
import { COVID_CUTOFF_YEAR, COVID_YEARS } from './benefit-rule';

const yen = (median: number): Range => ({ low: median, median, high: median });
const group = (id: string, median: number, lawCount = 1): ExposureGroup =>
  ({ kind: 'group-diff', id, group: id, window: '2000〜2005年', diff: yen(median), benchmark: '特性テスト', lawCount });
const inv = (actorId: string, lawId: string, role: Involvement['role'], weight = 1): Involvement =>
  ({ actorKind: 'person', actorId, groupId: 'g1', lawId, role, weight, ...(role === 'yes' || role === 'no' ? { house: 'upper' as const } : {}) });

describe('数値説明ドキュメントと定数の一致', () => {
  it('点数設計 v2.1 の固定定数は文書どおり', () => {
    expect(SCORING_CONSTANTS).toEqual({
      hitRateFloor: 0.8,
      minContributingLaws: 5,
      topThreeShareCap: 0.5,
      certaintyFloor: '中',
    });
    expect(meetsCertaintyFloor('中')).toBe(true);
    expect(meetsCertaintyFloor('低')).toBe(false);
  });

  it('曝露の役割比率・院分割・伏せ閾値は文書どおり（合計1）', () => {
    expect(DEFAULT_ROLE_RATIO).toEqual({ proposer: 0.4, yes: 0.2, no: 0.2, cabinet: 0.2 });
    expect(Object.values(DEFAULT_ROLE_RATIO).reduce((a, b) => a + b, 0)).toBeCloseTo(1);
    expect(HOUSE_SPLIT).toBe(0.5);
    expect(HIDDEN_DOMINANCE_REST_MIN).toBe(0.1);
  });

  it('損失の行動・立場重みと累積年数上限は文書どおり', () => {
    expect(ACTION_WEIGHT).toEqual({ decide: 5, amend: 4, chair: 3, question: 2, vote: 1 });
    expect(POSITION_WEIGHT).toEqual({ prime_minister: 3, minister_or_party_exec: 2, vice_minister_or_chair: 1.5, other: 1 });
    expect(MAX_LOSS_YEARS).toBe(10);
  });

  it('関与係数 ROLE_FACTOR とコロナ窓は文書どおり', () => {
    expect(ROLE_FACTOR).toEqual({ lead: 1, coauthor: 0.5, vote: 0.25, context: 0 });
    expect(COVID_YEARS).toEqual([2020, 2021, 2022]);
    expect(COVID_CUTOFF_YEAR).toBe(2019);
  });
});

describe('文書の計算境界（挙動を変えない特性）', () => {
  it('発議だけの曝露は群の差×0.4（1本・関与あり）', () => {
    const out = buildExposureRanking(
      [group('g1', 1000)],
      [inv('甲', 'L1', 'proposer')],
      { roleRatio: DEFAULT_ROLE_RATIO, minLaws: 1, topThreeShareCap: 1 },
    );
    expect(out.people.find(p => p.actorId === '甲')!.exposureYen.median).toBeCloseTo(400);
    // 賛成・反対・閣議の枠は未配分に残る（比率の残り 0.6。反対は符号反転で期待値は 0.4-0.2+0.2+0.2=0.6 ではない：
    // expected = Σ sign_r * ratio_r * G = (0.4+0.2-0.2+0.2)*1000 = 600）
    expect(out.totals.expected.median).toBeCloseTo(600);
  });

  it('影響段階：|Δ|=2σ ちょうどは保留、|Δ|>2σ かつ2年連続なら段階1', () => {
    // 開始前の差 [1,2,3] → 平均2・標本σ=1。2σ=2。
    // 開始後（1年目除外）の差の平均が4なら Δ=2 で等号→保留。平均が5なら Δ=3→段階1。
    const pts = (gaps: number[], from: number): ImpactPoint[] =>
      gaps.map((g, i) => ({ asOf: `${from + i}-12-31`, treated: 10 + g, control: 10 }));
    const base = (postGaps: number[]): ImpactSeries => ({
      definition: '特性',
      start: '2000-01-01',
      better: 'higher',
      target: [...pts([1, 2, 3], 1997), ...pts([0, ...postGaps], 2000)],
      economy: null,
      sectorGdpShare: null,
    });
    expect(judgeImpact(base([4, 4, 4]))).toMatchObject({ stage: null, effect: 2, spread: 1 });
    expect(judgeImpact(base([5, 5, 5]))).toMatchObject({ stage: 1, effect: 3, spread: 1 });
  });

  it('個人配分の既定帰属率0.5：decide×大臣=10 と vote×other=1 で按分', () => {
    const a = allocateLoss({ low: 100, median: 200, high: 400 }, [
      { personId: 'A', action: 'decide', position: 'minister_or_party_exec', evidenceUrl: 'https://example.go.jp/1' },
      { personId: 'B', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/2' },
    ]);
    expect(a.map(x => [x.personId, x.weight])).toEqual([['A', 10], ['B', 1]]);
    // 200 * 0.5 * 10/11 → 91、200 * 0.5 * 1/11 → 9
    expect(a[0].shareYen.median).toBe(91);
    expect(a[1].shareYen.median).toBe(9);
    expect(a.reduce((s, x) => s + x.shareYen.median, 0)).toBe(100);
  });
});
