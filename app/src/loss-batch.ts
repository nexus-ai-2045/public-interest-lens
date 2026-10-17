/**
 * impact-v1 で段階2以上になった法律に、loss-rule-v1（app/src/loss-rule.ts の estimateLoss）を一括でかける処理（loss-v1）。
 * 損失額の計算は loss-rule.ts だけが行い、ここでは系列を選んで入力を作り、結果を表にするだけです。
 * この段階は法律だけを扱います。人物・採決・役職のデータは読まず、allocateLoss も呼びません。
 * ファイルの読み書きは app/scripts/run-loss-v1.mjs が行い、このモジュールは純粋な関数だけにします。
 * 方法の説明は data/derived/loss-v1/spec.md。
 */
import { asOfYear, extractSeries, intlByCountry, startYear, type IntlSpec, type Ref, type Row, type Tables } from './impact-batch';
import type { CountryPoint, CountrySeries } from './impact-rule';
import { NEW_FIELDS, NEW_FIELD_WORDS, newIndicator, type NewField } from './indicator-pick';
import { estimateLoss, MAX_LOSS_YEARS, type LossInput, type LossResult } from './loss-rule';

const SNA_FILE = (base: string) => `domestic-stats/sna_gdp_by_industry_${base}base.csv`;
const SNA_BASES = ['2020', '2015', '2011', '2005', '2000'] as const;
type Sna = { base: string; activity: string };
const snaReal = ({ base, activity }: Sna): Ref => ({ file: SNA_FILE(base), where: { 価格: '実質(連鎖方式)', 経済活動: activity } });
const snaNominal = ({ base, activity }: Sna): Ref => ({ file: SNA_FILE(base), where: { 価格: '名目', 経済活動: activity } });
const sna = (names: Partial<Record<(typeof SNA_BASES)[number], string>>): Sna[] =>
  SNA_BASES.flatMap(base => names[base] ? [{ base, activity: names[base]! }] : []);

/**
 * 指標ごとの損失額の入力。loss-rule-v1 は「分野の実質付加価値」を日本と比較国で比べる。
 * - sector：日本の分野の実質・名目付加価値（国民経済計算。基準ごとに候補、つながない）。
 * - oecd：日本と比較国の同じ定義の分野の付加価値（OECD 表6）。あればこれで計算し、sector は名目の差を示す比較用にだけ使う。
 * - intl：比較国の同じ定義の系列。どちらも無ければ比較国0か国として判定ルールに渡し、保留になる。
 * - reference：参考扱い（合計に入れない）。
 * 貸出残高だけは付加価値ではなく、世界銀行の与信のGDP比を日本と比較国で比べ、名目GDPで円に直す（下の LOAN_NOTE）。
 */
export type LossSource = {
  indicator: string;
  definition: string;
  /** 日本の国民経済計算（基準ごとの候補）。oecd があるときは比較用（差を計算式の要素に書くだけ）。 */
  sector: Sna[] | null;
  /** 日本と比較国の同じ定義の分野の付加価値（OECD 表6）。実質は LR（全国2020年基準の連鎖実質）、名目は V。L は国で基準年が違うので使わない。 */
  oecd?: OecdSpec;
  intl: IntlSpec | null;
  /** 名目GDP（与信のGDP比を円に直すときの分母）。sector が null のときに使う。 */
  gdp?: Sna[];
  reference: boolean;
  note: string;
  /** 系列の定義が変わる年（その年から新しい定義）。窓がこの年をまたぐ法律は、つながない原則により保留にする。 */
  breaks?: { year: number; evidence: string }[];
};

/** OECD 表6の産業（ISIC Rev.4）。excludeIfCrossing の国は、損失額の窓がその年をまたぐ法律で比較国から外す。 */
export type OecdSpec = {
  industry: string;
  /** 複数の節を足して1つの産業にするとき（M と N など）の節。industry は代表の節（表示用）。足す節がすべてそろった年だけ使う。 */
  parts?: string[];
  label: string;
  excludeIfCrossing?: { country: string; year: number; evidence: string }[];
  /** 比較国に使ったときに計算式の要素へ書く注記（国ごと）。 */
  countryNotes?: Record<string, string>;
  /** 系列の無い国の注記（補わない）。 */
  missing?: Record<string, string>;
};

