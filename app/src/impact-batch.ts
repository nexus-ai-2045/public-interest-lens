/**
 * 評価対象の法律を一括で impact-rule-v1 にかける処理（impact-v1）。
 * 判定は app/src/impact-rule.ts の judgeImpact / judgeAcrossCountries だけが行い、ここでは系列を選んで窓を作るだけです。
 * ファイルの読み書きは app/scripts/run-impact-v1.mjs が行い、このモジュールは純粋な関数だけにします（ブラウザ用ビルドにも入れられる）。
 * 方法の説明は data/derived/impact-v1/spec.md。
 */
import { judgeAcrossCountries, judgeImpact, type CountryPoint, type ImpactPoint, type ImpactSeries } from './impact-rule';

export type Row = Record<string, string>;
/** 取得済み CSV の中身。キーは data/acquired/ からの相対パス。 */
export type Tables = Map<string, Row[]>;

/** 1つの CSV から、列の値で絞った1系列（年→値）を指す。 */
export type Ref = { file: string; where: Row; valueColumn?: string; yearColumn?: string };
/** 対象と比較の組。対象と比較は同じ基準・同じ分類のファイルから取る（系列接続禁止）。 */
export type PairOption = { name: string; treated: Ref; control: Ref };
export type PairSpec = { definition: string; better: 'lower' | 'higher'; options: PairOption[] };
export type ShareOption = { name: string; sector: Ref; total: Ref };
/** 国際比較の系列。ratio があれば code ÷ ratio を各国で計算する。rebase は指数・金額を開始前最後の年=100にそろえるか。 */
export type IntlSpec = { code: string; ratio?: string; label: string; rebase: boolean; better: 'lower' | 'higher' };
export type Mapping = {
  indicator: string;
  field: string;
  match: '直接' | '代理' | '系列なし';
  target: PairSpec | null;
  economy: PairSpec | null;
  share: ShareOption[];
  intl: IntlSpec | null;
  reason: string;
};

const sna = (base: string) => `domestic-stats/sna_gdp_by_industry_${base}base.csv`;
const snaReal = (base: string, activity: string): Ref => ({ file: sna(base), where: { 価格: '実質(連鎖方式)', 経済活動: activity } });
const snaNominal = (base: string, activity: string): Ref => ({ file: sna(base), where: { 価格: '名目', 経済活動: activity } });
const lfs = (cls: string, industry: string): Ref => ({ file: `domestic-stats/lfs_employed_by_industry_${cls}.csv`, where: { 産業: industry } });
const cpi = (base: string, where: Row): Ref => ({ file: `domestic-stats/cpi_items_annual_${base}base.csv`, where });

