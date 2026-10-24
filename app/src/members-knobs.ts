/**
 * 議員ページのつまみ。配布データ（public-members/v2）の名前の一覧から、つまみの値で割合を計算し直し、並べ替える。
 * 円は切り捨てるので、配る額の合計は法律の額を超えない。初期値のときは配布データをそのまま使う。
 */
import type { Range } from './allocation-batch';
import { isDefaultKnobs, knobShares, type Knobs } from './causal-allocation';
import { allocatedAmount, type PublicMember, type PublicMembers } from './members-build';

const zero = (): Range => ({ low: 0, median: 0, high: 0 });
const scale = (amount: Range, fraction: number): Range => ({ low: Math.floor(amount.low * fraction), median: Math.floor(amount.median * fraction), high: Math.floor(amount.high * fraction) });
const add = (a: Range, b: Range): Range => ({ low: a.low + b.low, median: a.median + b.median, high: a.high + b.high });

export function adjustMembers(data: PublicMembers, knobs: Knobs): PublicMember[] {
  if (isDefaultKnobs(knobs)) return data.members;
  const shares = new Map(data.laws.map(law => [law.id, { law, s: knobShares({ ...law.game.names, yes: law.game.yes, no: law.game.no }, knobs) }]));
  const adjusted = data.members.map(m => {
    let loss = zero(), credit = zero();
    const office = { loss: zero(), credit: zero() };
    const laws = m.laws.map(entry => {
      const { law, s } = shares.get(entry.lawId)!;
      if (entry.direction === 'against') {
        // 反対票は、いまのつまみで計算し直した賛成1票と同じ割合（帰属率を含む）。
        const fraction = s.vote;
        const share = scale(allocatedAmount(law), fraction);
        if (law.side === 'loss') credit = add(credit, share); else loss = add(loss, share);
        return { ...entry, fraction, share };
      }
      const roles = s.persons.get(m.id) ?? {};
      const fraction = Object.values(roles).reduce((a, b) => a + (b ?? 0), 0);
      const full = scale(allocatedAmount(law), fraction);
      // 閣法の提出者の分は、つまみ office が入っていなければ役職の帳簿へ。
      const officeShare = law.game.cabinet && !knobs.office && roles.proposer ? scale(allocatedAmount(law), roles.proposer) : zero();
      const share = { low: full.low - officeShare.low, median: full.median - officeShare.median, high: full.high - officeShare.high };
      if (law.side === 'loss') { loss = add(loss, share); office.loss = add(office.loss, officeShare); }
      else { credit = add(credit, share); office.credit = add(office.credit, officeShare); }
      return { ...entry, roles, fraction, share, office: officeShare };
    }).sort((a, b) => b.share.median + b.office.median - a.share.median - a.office.median);
    const net = { low: credit.low - loss.high, median: credit.median - loss.median, high: credit.high - loss.low };
    return { ...m, loss, credit, office, net, laws };
  }).sort((a, b) => a.net.median - b.net.median || a.id.localeCompare(b.id));
  return adjusted.map((m, i) => ({ ...m, rank: i + 1 }));
}