export const OECD_FILE = 'oecd-industry/industry_va.csv';
const oecdRef = (industry: string, price: 'LR' | 'V', country: string): Ref => ({ file: OECD_FILE, where: { 国: country, 産業: industry, 価格: price } });
/** OECD 表6の国ごとの系列（価格 LR または V）。 */
export function oecdByCountry(tables: Tables, industry: string, price: 'LR' | 'V'): Map<string, Map<number, number>> {
  const rows = tables.get(OECD_FILE);
  if (!rows) throw new Error(`未読込のファイル: ${OECD_FILE}`);
  const countries = [...new Set(rows.filter(r => r['産業'] === industry && r['価格'] === price).map(r => r['国']))].sort();
  return new Map(countries.map(c => [c, extractSeries(tables, oecdRef(industry, price, c))]));
}

/** OECD 表6の節（parts があれば足し合わせ）。連鎖実質（LR）は加法性がないので、足した系列は近似。 */
export function oecdAggregate(tables: Tables, spec: OecdSpec, price: 'LR' | 'V'): Map<string, Map<number, number>> {
  const parts = spec.parts ?? [spec.industry];
  if (parts.length === 1) return oecdByCountry(tables, parts[0], price);
  const byPart = parts.map(p => oecdByCountry(tables, p, price));
  const out = new Map<string, Map<number, number>>();
  for (const country of new Set(byPart.flatMap(m => [...m.keys()]))) {
    const series = byPart.map(m => m.get(country));
    if (series.some(x => !x)) continue;
    const years = [...series[0]!.keys()].filter(y => series.every(x => x!.has(y)));
    out.set(country, new Map(years.map(y => [y, series.reduce((sum, x) => sum + x!.get(y)!, 0)])));
  }
  return out;
}
/** industry_va.csv に無い節（まだ取得していない）。 */
export function missingOecdParts(tables: Tables, spec: OecdSpec): string[] {
  const rows = tables.get(OECD_FILE) ?? [];
  return (spec.parts ?? [spec.industry]).filter(p => !rows.some(r => r['産業'] === p));
}

const ITA_BREAK = { country: 'ITA', year: 2010, evidence: 'ITA は2010年の観測に系列の断絶フラグ（原本の OBS_STATUS=B）があるため、窓が2010年をまたぐ法律では比較国から外す' };
const AUS_NOTE = 'AUS は年度（7〜6月）の可能性が高い（OECD は年で記録）。そのまま使う';
const OECD_NOTE = '日本・比較国とも OECD 国民経済計算 表6（総付加価値 B1G、ISIC Rev.4）。実質は連鎖実質・2020年基準（LR）、名目は V。国により基準年の違う連鎖実質（L）は使わない。単位は自国通貨なので伸び（比）だけを比べる';

const LOAN_NOTE = '参考：影響段階は日本銀行の国内銀行の総貸出で判定したが、損失額は比較国と同じ定義が要るので世界銀行の与信のGDP比で測る。「貸出が多いほど良い」という向きは機械的な仮定で、1999〜2001年施行の6本はほぼ同じ窓の同じ系列（実質的に1つの観測）。合計に入れない。損失額は付加価値の損失ではなく、与信残高（GDP比）の比較国との差を毎年の名目GDPではなく開始前最後の年の名目GDPで円に直して足した「残高の差の累積」';

