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

/** 正の整数の最大公約数。 */
function gcd(a: bigint, b: bigint): bigint {
  while (b !== 0n) { const t = a % b; a = b; b = t; }
  return a;
}

/**
 * 整数の比を、最も近い float64 にする（ちょうど中間なら偶数の仮数へ）。
 * 四則と BigInt だけを使う。Math.log / Math.exp は OS の数学ライブラリで最終ビットが変わり、同じ入力の公開 JSON が一致しなくなる。
 */
function ratioToNumber(numerator: bigint, denominator: bigint): number {
  if (denominator <= 0n) throw new Error(`分母が正ではありません: ${denominator}`);
  if (numerator === 0n) return 0;
  const negative = numerator < 0n;
  let num = negative ? -numerator : numerator;
  let den = denominator;
  const divisor = gcd(num, den);
  num /= divisor;
  den /= divisor;
  // num × 2^exp を [den × 2^52, den × 2^53) に置く。左シフトだけで合わせ、下位ビットを捨てない。
  let exp = 52 + den.toString(2).length - num.toString(2).length - 2;
  if (exp < 0) exp = 0;
  let scaled = num << BigInt(exp);
  while (scaled < (den << 52n)) { exp += 1; scaled = num << BigInt(exp); }
  let mantissa = scaled / den;
  const remainder = scaled % den;
  const twice = remainder << 1n;
  if (twice > den || (twice === den && (mantissa & 1n) === 1n)) mantissa += 1n;
  if (mantissa === (1n << 53n)) { mantissa >>= 1n; exp -= 1; }
  const value = Number(mantissa) / 2 ** exp;
  return negative ? -value : value;
}

/**
 * 拒否権者 k 人と、対称な賛成者 Y 人（q 人以上で可決）のゲームでの、拒否権者1人の Shapley 値。
 * 並び順をすべて等しく考え、その人が来た時点で他の拒否権者が全員そろい、賛成者が q 人以上いれば、その人が成立を決めたことになる。
 * φ = (1/n) Σ_{j=q..Y} C(Y, j) / C(n−1, j+k−1)、n = k + Y。
 * 比は C(Y, j) / C(n−1, j+k−1) = Π_{t=1..k-1} (j+t) / (Y+t) なので、分母を揃えて整数のまま足す。
 */
export function vetoShare(k: number, Y: number, q: number): number {
  if (k < 1 || q > Y) throw new Error(`ゲームが成り立ちません: k=${k} Y=${Y} q=${q}`);
  const n = BigInt(k + Y);
  let den = 1n;
  for (let t = 1; t <= k - 1; t++) den *= BigInt(Y + t);
  let sum = 0n;
  for (let j = Math.max(q, 0); j <= Y; j++) {
    let term = 1n;
    for (let t = 1; t <= k - 1; t++) term *= BigInt(j + t);
    sum += term;
  }
  return ratioToNumber(sum, n * den);
}

/** 参議院本会議で可決に必要な票数。 */
export const quota = (yes: number, no: number): number => Math.floor((yes + no) / 2) + 1;

export type CausalRole = 'proposer' | 'vote' | 'chair' | 'oppose';
export const ROLE_LABEL: Record<CausalRole, string> = { proposer: '提出者', vote: '参議院本会議で賛成', chair: '委員長（感度でだけ拒否権者）', oppose: '参議院本会議で反対（向きを逆に）' };

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

/**
 * 見え方のつまみ。どの値でも、人・党・名前不明・未帰属の割合の合計は1のままで、配る額の合計は法律の額を超えない。
 * - proposer：提出者の組の重み（0〜1）。減らした分は、衆議院の賛成会派と参議院の賛成票に、いまの割合どおりに回す。
 * - party：衆議院の分を党（会派）に置くか、参議院の賛成議員で分けるか。
 * - chairVeto：委員長も拒否権者にするか。
 * - rate：帰属率（0〜1）。残りは誰にも配らない（未帰属）。
 * - office：閣法の提出者（担当の大臣）の分を点数に入れるか。初期値は入れない（役職の帳簿として別に見せる。設計決定0014）。
 */
export type Knobs = { proposer: number; party: 'party' | 'voters'; chairVeto: boolean; rate: number; office: boolean };
export const DEFAULT_KNOBS: Knobs = { proposer: 1, party: 'party', chairVeto: false, rate: 1, office: false };
export const isDefaultKnobs = (k: Knobs): boolean => k.proposer === 1 && k.party === 'party' && !k.chairVeto && k.rate === 1 && !k.office;

export function knobShares(game: LawGame, knobs: Knobs): { persons: Map<string, Partial<Record<CausalRole, number>>>; party: number; unidentified: number; unattributed: number; vote: number } {
  const s = gameShares(game, knobs.chairVeto ? 'chair_veto' : 'base');
  const proposerTotal = s.veto;
  const moved = (1 - knobs.proposer) * proposerTotal;
  const voteTotal = s.vote * game.yes;
  let party = s.party + moved * s.party / (s.party + voteTotal);
  let votes = voteTotal + moved * voteTotal / (s.party + voteTotal);
  if (knobs.party === 'voters') { votes += party; party = 0; }
  const perVote = votes / game.yes;
  const persons = new Map<string, Partial<Record<CausalRole, number>>>();
  for (const [name, roles] of s.persons) {
    const out: Partial<Record<CausalRole, number>> = {};
    if (roles.proposer !== undefined) out.proposer = roles.proposer * knobs.proposer * knobs.rate;
    if (roles.chair !== undefined) out.chair = roles.chair * knobs.rate;
    if (roles.vote !== undefined) out.vote = perVote * knobs.rate;
    persons.set(name, out);
  }
  const voters = new Set(game.voters).size;
  // vote：賛成1票の割合（反対票にも同じ割合を向きを逆にして配る）。
  return { persons, party: party * knobs.rate, unidentified: perVote * (game.yes - voters) * knobs.rate, unattributed: 1 - knobs.rate, vote: perVote * knobs.rate };
}

/** URL の値からつまみを読む。範囲外や読めない値は初期値にする。 */
export function readKnobs(params: URLSearchParams): Knobs {
  const num = (key: string, d: number) => { const v = Number(params.get(key)); return params.has(key) && Number.isFinite(v) && v >= 0 && v <= 100 ? v / 100 : d; };
  return { proposer: num('p', 1), party: params.get('house') === 'voters' ? 'voters' : 'party', chairVeto: params.get('chair') === '1', rate: Math.max(num('r', 1), 0.1), office: params.get('office') === '1' };
}

export function writeKnobs(params: URLSearchParams, k: Knobs): URLSearchParams {
  const out = new URLSearchParams(params);
  for (const key of ['p', 'house', 'chair', 'r', 'office']) out.delete(key);
  if (k.proposer !== 1) out.set('p', String(Math.round(k.proposer * 100)));
  if (k.party !== 'party') out.set('house', k.party);
  if (k.chairVeto) out.set('chair', '1');
  if (k.rate !== 1) out.set('r', String(Math.round(k.rate * 100)));
  if (k.office) out.set('office', '1');
  return out;
}
