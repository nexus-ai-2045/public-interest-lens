/** 全法律・政策の一覧（laws.json）と、開いた時に読む詳細（laws-detail.json）の型と、絞り込み・並べ替え。 */

import { lawNameText, type WhatWithheld } from './law-name';

export const lawsCatalogUrl = '/distribution/laws.json';
/** 詳細は束ごとに分けてある（法律は提出回次、政策は policy）。scripts/build_laws_catalog.py の bundle_of と同じ規則。 */
export function detailBundleUrl(id: string): string {
  const match = /^(?:閣法|衆法|参法)-(\d+)-\d+$/.exec(id);
  return `/distribution/laws-detail/${match ? match[1] : 'policy'}.json`;
}

/** 兆円・億円の単位で丸めて読む。幅は必ず一緒に出す。 */
export function formatYen(value: number): string {
  if (value < 0) return `−${formatYen(-value)}`;
  if (value >= 1e12) return `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value / 1e12)}兆円`;
  return `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 0 }).format(value / 1e8)}億円`;
}

export type CatalogStep = 'enacted' | 'evaluated' | 'dated' | 'staged' | 'amounted' | 'published';
export type CatalogAmount = { median: number; low: number; high: number };
/** 同じ観測（指標の系列＋期間）を共有する法律のまとまり。代表は id 昇順の先頭の1本。額は共有なので足し合わせない。 */
export type CatalogObservation = { key: string; size: number; representative: boolean; representativeId?: string };
/** 額が日本の付加価値1年分を超える法律に付く印。順位は変えず、印と倍率だけ付く。 */
export const OUTLIER_MARK = '額が日本の付加価値1年分を超える（桁外れ。参考にとどめる）';
export const isOutlierMark = (mark: string) => mark.startsWith('額が日本の付加価値1年分を超える');
export type CatalogItem = {
  id: string;
  kind: string;
  title: string;
  year: number | null;
  field: string;
  side: 'loss' | 'benefit' | null;
  amount: CatalogAmount | null;
  certainty?: '高' | '中' | '低' | '参考';
  marks: string[];
  step: CatalogStep;
  /** 参考の額を画面に出さない理由（検証で不合格／他の法律と同じ額／桁外れ）。ある法律は額を持たない。 */
  /** 何をする法律か（国会会議録の提案理由の説明を AI が1行に要約）。 */
  what?: string;
  /** what が無いときの理由（画面は題名から作らず、正式名だけを理由つきで出す）。 */
  whatWithheld?: WhatWithheld;
  summary: string;
  membersTotal?: number;
  href?: string;
  /** 額のある法律だけ。同じ観測を共有する法律の数と、この行が代表かどうか。 */
  observation?: CatalogObservation;
  /** 額が日本の付加価値1年分を超えるときだけ。額が1年分の何倍か。 */
  scale?: number;
};
export type LawsCatalog = {
  schema: 'public-laws/v1';
  counts: Record<CatalogStep, number>;
  /** 額を出さなかった本数（理由ごと）。 */
  /** 公開ランキングで段階を通った本数（全体指標の参考の額を含まない）。 */
  strict?: { evaluated: number; dated: number; staged: number };
  /** 観測の数（count）と、桁外れの印の本数（outliers）。 */
  observations?: { count: number; outliers: number };
  fields: string[];
  laws: CatalogItem[];
  policies: CatalogItem[];
};
/** text が空のときは要約しなかった理由。shared＝ほかの法案と同じ発言でどの法案の話か決められない、unread＝抜粋から中身を読み取れなかった。 */
// withheld が 'other'（この法律の発言ではなかった）・'unchecked'（まだ確かめていない）のときは、URL・発言者・日付を持たない
export type OverviewQuote = { text: string; url?: string; speaker?: string; date?: string; withheld?: 'shared' | 'unread' | 'other' | 'unchecked' };
/** 冒頭の概要。passage・parties は議案情報の事実、what・aim・concern は会議録の AI 要約、result はこのサイトの計算。 */
export type CatalogOverview = {
  passage: string;
  parties?: { yes: string[]; no: string[] };
  what?: OverviewQuote;
  aim?: OverviewQuote;
  concern?: OverviewQuote;
  result: string;
};
export type ChainStep = { step: string; result: string; note: string };
/** 額の物差し三欄（設計決定0024）。付加価値の変化だけが順位に使われうる（ranked）。国の収支は足さない別表、採算は参考。値のある欄だけ入る。 */
export type CatalogColumns = {
  valueAdded?: { yen: number; origin: string; certainty: string; ranked: boolean };
  fiscalOku?: number;
  fiscalOrigin?: string;
  spendYen?: number;
  profitability?: number;
  profitabilityNote?: string;
};
export type CatalogDetail = {
  columns?: CatalogColumns;
  proposer?: string;
  promulgatedOn?: string | null;
  enforcedOn?: string;
  indicator?: string;
  stage?: string;
  window?: string;
  comparison?: string[];
  group?: string;
  chain: ChainStep[];
  sources: { label: string; url: string }[];
  members?: { id: string; name: string; median: number; roles: string[] }[];
  attributed?: CatalogAmount;
  people?: { name: string; note: string }[];
  overview?: CatalogOverview;
};