export const LOSS_SOURCES: LossSource[] = [
  {
    indicator: '通信業の付加価値', definition: '情報通信業（ISIC Rev.4 J）の実質付加価値',
    sector: sna({ 2020: '9.情報通信業', 2015: '9.情報通信業', 2011: '9.情報通信業', 2005: '(10)情報通信業' }),
    oecd: { industry: 'J', label: '情報通信（J）', excludeIfCrossing: [ITA_BREAK], countryNotes: { AUS: AUS_NOTE } },
    intl: null, reference: false,
    note: OECD_NOTE,
  },
  {
    indicator: '宿泊者数', definition: '宿泊・飲食サービス業（ISIC Rev.4 I）の実質付加価値',
    sector: sna({ 2020: '8.宿泊・飲食サービス業', 2015: '8.宿泊・飲食サービス業', 2011: '8.宿泊・飲食サービス業' }),
    oecd: { industry: 'I', label: '宿泊・飲食サービス（I）', excludeIfCrossing: [ITA_BREAK], countryNotes: { AUS: AUS_NOTE }, missing: { KOR: 'KOR は宿泊・飲食（I）の系列が無いため比較国に入れない（補わない）' } },
    intl: null, reference: false,
    note: `損失額は付加価値で測るため、宿泊者数ではなく宿泊・飲食サービス業の付加価値を使う（飲食を含むため代理）。${OECD_NOTE}`,
  },
  {
    indicator: '貸出残高', definition: '預金銀行の民間向け国内与信（GDP比%、世界銀行 FD.AST.PRVT.GD.ZS）',
    sector: null,
    intl: { code: 'WB:FD.AST.PRVT.GD.ZS', label: '世界銀行 預金銀行の民間向け国内与信（GDP比%）', rebase: false, better: 'higher', source: { file: 'more-stats/worldbank_extra.csv', countryColumn: '区分', where: { 備考: '世界銀行 WDI FD.AST.PRVT.GD.ZS' } } },
    gdp: sna({ 2020: '合計', 2015: '合計', 2011: '合計', 2005: '合計', 2000: '合計' }),
    reference: true, note: LOAN_NOTE,
    // 取得済みの値で、2000→2001年に日本179→104、韓国68→100、スウェーデン40→90、カナダ74→121と多くの国が同時に段差を持ち、ドイツ・スペイン・フランス・イタリア・オランダの5か国は2001年から始まる。
    breaks: [{ year: 2001, evidence: '世界銀行の与信のGDP比は2000年と2001年の間で多くの国の値が同時に段差を持つ（日本179→104%、韓国68→100%、スウェーデン40→90%、カナダ74→121%）。定義の変わり目とみなし、またぐ窓はつながない' }],
  },
];

/**
 * field-expansion-v1 の新分野（docs/提案/分野の拡張-v1.md の3・5-2、承認項目 B1・B3・B4 の推奨）。日本の国民経済計算は基準ごとの候補（教育・保健衛生・専門サービス・その他のサービスは
 * 2011基準以降だけ）、国際は OECD 表6の ISIC Rev.4 の節。節が industry_va.csv にまだ無いときは、補わず保留にする（buildLossInput の blocked）。
 * 代理の語に当たった法律の指標（「（代理）」付き）は reference：合計に入れず、公開せず、議員への配分に使わない。
 */
const EXPANSION_LOSS: Record<NewField, { sna: Partial<Record<(typeof SNA_BASES)[number], string>>; sections: string[]; label: string; note?: string }> = {
  '農林水産': { sna: { 2020: '1.農林水産業', 2015: '1.農林水産業', 2011: '1.農林水産業', 2005: '(1)農林水産業', 2000: '(1)農林水産業' }, sections: ['A'], label: '農林水産業（A）' },
  '建設': { sna: { 2020: '5.建設業', 2015: '5.建設業', 2011: '5.建設業', 2005: '(4)建設業', 2000: '(4)建設業' }, sections: ['F'], label: '建設業（F）' },
  '住宅・不動産': { sna: { 2020: '11.不動産業', 2015: '11.不動産業', 2011: '11.不動産業', 2005: '(8)不動産業', 2000: '(8)不動産業' }, sections: ['L'], label: '不動産業（L）',
    note: '不動産業の付加価値の大半は持ち家の帰属家賃で、法律の効果にほぼ反応しない' },
  '教育': { sna: { 2020: '14.教育', 2015: '14.教育', 2011: '14.教育' }, sections: ['P'], label: '教育（P）',
    note: '教育の付加価値は提供量（人員・時間）で測られる側面があり、上がっても成果が良くなったとは限らない' },
  '医療・福祉': { sna: { 2020: '15.保健衛生・社会事業', 2015: '15.保健衛生・社会事業', 2011: '15.保健衛生・社会事業' }, sections: ['Q'], label: '保健衛生・社会事業（Q）',
    note: '保健衛生・社会事業の付加価値は提供量で測られる側面があり、上がっても成果が良くなったとは限らない' },
  '製造業': { sna: { 2020: '3.製造業', 2015: '3.製造業', 2011: '3.製造業', 2005: '(3)製造業', 2000: '(3)製造業' }, sections: ['C'], label: '製造業（C）' },
  '商業': { sna: { 2020: '6.卸売・小売業', 2015: '6.卸売・小売業', 2011: '6.卸売・小売業', 2005: '(6)卸売・小売業', 2000: '(6)卸売・小売業' }, sections: ['G'], label: '卸売・小売業（G）' },
  '専門サービス・研究開発': { sna: { 2020: '12.専門・科学技術、業務支援サービス業', 2015: '12.専門・科学技術、業務支援サービス業', 2011: '12.専門・科学技術、業務支援サービス業' }, sections: ['M', 'N'], label: '専門・科学技術、業務支援サービス（M+N）' },
  '文化・娯楽・生活サービス': { sna: { 2020: '16.その他のサービス', 2015: '16.その他のサービス', 2011: '16.その他のサービス' }, sections: ['R', 'S'], label: 'その他のサービス（R+S）',
    note: '日本の「その他のサービス」に雇用主としての世帯（T）が含まれるかは未確認のため、T は足さない' },
};
const COMPOSITE_NOTE = '複数の節（ISIC Rev.4）を足した系列で、連鎖実質（LR）は加法性がないため近似';
const MISSING_OECD = '国際比較の系列が未取得';

