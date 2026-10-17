/**
 * この人が失わせた額・生んだ額（causal-shapley-v1）。
 * 「この人の行動が無かったら、法律は成立したか」を、成立のしくみ（投票ゲーム）の Shapley 値で測り、法律の額をその割合で配る。
 *
 * 成立のしくみ：
 * - 提出者（閣法は内閣、衆法は発議者）と衆議院の賛成会派は、どちらが欠けても成立しない（拒否権者）。
 * - 参議院本会議は過半数で決まる。賛成した議員は対称で、可決に必要な票数 q = floor((賛成+反対)/2) + 1。
 * - 委員長は委員会の多数決と中間報告の道があるため、基準では拒否権者にしない（感度で拒否権者にした場合も出す）。
 * - 質疑・修正案は成立を左右しないので配らない（記録として表示だけする）。
 * 衆議院は起立採決で個人の賛否が残らないため、衆議院の分は会派（党）に置き、個人には配らない。
 */
import type { Range } from './allocation-batch';

/** log C(n, r)。 */
function logChoose(n: number, r: number): number {
  if (r < 0 || r > n) return -Infinity;
  let s = 0;
  for (let i = 1; i <= r; i++) s += Math.log(n - r + i) - Math.log(i);
  return s;
}

/**
 * 拒否権者 k 人と、対称な賛成者 Y 人（q 人以上で可決）のゲームでの、拒否権者1人の Shapley 値。
 * 並び順をすべて等しく考え、その人が来た時点で他の拒否権者が全員そろい、賛成者が q 人以上いれば、その人が成立を決めたことになる。
 * φ = (1/n) Σ_{j=q..Y} C(Y, j) / C(n−1, j+k−1)、n = k + Y。
 */
export function vetoShare(k: number, Y: number, q: number): number {
  if (k < 1 || q > Y) throw new Error(`ゲームが成り立ちません: k=${k} Y=${Y} q=${q}`);
  const n = k + Y;
  let s = 0;
  for (let j = Math.max(q, 0); j <= Y; j++) s += Math.exp(logChoose(Y, j) - logChoose(n - 1, j + k - 1));
  return s / n;
}

/** 参議院本会議で可決に必要な票数。 */
export const quota = (yes: number, no: number): number => Math.floor((yes + no) / 2) + 1;

export type CausalRole = 'proposer' | 'vote' | 'chair';
export const ROLE_LABEL: Record<CausalRole, string> = { proposer: '提出者', vote: '参議院本会議で賛成', chair: '委員長（感度でだけ拒否権者）' };

export type LawGame = {
  /** 提出者として記録のある人（重複なし）。この組で拒否権者1人分を等分する。 */
  proposers: string[];
  /** 参議院本会議で賛成した、名前の確かめられた人。 */
  voters: string[];
  /** 本件の委員会の委員長（重複なし）。 */
  chairs: string[];
  yes: number;
  no: number;
};

export type CausalVariant = 'base' | 'chair_veto';
export const CAUSAL_VARIANTS: CausalVariant[] = ['base', 'chair_veto'];

export type GameShares = {
  /** 拒否権者1人（提出者の組・衆議院の賛成会派）の割合。 */
  veto: number;
  /** 賛成票1票の割合。 */
  vote: number;
  q: number;
  k: number;
  /** 人ごとの割合（役割ごと）。 */
  persons: Map<string, Partial<Record<CausalRole, number>>>;
  /** 衆議院の賛成会派（党）に置く割合。 */
  party: number;
  /** 名前の確かめられない賛成票の割合。 */
  unidentified: number;
};

export function gameShares(game: LawGame, variant: CausalVariant): GameShares {
  if (game.proposers.length === 0) throw new Error('提出者の記録がありません');
  const chairs = variant === 'chair_veto' ? game.chairs : [];
  const k = 2 + chairs.length;
  const q = quota(game.yes, game.no);
  const veto = vetoShare(k, game.yes, q);
  const vote = (1 - k * veto) / game.yes;
  const persons = new Map<string, Partial<Record<CausalRole, number>>>();
  const add = (name: string, role: CausalRole, x: number) => {
    const cur = persons.get(name) ?? {};
    cur[role] = (cur[role] ?? 0) + x;
    persons.set(name, cur);
  };
  for (const p of game.proposers) add(p, 'proposer', veto / game.proposers.length);
  for (const c of chairs) add(c, 'chair', veto);
  const voters = [...new Set(game.voters)];
  if (voters.length > game.yes) throw new Error(`賛成者の記録（${voters.length}）が賛成票（${game.yes}）より多い`);
  for (const v of voters) add(v, 'vote', vote);
  return { veto, vote, q, k, persons, party: veto, unidentified: vote * (game.yes - voters.length) };
}

/** 割合を整数の円に直す。人・党・名前不明の合計が額にぴったり一致するよう、端数は最大剰余法で配る。 */
export function toYen(amount: number, parts: { id: string; fraction: number }[]): Map<string, number> {
  const sign = amount < 0 ? -1 : 1;
  const t = Math.abs(amount);
  const rows = parts.map(p => ({ id: p.id, exact: t * p.fraction, base: Math.floor(t * p.fraction) }));
  let left = t - rows.reduce((s, r) => s + r.base, 0);
  for (const r of [...rows].sort((a, b) => (b.exact - b.base) - (a.exact - a.base) || a.id.localeCompare(b.id))) if (left > 0) { r.base += 1; left -= 1; }
  return new Map(rows.map(r => [r.id, sign * r.base]));
}

export const PARTY_ID = '\u0000衆議院の賛成会派';
export const UNIDENTIFIED_ID = '\u0000名前不明の賛成票';

export type CausalRow = { personId: string; fraction: number; roles: Partial<Record<CausalRole, number>>; share: Range };

/** 1本の法律の額を、Shapley の割合で人・党に配る。 */
export function allocateLaw(amount: Range, game: LawGame, variant: CausalVariant): { shares: GameShares; rows: CausalRow[]; party: Range; unidentified: Range } {
  const shares = gameShares(game, variant);
  const parts = [...shares.persons].map(([id, roles]) => ({ id, fraction: Object.values(roles).reduce((s, x) => s + (x ?? 0), 0) }));
  parts.push({ id: PARTY_ID, fraction: shares.party }, { id: UNIDENTIFIED_ID, fraction: shares.unidentified });
  const low = toYen(amount.low, parts), median = toYen(amount.median, parts), high = toYen(amount.high, parts);
  const pick = (id: string): Range => ({ low: low.get(id)!, median: median.get(id)!, high: high.get(id)! });
  const rows = parts.filter(p => p.id !== PARTY_ID && p.id !== UNIDENTIFIED_ID)
    .map(p => ({ personId: p.id, fraction: p.fraction, roles: shares.persons.get(p.id)!, share: pick(p.id) }));
  return { shares, rows, party: pick(PARTY_ID), unidentified: pick(UNIDENTIFIED_ID) };
}