/** SNA の基準ごとの経済活動名。2000基準は運輸と通信が1つで、分けられないものは入れない。 */
const SNA_BASES = ['2020', '2015', '2011', '2005', '2000'] as const;
type SnaKey = 'ict' | 'transport' | 'lodging' | 'electricity' | 'electronics';
const SNA_NAMES: Record<SnaKey, Partial<Record<(typeof SNA_BASES)[number], string>>> = {
  ict: { 2020: '9.情報通信業', 2015: '9.情報通信業', 2011: '9.情報通信業', 2005: '(10)情報通信業' },
  transport: { 2020: '7.運輸・郵便業', 2015: '7.運輸・郵便業', 2011: '7.運輸・郵便業', 2005: '(9)運輸業' },
  lodging: { 2020: '8.宿泊・飲食サービス業', 2015: '8.宿泊・飲食サービス業', 2011: '8.宿泊・飲食サービス業' },
  electricity: { 2020: '4.電気・ガス・水道・廃棄物処理業', 2015: '4.電気・ガス・水道・廃棄物処理業', 2011: '4.電気・ガス・水道・廃棄物処理業', 2005: '(5)電気・ガス・水道業', 2000: '(5)電気・ガス・水道業' },
  electronics: { 2020: '(10)電子部品・デバイス', 2015: '(10)電子部品・デバイス', 2011: '(10)電子部品・デバイス' },
};
const snaVsGdp = (key: SnaKey): PairOption[] => SNA_BASES.flatMap(base => {
  const activity = SNA_NAMES[key][base];
  return activity ? [{ name: `国民経済計算${base}基準 実質（連鎖）「${activity}」対「合計」`, treated: snaReal(base, activity), control: snaReal(base, '合計') }] : [];
});
const snaShare = (key: SnaKey): ShareOption[] => SNA_BASES.flatMap(base => {
  const activity = SNA_NAMES[key][base];
  return activity ? [{ name: `国民経済計算${base}基準 名目「${activity}」÷「合計」`, sector: snaNominal(base, activity), total: snaNominal(base, '合計') }] : [];
});
/** 労働力調査の産業名。第10回改定は運輸と通信が1つで、分けられないものは入れない。 */
const LFS_NAMES: Record<'ict' | 'transport' | 'manufacturing', Partial<Record<'jsic12-14' | 'jsic11', string>>> = {
  ict: { 'jsic12-14': '情報通信業', jsic11: '情報通信業' },
  transport: { 'jsic12-14': '運輸業,郵便業', jsic11: '運輸業' },
  manufacturing: { 'jsic12-14': '製造業', jsic11: '製造業' },
};
const lfsVsTotal = (key: keyof typeof LFS_NAMES): PairOption[] => (['jsic12-14', 'jsic11'] as const).flatMap(cls => {
  const industry = LFS_NAMES[key][cls];
  return industry ? [{ name: `労働力調査（${cls}）就業者「${industry}」対「総数」`, treated: lfs(cls, industry), control: lfs(cls, '総数') }] : [];
});
const CPI_BASES = ['2025', '2020', '2015', '2010', '2005'];

const none = (indicator: string, field: string, reason: string): Mapping => ({ indicator, field, match: '系列なし', target: null, economy: null, share: [], intl: null, reason });

/**
 * triage の指標 → 取得済みの系列。結果を見る前に固定する（docs/indicator-control-table.md の考え方）。
 * 比較群は「その分野の値」対「経済全体の同じ種類の値」（付加価値なら GDP、就業者なら就業者総数、物価なら総合指数）。
 */