export const EXPANSION_LOSS_SOURCES: LossSource[] = NEW_FIELDS.flatMap(field => {
  const e = EXPANSION_LOSS[field], w = NEW_FIELD_WORDS[field];
  return (['直接', '代理'] as const).filter(m => m === '代理' || w.direct.length > 0).map((match): LossSource => ({
    indicator: newIndicator(field, match),
    definition: `${e.label}の実質付加価値（ISIC Rev.4 ${e.sections.join('+')}）`,
    sector: sna(e.sna),
    oecd: { industry: e.sections[0], parts: e.sections.length > 1 ? e.sections : undefined, label: e.label, excludeIfCrossing: [ITA_BREAK], countryNotes: { AUS: AUS_NOTE } },
    intl: null, reference: match === '代理',
    note: [OECD_NOTE, e.sections.length > 1 ? COMPOSITE_NOTE : '', e.note ?? '',
      match === '代理' ? '代理：題名の語が法律の対象と産業の括りを直接には結ばない。向きは機械的な仮定なので参考にとどめ、合計に入れず、公開せず、議員への配分に使わない' : ''].filter(Boolean).join('。'),
  }));
});
LOSS_SOURCES.push(...EXPANSION_LOSS_SOURCES);

export type ImpactRow = Row;
export type LossLaw = { id: string; title: string; field: string; indicator: string; start: string; stage: 1 | 2 | 3 | null; direction: 'benefit' | 'harm' | null;
  /** impact.csv の向きが「上昇／低下」（代理の語に当たった法律。貢献・悪影響とは読まない）。 */
  neutral?: boolean };

/** impact.csv の行 → 判定ルールに渡す段階と向き。判定欄が「段階N」でなければ stage は null。 */
export function toLossLaw(r: ImpactRow): LossLaw {
  const m = /^段階([123])$/.exec(r['判定']);
  const direction = r['向き'] === '貢献' || r['向き'] === '上昇' ? 'benefit' : r['向き'] === '悪影響' || r['向き'] === '低下' ? 'harm' : null;
  return { id: r.id, title: r['題名'], field: r['分野'], indicator: r['指標'], start: r['施行日'], stage: m ? Number(m[1]) as 1 | 2 | 3 : null, direction,
    ...(r['向き'] === '上昇' || r['向き'] === '低下' ? { neutral: true } : {}) };
}

/** loss-rule-v1 の本来の対象（段階2以上・向きあり）。判定ルールも同じ条件で保留にする。 */
export const qualifies = (l: LossLaw) => l.stage !== null && l.stage >= 2 && l.direction !== null;

/** 段階1（対象の指標は動いたが、経済全体の指標では確認できていない）で向きのある行。額は参考として出すだけで、合計・公開・議員への配分には使わない。 */
export const isStage1Reference = (l: LossLaw) => l.stage === 1 && l.direction !== null;

