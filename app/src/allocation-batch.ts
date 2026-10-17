/**
 * 配分 allocation-v1：法律ごとの損失額・便益額を、確認できた個人の行動に按分し、人ごとに合計する。
 * 按分そのものは loss-rule.ts の allocateLoss だけで行い、ここでは入力の整形・重みの変種・合計・順位だけをする。
 * 人物名はデータとして受け取るだけで、このファイルにもテストにも実在の名前は書かない。
 */
import { allocateLoss, type Action, type Involvement, type Position } from './loss-rule';

export type Range = { low: number; median: number; high: number };
/** 重みの変種。基準は設計 §2-4 の表。行動重視は立場の重みをすべて1、立場重視は行動の重みをすべて1にする。 */
export type Variant = 'base' | 'action_only' | 'position_only';
export const VARIANT_LABEL: Record<Variant, string> = { base: '基準', action_only: '行動重視', position_only: '立場重視' };
export const VARIANTS: Variant[] = ['base', 'action_only', 'position_only'];
export const RATES = [0.3, 0.5, 0.7];
export const BASE_RATE = 0.5;
/** 順位がこの数以上動いた人に印を付ける。 */
export const RANK_MOVE_FLAG = 5;

export type Law = {
  lawId: string;
  title: string;
  /** loss は損失（国賊側）、benefit は便益（国士側）。 */
  side: 'loss' | 'benefit';
  publishable: boolean;
  group: string;
  /** publish.csv の額そのもの（円）。便益は負。low は第1四分位、high は第3四分位。 */
  amount: Range;
};

export type AllocationRow = { lawId: string; variant: Variant; rate: number; personId: string; weight: number; share: Range };

/** 「中央値=…;第1四分位=…;第3四分位=…」から額を読む。無ければ null。 */
export function parseAmount(text: string): Range | null {
  const m = /中央値=(-?\d+);第1四分位=(-?\d+);第3四分位=(-?\d+)/.exec(text);
  return m ? { median: Number(m[1]), low: Number(m[2]), high: Number(m[3]) } : null;
}

/** 変種に合わせて行動・立場を置き換える。allocateLoss の重み表を変えずに、同じ関数で計算できるようにする。 */
export function applyVariant(involvements: Involvement[], variant: Variant): Involvement[] {
  if (variant === 'action_only') return involvements.map(v => ({ ...v, position: 'other' as Position }));
  if (variant === 'position_only') return involvements.map(v => ({ ...v, action: 'vote' as Action }));
  return involvements;
}

/**
 * 最大剰余法で整数の円に配る。合計は target にぴったり一致する。
 * 重みは 0.5 刻みなので 2 倍して整数にし、BigInt で厳密に割る。余りが同じなら重みの大きい方、それも同じなら氏名順。
 */
export function distributeLargestRemainder(target: number, items: { personId: string; weight: number }[]): Map<string, number> {
  const out = new Map<string, number>();
  if (items.length === 0) return out;
  const sign = target < 0 ? -1n : 1n;
  const t = BigInt(Math.abs(target));
  const ws = items.map(i => BigInt(Math.round(i.weight * 2)));
  const total = ws.reduce((a, b) => a + b, 0n);
  const parts = items.map((it, k) => ({ it, base: (t * ws[k]) / total, rem: (t * ws[k]) % total }));
  let left = t - parts.reduce((s, p) => s + p.base, 0n);
  const order = [...parts].sort((a, b) => (a.rem === b.rem ? 0 : a.rem > b.rem ? -1 : 1) || b.it.weight - a.it.weight || a.it.personId.localeCompare(b.it.personId));
  for (const p of order) if (left > 0n) { p.base += 1n; left -= 1n; }
  for (const p of parts) out.set(p.it.personId, Number(sign * p.base));
  return out;
}

/** 帰属額（額 × 帰属率を円に丸めたもの）を、allocateLoss の重みどおりに最大剰余法で配る。 */
export function allocateExact(amount: Range, involvements: Involvement[], rate: number): { personId: string; weight: number; share: Range }[] {
  const base = allocateLoss(amount, involvements, rate);
  const dist = (x: number) => distributeLargestRemainder(Math.round(x * rate), base);
  const low = dist(amount.low), median = dist(amount.median), high = dist(amount.high);
  return base.map(a => ({ personId: a.personId, weight: a.weight, share: { low: low.get(a.personId)!, median: median.get(a.personId)!, high: high.get(a.personId)! } }));
}

export function allocateAll(laws: Law[], involvementsByLaw: Map<string, Involvement[]>): AllocationRow[] {
  const rows: AllocationRow[] = [];
  for (const law of laws) {
    const inv = involvementsByLaw.get(law.lawId) ?? [];
    for (const variant of VARIANTS) {
      for (const rate of RATES) {
        for (const a of allocateExact(law.amount, applyVariant(inv, variant), rate)) {
          rows.push({ lawId: law.lawId, variant, rate, personId: a.personId, weight: a.weight, share: a.share });
        }
      }
    }
  }
  return rows;
}

