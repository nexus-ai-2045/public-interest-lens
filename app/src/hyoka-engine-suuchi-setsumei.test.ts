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
    expect(meetsCertaintyFloor('高')).toBe(true);
    expect(meetsCertaintyFloor('中')).toBe(true);
    expect(meetsCertaintyFloor('低')).toBe(false);
    expect(meetsCertaintyFloor('参考')).toBe(false);
    expect(meetsCertaintyFloor('')).toBe(false);
    expect(meetsCertaintyFloor('未知')).toBe(false);
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

  it('影響段階：|Δ|=2σ ちょうどは保留、すぐ上と持続の境界を分ける', () => {
    // 開始前の差 [1,2,3] → 平均2・標本σ=1（n−1）。2σ=2。
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
    // 等号 |Δ|=2σ → 保留（持続年を3にしても落ちない＝σ側で落ちる）
    expect(judgeImpact(base([4, 4, 4]))).toMatchObject({ stage: null, effect: 2, spread: 1 });
    // 2σ のすぐ上：Δ=2.1、3年連続同符号 → 段階1
    expect(judgeImpact(base([4.1, 4.1, 4.1]))).toMatchObject({ stage: 1, effect: 2.1, spread: 1 });
    // ばらつき倍率 2〜3：Δ=3 でも通る（倍率だけの下限は無い）
    expect(judgeImpact(base([5, 5, 5]))).toMatchObject({ stage: 1, effect: 3, spread: 1 });
    // 最長連続2年（[7,7,0]：効果と同符号が2年→段階1）と1年（[7,0,7]：最長1→保留）の組
    expect(judgeImpact(base([7, 7, 0]))).toMatchObject({ stage: 1, spread: 1 });
    expect(judgeImpact(base([7, 0, 7]))).toMatchObject({ stage: null, spread: 1 });
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

  it('個人配分は各人を独立に丸めるため、合計が損失×帰属率を超えうる（P1）', () => {
    // 損失2・帰属0.5・同じ重み2人 → 各人 round(2*0.5*0.5)=round(0.5)=1、合計2 > 理論上限1
    const two = allocateLoss({ low: 2, median: 2, high: 2 }, [
      { personId: 'A', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/a' },
      { personId: 'B', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/b' },
    ]);
    expect(two.map(x => x.shareYen.median)).toEqual([1, 1]);
    expect(two.reduce((s, x) => s + x.shareYen.median, 0)).toBeGreaterThan(2 * 0.5);

    // 中央値10・帰属0.5・重み1の3人 → 各 round(10*0.5/3)=round(1.666…)=2、合計6 > 上限5
    const three = allocateLoss({ low: 10, median: 10, high: 10 }, [
      { personId: 'A', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/a' },
      { personId: 'B', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/b' },
      { personId: 'C', action: 'vote', position: 'other', evidenceUrl: 'https://example.go.jp/c' },
    ]);
    expect(three.map(x => x.shareYen.median)).toEqual([2, 2, 2]);
    expect(three.reduce((s, x) => s + x.shareYen.median, 0)).toBe(6);
    expect(6).toBeGreaterThan(10 * 0.5);
  });

  it('影響段階の分岐は排他：経済全体通過後、傾きか規模が欠ければ段階2、そろえば段階3', () => {
    const years = (gaps: number[], from = 1995): ImpactPoint[] =>
      gaps.map((g, i) => ({ asOf: `${from + i}-03-31`, treated: 10 + g, control: 10 }));
    // 開始前ほぼ0、開始後に差が開く（基本通過）。低いほど良い → 負の効果が貢献。
    const clear = [0, 0.1, -0.1, 0.05, 0, -0.5, -3, -3, -3.1, -3];
    const economy = { definition: '特性', better: 'higher' as const, points: years(clear.map(g => -g)) };
    expect(judgeImpact({
      definition: '特性', start: '1999-10-01', better: 'lower', target: years(clear),
      economy, sectorGdpShare: null,
    }).stage).toBe(2);
    expect(judgeImpact({
      definition: '特性', start: '1999-10-01', better: 'lower', target: years(clear),
      economy, sectorGdpShare: 0.05,
    }).stage).toBe(3);
  });
});