/** 表に載せる行：本来の対象と、参考として額を出す段階1。 */
export const listed = (l: LossLaw) => qualifies(l) || isStage1Reference(l);

export const STAGE1_REFERENCE_REASON = '参考（段階1）：対象の指標は動いたが、経済全体の指標では確認できていないため、この額は合計に入れず、公開に使わず、議員への配分にも使わない。段階2以上と同じ方法・同じ入力で計算した参考値';

/** 損失額の窓：開始年の5年前〜開始後10年目（開始年が1年目）。 */
export const lossWindow = (start: string) => { const y = startYear(start); return { from: y - 5, to: y + MAX_LOSS_YEARS - 1 }; };

/** 基準ごとの候補から、窓の年を最も多く覆うものを選ぶ（同数なら新しい基準）。実質と名目は同じ基準から取る。 */
export function chooseSna(tables: Tables, options: Sna[], start: string) {
  const { from, to } = lossWindow(start);
  let best: { option: Sna; real: Map<number, number>; nominal: Map<number, number>; coverage: number } | null = null;
  for (const option of options) {
    const real = extractSeries(tables, snaReal(option)), nominal = extractSeries(tables, snaNominal(option));
    let coverage = 0;
    for (let y = from; y <= to; y++) if (real.has(y)) coverage++;
    if (best === null || coverage > best.coverage) best = { option, real, nominal, coverage };
  }
  return best && best.coverage > 0 ? best : null;
}

const toPoints = (m: Map<number, number>, from: number, to: number): CountryPoint[] =>
  [...m.keys()].filter(y => y >= from && y <= to).sort((a, b) => a - b).map(y => ({ asOf: asOfYear(y), value: m.get(y)! }));

/**
 * 比較国は、日本の窓の年をすべて持つ国だけにする（判定ルールは1国でも年が欠けると全体を保留にするため）。
 * 最新の年は国によって公表が遅れるので、開始前の窓を持つ国の半数以上（かつ min か国以上）がそろう最後の年で、開始後の窓を切る。
 */
export function alignControls(treated: CountryPoint[], candidates: CountrySeries[], start: string, min = 3) {
  const sets = candidates.map(c => ({ c, s: new Set(c.points.map(p => p.asOf)) }));
  const preJp = treated.filter(p => p.asOf < start);
  const withPre = sets.filter(({ s }) => preJp.every(p => s.has(p.asOf)));
  const need = Math.max(min, Math.ceil(withPre.length / 2));
  let jp = [...treated];
  const full = () => withPre.filter(({ s }) => jp.every(p => s.has(p.asOf)));
  while (full().length < need && jp.length && jp[jp.length - 1].asOf >= start) jp = jp.slice(0, -1);
  const keep = new Set(jp.map(p => p.asOf));
  return { treated: jp, controls: full().map(({ c }) => ({ country: c.country, points: c.points.filter(p => keep.has(p.asOf)) })) };
}

/** blocked があれば判定ルールを呼ばない（系列の定義が窓の中で変わるなど、入力を作れない理由）。 */
export type LossBuilt = { input: LossInput; elements: string[]; note: string; reference: boolean; baseYear: number | null; blocked?: string; stage1Reference?: boolean };