export const INDICATOR_MAP: Mapping[] = [
  none('不良債権比率', '金融', '取得済みの国内・国際統計に不良債権比率の系列がない。金融庁の主要行・地域銀行の系列（app/src/case-evaluation.ts）は金融再生プログラム専用の比較群で、全銀行に及ぶ法律では比較群も同時に影響を受けるため使わない'),
  none('貸出残高', '金融', '取得済みの統計に貸出残高（日本銀行の貸出・預金統計など）がない。金融・保険業の付加価値は貸出の量を表さないため代わりにしない'),
  none('企業倒産件数', '金融', '取得済みの統計に倒産件数（東京商工リサーチ等）がない'),
  {
    indicator: '旅客輸送の付加価値', field: '交通・移動', match: '代理',
    target: { definition: '運輸業（旅客と貨物・郵便を含む）の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('transport') },
    economy: { definition: '運輸業の就業者数と就業者総数（開始前最後の年=100）', better: 'higher', options: lfsVsTotal('transport') },
    share: snaShare('transport'), intl: null,
    reason: '国民経済計算に旅客輸送だけの付加価値はなく、運輸業（2011基準以降は運輸・郵便業）で代える。貨物・郵便を含むため代理。2000基準は運輸・通信業が1つなので使わない。国際統計に産業別付加価値がないため国際比較なし',
  },
  none('利用件数', '交通・移動', '取得済みの統計に旅客数・利用件数（国土交通省の輸送統計など）がない。消費者物価の鉄道運賃は利用量ではないため代わりにしない'),
  {
    indicator: '就業者数', field: '交通・移動', match: '代理',
    target: { definition: '運輸業の就業者数と就業者総数（開始前最後の年=100）', better: 'higher', options: lfsVsTotal('transport') },
    economy: { definition: '運輸業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('transport') },
    share: snaShare('transport'), intl: null,
    reason: '労働力調査の運輸業（第12〜14回改定は運輸業,郵便業）。貨物・郵便を含むため代理。第10回改定（2002年まで）は運輸・通信業が1つなので使わない。就業者が増えるほど良いとみなす（向きは機械的な仮定）',
  },
  {
    indicator: '宿泊者数', field: '宿泊・観光', match: '直接',
    target: { definition: '延べ宿泊者数の指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: [{ name: '宿泊旅行統計「延べ宿泊者数」対 国民経済計算2020基準 実質「合計」', treated: { file: 'domestic-stats/kanko_lodging_annual.csv', where: { 指標: '延べ宿泊者数' } }, control: snaReal('2020', '合計') }] },
    economy: { definition: '宿泊・飲食サービス業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('lodging') },
    share: snaShare('lodging'), intl: null,
    reason: '観光庁 宿泊旅行統計の延べ宿泊者数（2011〜2025年）。比較は経済全体の活動量として実質GDP。国際統計に宿泊数（Eurostat）が未取得のため国際比較なし',
  },
  none('宿泊業の付加価値', '宿泊・観光', '施行日のある評価対象に該当がなく、対応を固定していない（国民経済計算は宿泊・飲食サービス業で、宿泊業だけの系列はない）'),
  none('客室数', '宿泊・観光', '取得済みの統計に客室数（旅館業法の施設数・客室数など）がない'),
  {
    indicator: '通信業の付加価値', field: '通信・ネット', match: '直接',
    target: { definition: '情報通信業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('ict') },
    economy: { definition: '情報通信業の就業者数と就業者総数（開始前最後の年=100）', better: 'higher', options: lfsVsTotal('ict') },
    share: snaShare('ict'), intl: null,
    reason: '国民経済計算の情報通信業（2005基準以降）。放送・情報サービスを含む。2000基準は運輸・通信業が1つなので使わない。国際統計に産業別付加価値がないため国際比較なし',
  },
  {
    indicator: 'ブロードバンド普及率', field: '通信・ネット', match: '代理',
    target: null, economy: null, share: snaShare('ict'),
    intl: { code: 'WB:IT.NET.USER.ZS', label: '世界銀行 インターネット利用者（人口比%）', rebase: false, better: 'higher' },
    reason: '国内のブロードバンド契約数は未取得。世界銀行のインターネット利用者比率で国際比較だけ行う（契約率ではないため代理）',
  },
  none('ネット企業の時価総額', '通信・ネット', '取得済みの統計に株式時価総額の業種別系列がない'),
  none('世界輸出シェア', '半導体・電子', '取得済みの統計に半導体の輸出額（国連 Comtrade 等）がない'),
  {
    indicator: '生産額', field: '半導体・電子', match: '代理',
    target: { definition: '電子部品・デバイスの実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('electronics') },
    economy: { definition: '製造業の就業者数と就業者総数（開始前最後の年=100）', better: 'higher', options: lfsVsTotal('manufacturing') },
    share: snaShare('electronics'), intl: null,
    reason: '生産額（出荷額）は未取得で、国民経済計算の電子部品・デバイスの付加価値で代える（2011基準以降のみ）',
  },
  {
    indicator: '電力価格', field: 'エネルギー', match: '直接',
    target: { definition: '消費者物価指数「電気代」（品目符号3500）と「総合」（開始前最後の年=100）', better: 'lower', options: CPI_BASES.map(base => ({ name: `消費者物価指数${base}基準「電気代」対「総合」`, treated: cpi(base, { 品目: '電気代', 品目符号: '3500' }), control: cpi(base, { 品目: '総合' }) })) },
    economy: { definition: '電気・ガス・水道業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('electricity') },
    share: snaShare('electricity'),
    intl: { code: 'CPI:CP045', label: 'OECD 消費者物価「電気・ガス・その他燃料」（COICOP 04.5）', rebase: true, better: 'lower' },
    reason: '家計が払う電気代の物価を総合物価と比べる（相対価格）。国際比較は OECD の 04.5（電気・ガス・その他燃料）で、電気だけの系列が未取得のため代理',
  },
  none('発電構成', 'エネルギー', '取得済みの統計に電源別発電量（資源エネルギー庁 総合エネルギー統計、IEA など）がない'),
  none('エネルギー効率', 'エネルギー', '取得済みの統計にエネルギー消費量がなく、GDP当たりのエネルギー消費を計算できない'),
  {
    indicator: '労働生産性', field: '労働市場', match: '代理',
    target: null, economy: null, share: [],
    intl: { code: 'WB:NY.GDP.MKTP.KD', ratio: 'WB:SL.TLF.TOTL.IN', label: '世界銀行 実質GDP（2015年米ドル）÷労働力人口', rebase: true, better: 'higher' },
    reason: '経済全体の法律なので国内に比較群がない。国際比較で、労働力人口1人当たり実質GDP（就業者・労働時間ではないため代理）を比べる',
  },
  none('賃金', '労働市場', '取得済みの統計に賃金（毎月勤労統計・賃金構造基本統計）がない'),
  none('雇用の流動性', '労働市場', '取得済みの統計に入職率・離職率・転職者数（雇用動向調査など）がない'),
  none('電子申請率', '行政のデジタル化', '取得済みの統計に行政手続きのオンライン利用率がない'),
  none('行政手続きの時間', '行政のデジタル化', '取得済みの統計に行政手続きの所要時間の系列がない'),
];

// ---- CSV ----

/** RFC 4180 の CSV（引用符・引用符内のカンマと改行）を読む。先頭行を見出しとする。 */
export function parseCsv(text: string): Row[] {
  const records: string[][] = [];
  let field = '', record: string[] = [], quoted = false;
  const src = text.replace(/^﻿/, '');
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"' && src[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { record.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && src[i + 1] === '\n') i++;
      record.push(field); records.push(record); record = []; field = '';
    } else field += c;
  }
  if (field !== '' || record.length) { record.push(field); records.push(record); }
  const [header, ...body] = records.filter(r => !(r.length === 1 && r[0] === ''));
  return body.map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

const csvCell = (v: string | number | null) => { const s = v === null ? '' : String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
export const toCsv = (header: string[], rows: (string | number | null)[][]) => [header, ...rows].map(r => r.map(csvCell).join(',')).join('\n') + '\n';

// ---- 系列と窓 ----

/** 列の値で絞った年→値。空欄の年は入れない（0で埋めない）。同じ年に違う値があれば止める。 */
export function extractSeries(tables: Tables, ref: Ref): Map<number, number> {
  const rows = tables.get(ref.file);
  if (!rows) throw new Error(`未読込のファイル: ${ref.file}`);
  const out = new Map<number, number>();
  for (const row of rows) {
    if (!Object.entries(ref.where).every(([k, v]) => row[k] === v)) continue;
    const raw = (row[ref.valueColumn ?? '値'] ?? '').trim();
    if (raw === '') continue;
    const year = Number((row[ref.yearColumn ?? '年'] ?? '').slice(0, 4)), value = Number(raw);
    if (!Number.isFinite(year) || !Number.isFinite(value)) throw new Error(`数値でない値: ${ref.file} ${JSON.stringify(row)}`);
    if (out.has(year) && out.get(year) !== value) throw new Error(`同じ年に異なる値: ${ref.file} ${JSON.stringify(ref.where)} ${year}`);
    out.set(year, value);
  }
  return out;
}

export const startYear = (start: string) => Number(start.slice(0, 4));
/** 判定ルールが使う年：開始前5年（開始年の前年まで）と、開始年（1年目、除外される）から4年後（5年目）まで。 */
export const neededYears = (start: string) => { const y = startYear(start); return Array.from({ length: 10 }, (_, i) => y - 5 + i); };
export const asOfYear = (year: number) => `${year}-12-31`;

/** 対象と比較の両方に値がある年。 */
const commonYears = (a: Map<number, number>, b: Map<number, number>) => [...a.keys()].filter(y => b.has(y)).sort((x, y) => x - y);

/**
 * 候補（基準年・分類の違うファイル）から1つ選ぶ。判定に必要な10年のうち両方に値がある年が最も多いもの、同数なら先に書いた（新しい）もの。
 * 基準の違う系列はつながない。
 */
export function chooseOption<T>(tables: Tables, start: string, options: T[], pick: (o: T) => [Ref, Ref]): { option: T; a: Map<number, number>; b: Map<number, number>; coverage: number } | null {
  let best: { option: T; a: Map<number, number>; b: Map<number, number>; coverage: number } | null = null;
  const need = neededYears(start);
  for (const option of options) {
    const [ra, rb] = pick(option);
    const a = extractSeries(tables, ra), b = extractSeries(tables, rb);
    const coverage = need.filter(y => a.has(y) && b.has(y)).length;
    if (best === null || coverage > best.coverage) best = { option, a, b, coverage };
  }
  return best;
}

/** 開始前の最後の共通年を100にそろえた対象・比較の点列。開始前に共通年が無ければそろえずに返す（判定ルールが年数不足で保留にする）。 */
export function buildPairPoints(a: Map<number, number>, b: Map<number, number>, start: string): { points: ImpactPoint[]; baseYear: number | null } {
  const years = commonYears(a, b);
  const pre = years.filter(y => y < startYear(start));
  const baseYear = pre.length ? pre[pre.length - 1] : null;
  const scale = (m: Map<number, number>, y: number) => baseYear === null ? m.get(y)! : (m.get(y)! / m.get(baseYear)!) * 100;
  return { points: years.map(y => ({ asOf: asOfYear(y), treated: scale(a, y), control: scale(b, y) })), baseYear };
}

export function buildImpactSeries(tables: Tables, mapping: Mapping, start: string): { series: ImpactSeries; label: string; baseYear: number | null } | null {
  if (!mapping.target) return null;
  const chosen = chooseOption(tables, start, mapping.target.options, o => [o.treated, o.control]);
  if (!chosen || chosen.coverage === 0) return null;
  const { points, baseYear } = buildPairPoints(chosen.a, chosen.b, start);
  let economy: ImpactSeries['economy'] = null, economyLabel = '経済全体の指標なし';
  if (mapping.economy) {
    const e = chooseOption(tables, start, mapping.economy.options, o => [o.treated, o.control]);
    if (e && e.coverage > 0) {
      economy = { definition: mapping.economy.definition, better: mapping.economy.better, points: buildPairPoints(e.a, e.b, start).points };
      economyLabel = `経済全体：${e.option.name}`;
    }
  }
  const sectorGdpShare = gdpShare(tables, mapping.share, start);
  const label = `${chosen.option.name}（${baseYear ?? '—'}年=100）／${economyLabel}／GDP比${sectorGdpShare === null ? 'なし' : sectorGdpShare.toFixed(4)}`;
  return { series: { definition: mapping.target.definition, start, better: mapping.target.better, target: points, economy, sectorGdpShare }, label, baseYear };
}

/** 開始前の最後の年の、分野の名目付加価値÷名目GDP。開始前に値が無ければ null。 */
export function gdpShare(tables: Tables, options: ShareOption[], start: string): number | null {
  const chosen = chooseOption(tables, start, options, o => [o.sector, o.total]);
  if (!chosen) return null;
  const pre = commonYears(chosen.a, chosen.b).filter(y => y < startYear(start));
  if (!pre.length) return null;
  const y = pre[pre.length - 1];
  return chosen.a.get(y)! / chosen.b.get(y)!;
}

/** 国際統計（国,指標,年,値）から国ごとの年→値。ratio があれば割り算する。 */
export function intlByCountry(tables: Tables, spec: IntlSpec): Map<string, Map<number, number>> {
  const read = (code: string) => {
    const out = new Map<string, Map<number, number>>();
    for (const row of tables.get('intl-stats/intl-stats.csv') ?? []) {
      if (row['指標'] !== code || row['値'].trim() === '') continue;
      const m = out.get(row['国']) ?? new Map<number, number>();
      m.set(Number(row['年'].slice(0, 4)), Number(row['値']));
      out.set(row['国'], m);
    }
    return out;
  };
  const num = read(spec.code);
  if (!spec.ratio) return num;
  const den = read(spec.ratio), out = new Map<string, Map<number, number>>();
  for (const [country, n] of num) {
    const d = den.get(country); if (!d) continue;
    const m = new Map<number, number>();
    for (const [y, v] of n) if (d.has(y) && d.get(y)! !== 0) m.set(y, v / d.get(y)!);
    out.set(country, m);
  }
  return out;
}

/**
 * 日本と比較国の点列。指数・金額は日本の開始前最後の年を全員100にそろえ、その年の値が無い国は外す。比率（%）はそろえない。
 */
export function buildCrossCountry(byCountry: Map<string, Map<number, number>>, spec: IntlSpec, start: string, treatedCountry = 'JPN') {
  const jp = byCountry.get(treatedCountry);
  if (!jp) return null;
  const pre = [...jp.keys()].filter(y => y < startYear(start)).sort((a, b) => a - b);
  const baseYear = spec.rebase ? (pre.length ? pre[pre.length - 1] : null) : null;
  if (spec.rebase && baseYear === null) return null;
  const toPoints = (m: Map<number, number>): CountryPoint[] =>
    [...m.keys()].sort((a, b) => a - b).map(y => ({ asOf: asOfYear(y), value: baseYear === null ? m.get(y)! : (m.get(y)! / m.get(baseYear)!) * 100 }));
  const controls = [...byCountry.entries()].filter(([c, m]) => c !== treatedCountry && (baseYear === null || m.has(baseYear))).sort(([a], [b]) => a.localeCompare(b))
    .map(([country, m]) => ({ country, points: toPoints(m) }));
  return { treated: toPoints(jp), controls, baseYear };
}

// ---- 1法律の判定 ----

/** 新型コロナで経済活動が大きく揺れた年。判定は変えず、理由欄に機械的に注意を付けるだけに使う。 */
export const PANDEMIC_YEARS = [2020, 2021, 2022];
/** 判定ルールが使う開始後2〜5年目のうち、PANDEMIC_YEARS に当たる年。 */
export const pandemicOverlap = (start: string) => { const y = startYear(start); return PANDEMIC_YEARS.filter(p => p >= y + 1 && p <= y + 4); };

export type Law = { id: string; title: string; field: string; indicator: string; start: string };
export type LawResult = Law & {
  series: string; verdict: string; direction: string; effect: number | null; spread: number | null; cross: string; reason: string;
};

const stageLabel = (stage: 1 | 2 | 3 | null) => stage === null ? '保留' : `段階${stage}`;
const dirLabel = (d: 'benefit' | 'harm' | null) => d === null ? '' : d === 'benefit' ? '貢献' : '悪影響';

export function evaluateLaw(tables: Tables, law: Law, mappings: Mapping[] = INDICATOR_MAP): LawResult {
  const mapping = mappings.find(m => m.indicator === law.indicator);
  const blank = { series: '', verdict: '系列なし', direction: '', effect: null, spread: null, cross: '系列なし' };
  if (!mapping) return { ...law, ...blank, reason: `系列なし：指標「${law.indicator}」が対応表にない` };
  if (mapping.match === '系列なし') return { ...law, ...blank, reason: `系列なし：${mapping.reason}` };

  const reasons: string[] = [];
  let result: Omit<LawResult, keyof Law | 'cross' | 'reason'> = { ...blank, verdict: '国内系列なし' };
  if (mapping.target) {
    const built = buildImpactSeries(tables, mapping, law.start);
    if (!built) { result = { ...blank, verdict: '保留' }; reasons.push('国内：期間が足りない（判定に必要な年に系列の値がない）'); }
    else {
      const j = judgeImpact(built.series);
      result = { series: built.label, verdict: stageLabel(j.stage), direction: dirLabel(j.direction), effect: j.effect, spread: j.spread };
      reasons.push(`国内：${j.preYears < 3 || j.effect === null ? '期間が足りない。' : ''}${j.reason}`);
    }
  } else reasons.push('国内：国内に比較群がない');

  let cross = '系列なし';
  if (mapping.intl) {
    const built = buildCrossCountry(intlByCountry(tables, mapping.intl), mapping.intl, law.start);
    if (!built) { cross = '保留'; reasons.push('国際：日本の開始前の値がない'); }
    else {
      const j = judgeAcrossCountries({ definition: mapping.intl.label, start: law.start, better: mapping.intl.better, sectorGdpShare: null, treated: built.treated, controls: built.controls });
      const passed = j.countries.filter(c => c.passes).length;
      cross = `${stageLabel(j.stage)}${j.direction ? '・' + dirLabel(j.direction) : ''}（比較国${built.controls.length}か国、条件を満たした国${passed}）`;
      reasons.push(`国際（${mapping.intl.label}${built.baseYear ? `、${built.baseYear}年=100` : ''}）：${j.reason}`);
      if (!result.series) result = { ...result, series: `国際：${mapping.intl.label}` };
    }
  }
  if (mapping.match === '代理') reasons.push(`代理系列：${mapping.reason}`);
  const overlap = pandemicOverlap(law.start);
  if (overlap.length) reasons.push(`注意：判定に使う開始後2〜5年目（${startYear(law.start) + 1}〜${startYear(law.start) + 4}年）に新型コロナの${overlap.join('・')}年を含む。判定ルールは同時期の別の出来事を除かない`);
  return { ...law, ...result, cross, reason: reasons.join('／') };
}

export const IMPACT_HEADER = ['id', '題名', '分野', '指標', '施行日', '系列', '判定', '向き', '効果', 'ばらつき', '国際比較', '理由'];
export const impactRow = (r: LawResult) => [r.id, r.title, r.field, r.indicator, r.start, r.series, r.verdict, r.direction, r.effect, r.spread, r.cross, r.reason];

export const MAP_HEADER = ['指標', '分野', '対応', '国内_対象と比較（候補を優先順に）', '国内_向き', '経済全体の指標（候補を優先順に）', 'GDP比（候補を優先順に）', '国際比較_指標コード', '国際比較_説明', '理由'];
export const mapRow = (m: Mapping) => [
  m.indicator, m.field, m.match,
  m.target ? m.target.options.map(o => `${o.name}［${o.treated.file}］`).join('; ') : '系列なし',
  m.target ? (m.target.better === 'higher' ? '高いほど良い' : '低いほど良い') : '',
  m.economy ? m.economy.options.map(o => `${o.name}［${o.treated.file}］`).join('; ') : '',
  m.share.map(o => o.name).join('; '),
  m.intl ? (m.intl.ratio ? `${m.intl.code} ÷ ${m.intl.ratio}` : m.intl.code) : '系列なし',
  m.intl ? `${m.intl.label}（${m.intl.better === 'higher' ? '高いほど良い' : '低いほど良い'}${m.intl.rebase ? '、日本の開始前最後の年=100' : '、比率のまま'}）` : '',
  m.reason,
];