export const STEP_LABEL: Record<CatalogStep, string> = {
  enacted: '振り分けで止まった',
  evaluated: '施行日の確認で止まった',
  dated: '影響の判定で止まった',
  staged: '額の計算で止まった',
  amounted: '参考の額',
  published: '確かな額',
};
const STEP_ORDER: CatalogStep[] = ['enacted', 'evaluated', 'dated', 'staged', 'amounted', 'published'];

export function parseLawsCatalog(text: string): LawsCatalog {
  const data = JSON.parse(text) as LawsCatalog;
  if (data.schema !== 'public-laws/v1' || !Array.isArray(data.laws) || !Array.isArray(data.policies)) throw new Error('laws.json の形が違います');
  for (const item of [...data.laws, ...data.policies]) {
    if (typeof item.id !== 'string' || typeof item.title !== 'string' || !STEP_ORDER.includes(item.step)) throw new Error(`行の形が違います: ${String(item.id)}`);
    if (item.observation && (typeof item.observation.key !== 'string' || !(item.observation.size >= 1) || (!item.observation.representative && typeof item.observation.representativeId !== 'string'))) throw new Error(`観測の形が違います: ${item.id}`);
    if (item.scale !== undefined && !(item.scale > 1)) throw new Error(`桁外れの倍率が1を超えていません: ${item.id}`);
    if (item.amount && !(item.amount.low <= item.amount.median && item.amount.median <= item.amount.high)) throw new Error(`額の幅が中央値を挟んでいません: ${item.id}`);
  }
  return data;
}

export type SideFilter = 'all' | 'confirmed' | 'loss' | 'benefit' | 'amount' | 'none';
export type SortKey = 'amount' | 'loss' | 'benefit' | 'newest' | 'oldest' | 'progress';
export type CatalogQuery = { text: string; side: SideFilter; field: string; kind: string; sort: SortKey };
export const DEFAULT_QUERY: CatalogQuery = { text: '', side: 'all', field: '', kind: '', sort: 'amount' };

const normalize = (value: string) => value.normalize('NFKC').toLowerCase().replace(/\s+/g, '');