/** 1法律の loss-rule-v1 の入力。系列が無いものも、無いまま（比較国0か国など）判定ルールに渡す。 */
export function buildLossInput(tables: Tables, law: LossLaw, sources: LossSource[] = LOSS_SOURCES): LossBuilt | null {
  const source = sources.find(s => s.indicator === law.indicator);
  if (!source) return null;
  const { from, to } = lossWindow(law.start);
  const elements: string[] = [];
  const judgement = { stage: law.stage, direction: law.direction };

  if (source.oecd) {
    const { label, excludeIfCrossing = [], countryNotes = {}, missing = {} } = source.oecd;
    const missingParts = missingOecdParts(tables, source.oecd);
    if (missingParts.length) {
      // 節がまだ取得されていない：補わず、入力を作らずに保留にする（エラーにしない）。
      const blocked = `保留（${MISSING_OECD}）：OECD 表6の産業 ${missingParts.join('・')} が ${OECD_FILE} にない（${label} の比較に必要。scripts/fetch_oecd_industry.py で取得してから再実行する）`;
      elements.push(`日本：OECD 表6 JPN ${label} 連鎖実質（LR、2020年基準）の系列なし（${MISSING_OECD}）`, '比較国：0か国（同じ産業の系列が未取得）', '規制の便益：未測定');
      return { input: { definition: source.definition, start: law.start, judgement, treated: [], controls: [], baseNominalYen: 0, regulationBenefitYen: null }, elements, note: source.note, reference: source.reference, baseYear: null, blocked };
    }
    const real = oecdAggregate(tables, source.oecd, 'LR'), nominalAll = oecdAggregate(tables, source.oecd, 'V');
    const jpReal = real.get('JPN') ?? new Map<number, number>();
    const excluded = excludeIfCrossing.filter(e => e.year > from && e.year <= to);
    const excludedSet = new Set(excluded.map(e => e.country));
    const candidates: CountrySeries[] = [...real.entries()].filter(([c]) => c !== 'JPN' && !excludedSet.has(c))
      .map(([country, m]) => ({ country, points: toPoints(m, from, to) }));
    const aligned = alignControls(toPoints(jpReal, from, to), candidates, law.start);
    const tr = aligned.treated;
    const pre = tr.filter(p => p.asOf < law.start);
    const baseYear = pre.length ? Number(pre[pre.length - 1].asOf.slice(0, 4)) : null;
    const nominal = baseYear !== null ? nominalAll.get('JPN')?.get(baseYear) ?? null : null;
    // OECD の単位は百万円。
    const baseNominalYen = nominal === null ? 0 : nominal * 1e6;
    elements.push(`日本：OECD 表6 JPN ${label} 連鎖実質（LR、2020年基準）${tr.length ? `${tr[0].asOf.slice(0, 4)}〜${tr[tr.length - 1].asOf.slice(0, 4)}年` : 'なし'}`);
    let nominalLabel = baseYear !== null && nominal !== null ? `開始前最後の年（${baseYear}年）の名目付加価値 ${nominal}百万円（OECD V）` : '開始前最後の年の名目付加価値なし';
    const snaChosen = source.sector && baseYear !== null ? chooseSna(tables, source.sector, law.start) : null;
    const snaNom = snaChosen && baseYear !== null ? snaChosen.nominal.get(baseYear) : undefined;
    if (nominal !== null && snaNom !== undefined) {
      const diff = nominal / (snaNom * 1e3) - 1;
      nominalLabel += `。国民経済計算${snaChosen!.option.base}基準「${snaChosen!.option.activity}」の名目は${snaNom}十億円（${Math.abs(diff) < 5e-7 ? '同じ値' : `差${(diff * 100).toFixed(2)}%`}）`;
    }
    elements.push(nominalLabel);
    const used = aligned.controls.map(c => c.country);
    elements.push(`比較国：${used.length}か国（${used.join('・')}）。OECD 表6の同じ産業の LR で、日本の窓の年をすべて持つ国だけ`);
    for (const e of excluded) elements.push(`除外：${e.evidence}`);
    for (const [c, why] of Object.entries(missing)) if (!real.has(c)) elements.push(`除外：${why}`);
    for (const c of used) if (countryNotes[c]) elements.push(`注記：${countryNotes[c]}`);
    const lastPost = tr.length ? Number(tr[tr.length - 1].asOf.slice(0, 4)) : null;
    if (lastPost !== null && lastPost < Math.min(to, Math.max(...jpReal.keys()))) elements.push(`比較国をそろえるため開始後は${lastPost}年まで`);
    elements.push('規制の便益：未測定');
    return { input: { definition: source.definition, start: law.start, judgement, treated: tr, controls: aligned.controls, baseNominalYen, regulationBenefitYen: null }, elements, note: source.note, reference: source.reference, baseYear };
  }

  if (source.sector) {
    const chosen = chooseSna(tables, source.sector, law.start);
    const treated = chosen ? toPoints(chosen.real, from, to) : [];
    const pre = treated.filter(p => p.asOf < law.start);
    const baseYear = pre.length ? Number(pre[pre.length - 1].asOf.slice(0, 4)) : null;
    const nominal = chosen && baseYear !== null ? chosen.nominal.get(baseYear) ?? null : null;
    const baseNominalYen = nominal === null ? 0 : nominal * 1e9;
    elements.push(chosen ? `日本：国民経済計算${chosen.option.base}基準 実質（連鎖）「${chosen.option.activity}」${treated.length ? `${treated[0].asOf.slice(0, 4)}〜${treated[treated.length - 1].asOf.slice(0, 4)}年` : ''}` : '日本：系列なし');
    elements.push(baseYear !== null && nominal !== null ? `開始前最後の年（${baseYear}年）の名目付加価値 ${nominal}十億円` : '開始前最後の年の名目付加価値なし');
    elements.push('比較国：同じ定義の系列が未取得のため0か国');
    elements.push('規制の便益：未測定');
    return { input: { definition: source.definition, start: law.start, judgement, treated, controls: [], baseNominalYen, regulationBenefitYen: null }, elements, note: source.note, reference: source.reference, baseYear };
  }

  // 与信のGDP比（%）を日本と比較国で比べる。
  const crossing = (source.breaks ?? []).find(b => b.year > from && b.year <= to);
  const byCountry = intlByCountry(tables, source.intl!);
  const jpAll = byCountry.get('JPN') ?? new Map<number, number>();
  const candidates: CountrySeries[] = [...byCountry.entries()].filter(([c]) => c !== 'JPN').sort(([a], [b]) => a.localeCompare(b))
    .map(([country, m]) => ({ country, points: toPoints(m, from, to) }));
  const aligned = alignControls(toPoints(jpAll, from, to), candidates, law.start);
  const pre = aligned.treated.filter(p => p.asOf < law.start);
  const baseYear = pre.length ? Number(pre[pre.length - 1].asOf.slice(0, 4)) : null;
  let baseNominalYen = 0, gdpLabel = '開始前最後の年の名目GDPなし';
  if (baseYear !== null) {
    for (const option of source.gdp ?? []) {
      const g = extractSeries(tables, snaNominal(option)).get(baseYear);
      if (g === undefined) continue;
      const ratio = jpAll.get(baseYear)!;
      // 開始前最後の年の与信残高（円）＝ 与信のGDP比 ÷ 100 × 名目GDP。判定ルールはこれを「開始前最後の年の名目値」として使う。
      baseNominalYen = ratio / 100 * g * 1e9;
      gdpLabel = `開始前最後の年（${baseYear}年）の与信残高＝与信のGDP比${ratio.toFixed(2)}%×名目GDP ${g}十億円（国民経済計算${option.base}基準）`;
      break;
    }
  }
  const tr = aligned.treated;
  elements.push(`日本：${source.intl!.label}${tr.length ? ` ${tr[0].asOf.slice(0, 4)}〜${tr[tr.length - 1].asOf.slice(0, 4)}年` : ''}`);
  elements.push(gdpLabel);
  elements.push(`比較国：${aligned.controls.length}か国（${aligned.controls.map(c => c.country).join('・')}）。日本の窓の年をすべて持つ国だけ`);
  const lastPost = tr.length ? Number(tr[tr.length - 1].asOf.slice(0, 4)) : null;
  if (lastPost !== null && lastPost < Math.min(to, Math.max(...jpAll.keys()))) elements.push(`比較国をそろえるため開始後は${lastPost}年まで`);
  elements.push('規制の便益：未測定');
  const blocked = crossing ? `保留（系列の断絶）：損失額の窓（${from}〜${to}年）が${crossing.year}年をまたぐ。${crossing.evidence}` : undefined;
  return { input: { definition: source.definition, start: law.start, judgement, treated: aligned.treated, controls: aligned.controls, baseNominalYen, regulationBenefitYen: null }, elements, note: source.note, reference: source.reference, baseYear, blocked };
}

