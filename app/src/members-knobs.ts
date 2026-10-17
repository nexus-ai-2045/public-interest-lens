/**
 * 議員ページのつまみ。配布データ（public-members/v2）の名前の一覧から、つまみの値で割合を計算し直し、並べ替える。
 * 円は切り捨てるので、配る額の合計は法律の額を超えない。初期値のときは配布データをそのまま使う。
 */
import type { Range } from './allocation-batch';
import { isDefaultKnobs, knobShares, type Knobs } from './causal-allocation';
import type { PublicMember, PublicMembers } from './members-build';

const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const scale = (amount: Range, fraction: number): Range => ({ low: Math.floor(amount.low * fraction), median: Math.floor(amount.median * fraction), high: Math.floor(amount.high * fraction) });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });

export function adjustMembers(data: PublicMembers, knobs: Knobs): PublicMember[] {
  if (isDefaultKnobs(knobs)) return data.members;
  const shares = new Map(data.laws.map(law => [law.id, { law, s: knobShares({ ...law.game.names, yes: law.game.yes, no: law.game.no }, knobs) }]));
  const adjusted = data.members.map(m => {
    let loss = zero(), credit = zero();
    const laws = m.laws.map(entry => {
      const { law, s } = shares.get(entry.lawId)!;
      const roles = s.persons.get(m.name) ?? {};
      const fraction = Object.values(roles).reduce((a, b) => a + (b ?? 0), 0);
      const share = scale(law.amount, fraction);
      if (law.side === 'loss') loss = add(loss, share); else credit = add(credit, share);
      return { ...entry, roles, fraction, share };
    }).sort((a, b) => b.share.median - a.share.median);
    const net = { low: credit.low - loss.high, median: credit.median - loss.median, high: credit.high - loss.low };
    return { ...m, loss, credit, net, laws };
  }).sort((a, b) => a.net.median - b.net.median || a.name.localeCompare(b.name));
  return adjusted.map((m, i) => ({ ...m, rank: i + 1 }));
}