const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });
const zero = (): Range => ({ low: 0, median: 0, high: 0 });

export type LawTotal = { lawId: string; variant: Variant; rate: number; persons: number; attributed: Range; unattributed: Range };

/** 法律ごとの帰属額（個人の配分の合計）と未帰属額（額 − 帰属額）。 */
export function lawTotals(laws: Law[], rows: AllocationRow[]): LawTotal[] {
  const out: LawTotal[] = [];
  for (const law of laws) for (const variant of VARIANTS) for (const rate of RATES) {
    const mine = rows.filter(r => r.lawId === law.lawId && r.variant === variant && r.rate === rate);
    const attributed = mine.reduce((s, r) => add(s, r.share), zero());
    out.push({ lawId: law.lawId, variant, rate, persons: mine.length, attributed,
      unattributed: { low: law.amount.low - attributed.low, median: law.amount.median - attributed.median, high: law.amount.high - attributed.high } });
  }
  return out;
}

/** 損失の配分はそのまま（正）、便益の配分は符号を反転して貢献（正）にする。幅は小さい方を low にそろえる。 */
export function toLossCredit(side: Law['side'], share: Range): { loss: Range; credit: Range } {
  if (side === 'loss') return { loss: { ...share }, credit: zero() };
  const c = [-share.low, -share.high].sort((a, b) => a - b);
  return { loss: zero(), credit: { low: c[0], median: -share.median, high: c[1] } };
}

export type PersonTotal = {
  personId: string;
  variant: Variant;
  rate: number;
  loss: Range;
  credit: Range;
  /** 純額 = 貢献 − 損失。low は 貢献low − 損失high、high は 貢献high − 損失low。 */
  net: Range;
  /** 公開可の法律だけで数えた純額（中央値）。 */
  netPublishableMedian: number;
  laws: string[];
  nonPublishableLaws: string[];
  /** 同じ観測グループの法律を2本以上合計した（額が重なる）か。 */
  overlappingGroups: string[];
};

export function personTotals(laws: Law[], rows: AllocationRow[]): PersonTotal[] {
  const byLaw = new Map(laws.map(l => [l.lawId, l]));
  const acc = new Map<string, PersonTotal>();
  for (const r of rows) {
    const law = byLaw.get(r.lawId)!;
    const key = `${r.variant}|${r.rate}|${r.personId}`;
    const p = acc.get(key) ?? { personId: r.personId, variant: r.variant, rate: r.rate, loss: zero(), credit: zero(), net: zero(),
      netPublishableMedian: 0, laws: [], nonPublishableLaws: [], overlappingGroups: [] };
    const { loss, credit } = toLossCredit(law.side, r.share);
    p.loss = add(p.loss, loss);
    p.credit = add(p.credit, credit);
    if (law.publishable) p.netPublishableMedian += credit.median - loss.median;
    else p.nonPublishableLaws.push(law.lawId);
    p.laws.push(law.lawId);
    acc.set(key, p);
  }
  for (const p of acc.values()) {
    p.net = { low: p.credit.low - p.loss.high, median: p.credit.median - p.loss.median, high: p.credit.high - p.loss.low };
    const groups = new Map<string, number>();
    for (const id of p.laws) { const g = byLaw.get(id)!.group; if (g) groups.set(g, (groups.get(g) ?? 0) + 1); }
    p.overlappingGroups = [...groups].filter(([, n]) => n > 1).map(([g]) => g).sort();
  }
  return [...acc.values()].sort((a, b) => a.variant.localeCompare(b.variant) || a.rate - b.rate || a.net.median - b.net.median || a.personId.localeCompare(b.personId));
}

/** 純額の小さい順（国賊側が上）の順位。同じ額は同じ順位（1,2,2,4）。 */
export function ranks(totals: PersonTotal[], variant: Variant, rate: number): Map<string, number> {
  const xs = totals.filter(t => t.variant === variant && t.rate === rate).sort((a, b) => a.net.median - b.net.median);
  const out = new Map<string, number>();
  xs.forEach((t, i) => out.set(t.personId, i > 0 && xs[i - 1].net.median === t.net.median ? out.get(xs[i - 1].personId)! : i + 1));
  return out;
}

export type PersonRank = { personId: string; base: number; actionOnly: number; positionOnly: number; maxMove: number; flagged: boolean };

export function rankSensitivity(totals: PersonTotal[], rate = BASE_RATE): PersonRank[] {
  const b = ranks(totals, 'base', rate), a = ranks(totals, 'action_only', rate), p = ranks(totals, 'position_only', rate);
  return [...b.keys()].map(id => {
    const maxMove = Math.max(Math.abs(b.get(id)! - (a.get(id) ?? b.get(id)!)), Math.abs(b.get(id)! - (p.get(id) ?? b.get(id)!)));
    return { personId: id, base: b.get(id)!, actionOnly: a.get(id)!, positionOnly: p.get(id)!, maxMove, flagged: maxMove >= RANK_MOVE_FLAG };
  }).sort((x, y) => x.base - y.base || x.personId.localeCompare(y.personId));
}