// ---- 独立でない観測のまとまり ----

/**
 * 同じ指標（同じ系列）で、損失額の窓（開始前5年〜開始後10年目）が重なる法律を1つのまとまりにする。
 * まとまりの中の損失額は同じ系列の同じ年を何度も数えるので、足してはいけない。
 */
export function observationGroups(laws: { id: string; indicator: string; start: string }[]): Map<string, string> {
  const out = new Map<string, string>();
  const byIndicator = new Map<string, typeof laws>();
  for (const l of laws) byIndicator.set(l.indicator, [...(byIndicator.get(l.indicator) ?? []), l]);
  for (const [indicator, list] of [...byIndicator.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const sorted = [...list].sort((a, b) => a.start.localeCompare(b.start) || a.id.localeCompare(b.id));
    let n = 0, groupEnd = -Infinity;
    for (const l of sorted) {
      const w = lossWindow(l.start);
      if (w.from > groupEnd) n++;
      groupEnd = Math.max(groupEnd, w.to);
      out.set(l.id, `${indicator}-${n}`);
    }
  }
  return out;
}

// ---- 表 ----

export type LossRow = { law: LossLaw; result: LossResult | null; built: LossBuilt | null; group: string; stage1Reference?: boolean };

const yen = (x: number) => String(x);
export function amountCell(r: LossResult | null): string {
  if (!r || !r.lossYen) return '';
  const { low, median, high } = r.lossYen;
  return `${median >= 0 ? '損失' : '便益'}：中央値=${yen(median)};第1四分位=${yen(low)};第3四分位=${yen(high)}`;
}

export const LOSS_HEADER = ['id', '題名', '分野', '指標', '段階', '向き', '損失または便益の額', '単位', '計算式の要素', '参考フラグ', '理由', '観測グループ'];

export function lossRow({ law, result, built, group, stage1Reference }: LossRow): string[] {
  const reasons: string[] = [];
  if (stage1Reference) reasons.push(STAGE1_REFERENCE_REASON);
  if (!built) reasons.push('損失額の入力の対応がない指標');
  else {
    reasons.push(built.blocked ?? result!.reason);
    reasons.push(built.note);
  }
  const { to } = lossWindow(law.start);
  const covid = [2020, 2021, 2022].filter(y => y >= startYear(law.start) && y <= to);
  if (covid.length) reasons.push(`注意：損失額の開始後の窓（${startYear(law.start)}〜${to}年）に新型コロナの${covid.join('・')}年を含む。判定ルールは同時期の別の出来事を除かない`);
  reasons.push(`独立でない：観測グループ ${group} の中の法律は同じ系列の重なる年を使うので、額を足さない`);
  const unit = result?.lossYen ? `円（開始後${result.years}年の累積、名目は開始前最後の年${built?.baseYear ?? ''}年の水準）` : '';
  return [
    law.id, law.title, law.field, law.indicator, law.stage === null ? '保留' : `段階${law.stage}`,
    law.direction === 'benefit' ? (law.neutral ? '上昇' : '貢献') : law.direction === 'harm' ? (law.neutral ? '低下' : '悪影響') : '',
    amountCell(result), unit, built ? built.elements.join('／') : '', built?.reference || stage1Reference ? '参考' : '', reasons.join('／'), group,
  ];
}

/**
 * impact.csv の全行から、対象の法律に loss-rule-v1 をかけた表の行。
 * includeStage1 のとき（振り分けv2の出力）だけ、段階1（向きあり）も同じ入力・同じ estimateLoss で額を計算するが、参考扱い（reference=true）にする。
 * estimateLoss は段階2未満を保留にするので、計算のときだけ段階2として渡す（段階1の行を参考として計算するための唯一の例外。表の「段階」欄は段階1のまま）。
 */
export function evaluateLosses(tables: Tables, impactRows: ImpactRow[], sources: LossSource[] = LOSS_SOURCES, options: { includeStage1?: boolean } = {}): LossRow[] {
  const laws = impactRows.map(toLossLaw).filter(options.includeStage1 ? listed : qualifies);
  const groups = observationGroups(laws);
  return laws.map(law => {
    const stage1Reference = isStage1Reference(law);
    const built = buildLossInput(tables, law, sources);
    if (built && stage1Reference) {
      built.input = { ...built.input, judgement: { stage: 2, direction: law.direction } };
      built.reference = true;
      built.stage1Reference = true;
    }
    return { law, built, result: built && !built.blocked ? estimateLoss(built.input) : null, group: groups.get(law.id)!, stage1Reference };
  });
}