export function filterCatalog(items: CatalogItem[], query: CatalogQuery): CatalogItem[] {
  const text = normalize(query.text);
  const shown = items.filter(item => {
    if (text && !normalize(`${item.title}${item.id}${item.field}${item.summary}${item.what ?? ''}\n${lawNameText(item.title, item.what)}`).includes(text)) return false;
    if (query.field && item.field !== query.field) return false;
    if (query.kind && item.kind !== query.kind) return false;
    if (query.side === 'loss' && item.side !== 'loss') return false;
    if (query.side === 'benefit' && item.side !== 'benefit') return false;
    if (query.side === 'amount' && !item.amount) return false;
    if (query.side === 'confirmed' && item.step !== 'published') return false;
    if (query.side === 'none' && item.amount) return false;
    return true;
  });
  const progress = (item: CatalogItem) => STEP_ORDER.indexOf(item.step);
  // 年の無い行は、新しい順でも古い順でも最後に置く。
  const byYear = (a: CatalogItem, b: CatalogItem) => (a.year === null) !== (b.year === null) ? (a.year === null ? 1 : -1) : (b.year ?? 0) - (a.year ?? 0);
  const byYearAsc = (a: CatalogItem, b: CatalogItem) => (a.year === null) !== (b.year === null) ? (a.year === null ? 1 : -1) : (a.year ?? 0) - (b.year ?? 0);
  // 損失順・便益順は、その向きの行を先に置き、あとは既定の並び（確かな額 → 額の大きい順）。向きの無い行は最後。
  const bySide = (side: 'loss' | 'benefit') => (a: CatalogItem, b: CatalogItem) => Number(b.side === side) - Number(a.side === side) || sorters.amount(a, b);
  const sorters: Record<SortKey, (a: CatalogItem, b: CatalogItem) => number> = {
    // 確かな額 → 参考の額 → 額なしの順。同じ組の中は額の大きい順、額のない行は計算が進んだ順、同じなら新しい順。
    amount: (a, b) => Number(b.step === 'published') - Number(a.step === 'published') || (b.amount?.median ?? -1) - (a.amount?.median ?? -1) || progress(b) - progress(a) || byYear(a, b),
    loss: (a, b) => bySide('loss')(a, b),
    benefit: (a, b) => bySide('benefit')(a, b),
    newest: (a, b) => byYear(a, b) || progress(b) - progress(a),
    oldest: (a, b) => byYearAsc(a, b) || progress(b) - progress(a),
    progress: (a, b) => progress(b) - progress(a) || (b.amount?.median ?? -1) - (a.amount?.median ?? -1) || byYear(a, b),
  };
  return [...shown].sort(sorters[query.sort]);
}

/** 観測の key ごとの法律（id 昇順）。同じ観測の仲間を引くのに使う。 */
export function groupByObservation(items: CatalogItem[]): Map<string, CatalogItem[]> {
  const groups = new Map<string, CatalogItem[]>();
  for (const item of items) {
    if (!item.observation) continue;
    const list = groups.get(item.observation.key);
    if (list) list.push(item); else groups.set(item.observation.key, [item]);
  }
  for (const list of groups.values()) list.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return groups;
}

/**
 * 同じ観測は代表の1行にまとめる。絞り込みで代表が外れていたら、残った中で並びの先頭の1本を代表にする。
 * revealed に入れた id は、代表でなくても行として残す（同じ観測の題名一覧から選んだ法律、#id で開く法律）。
 */
export function collapseObservations(list: CatalogItem[], revealed: ReadonlySet<string> = new Set()): CatalogItem[] {
  const chosen = new Map<string, CatalogItem>();
  for (const item of list) {
    if (!item.observation) continue;
    const current = chosen.get(item.observation.key);
    if (!current || (item.observation.representative && !current.observation!.representative)) chosen.set(item.observation.key, item);
  }
  return list.filter(item => !item.observation || chosen.get(item.observation.key) === item || revealed.has(item.id));
}

/** URL の検索部分 ⇔ 絞り込み。共有した URL で同じ一覧が開く。 */
export function readQuery(search: string): CatalogQuery {
  const params = new URLSearchParams(search);
  const side = params.get('side') as SideFilter | null;
  const sort = params.get('sort') as SortKey | null;
  return {
    text: params.get('q') ?? '',
    side: side && ['all', 'confirmed', 'loss', 'benefit', 'amount', 'none'].includes(side) ? side : 'all',
    field: params.get('field') ?? '',
    kind: params.get('kind') ?? '',
    sort: sort && ['amount', 'loss', 'benefit', 'newest', 'oldest', 'progress'].includes(sort) ? sort : 'amount',
  };
}

export function writeQuery(query: CatalogQuery): string {
  const params = new URLSearchParams();
  if (query.text) params.set('q', query.text);
  if (query.side !== 'all') params.set('side', query.side);
  if (query.field) params.set('field', query.field);
  if (query.kind) params.set('kind', query.kind);
  if (query.sort !== 'amount') params.set('sort', query.sort);
  const text = params.toString();
  return text ? `?${text}` : '';
}

export function sideLabel(side: CatalogItem['side']): string {
  return side === 'loss' ? '国賊側（損失）' : side === 'benefit' ? '国士側（便益）' : '額なし';
}
