/**
 * 評価対象の法律を一括で impact-rule-v1 にかける処理（impact-v1）。
 * 判定は app/src/impact-rule.ts の judgeImpact / judgeAcrossCountries だけが行い、ここでは系列を選んで窓を作るだけです。
 * ファイルの読み書きは app/scripts/run-impact-v1.mjs が行い、このモジュールは純粋な関数だけにします（ブラウザ用ビルドにも入れられる）。
 * 方法の説明は data/derived/impact-v1/spec.md。
 */
import { NEW_FIELDS, NEW_FIELD_WORDS, PROXY_SUFFIX, type NewField } from './indicator-pick';
import { judgeAcrossCountries, judgeImpact, MIN_PRE_YEARS, type CountryPoint, type ImpactPoint, type ImpactSeries } from './impact-rule';

export type Row = Record<string, string>;
/** 取得済み CSV の中身。キーは data/acquired/ からの相対パス。 */
export type Tables = Map<string, Row[]>;

/** 1つの CSV から、列の値で絞った1系列（年→値）を指す。 */
export type Ref = { file: string; where: Row; valueColumn?: string; yearColumn?: string };
/** 対象と比較の組。対象と比較は同じ基準・同じ分類のファイルから取る（系列接続禁止）。 */
export type PairOption = { name: string; treated: Ref; control: Ref };
/** 年の数え方。calendar は暦年（期末12月31日）、fiscal は4月始まりの年度（期末翌年3月31日）。対象と比較は同じ数え方のものだけを組にする。 */
export type Period = 'calendar' | 'fiscal';
export type PairSpec = { definition: string; better: 'lower' | 'higher'; options: PairOption[]; period?: Period };
export type ShareOption = { name: string; sector: Ref; total: Ref };
/**
 * 国際比較の系列。ratio があれば code ÷ ratio を各国で計算する。rebase は指数・金額を開始前最後の年=100にそろえるか。
 * source が無ければ intl-stats/intl-stats.csv（国,指標,年,値）の「指標」列で code を探す。
 * source があれば、そのファイルで where に合う行を取り、国は countryColumn の列から読む（ratio は使えない）。
 */
export type IntlSource = { file: string; countryColumn: string; where: Row; /** 候補の名前（altSources から選んだとき理由欄に書く）。 */ name?: string };
/**
 * altSources は、同じ指標を測る別の出所の候補（値が一致しない別の取得物など）。source と altSources のうち、日本の判定に必要な10年を最も多く覆うものを
 * 法律ごとに1つ選ぶ（同数なら先に書いたもの）。候補どうしはつながない（chooseOption と同じ考え方）。
 * reference は、向き（高いほど良いか）を決められない指標。better は計算上の置き方にすぎず、貢献・悪影響とは読まず、「上昇／低下」と書く。
 */
export type IntlSpec = { code: string; ratio?: string; label: string; rebase: boolean; better: 'lower' | 'higher'; source?: IntlSource; altSources?: IntlSource[]; reference?: boolean };
export type Mapping = {
  indicator: string;
  field: string;
  /** 比較群なし：系列は取得済みだが、法律が経済全体に及ぶため影響を受けない比較群が国内になく、国際の系列も無い。 */
  match: '直接' | '代理' | '比較群なし' | '系列なし';
  target: PairSpec | null;
  economy: PairSpec | null;
  share: ShareOption[];
  intl: IntlSpec | null;
  reason: string;
  /** 取得済みだが判定に使わない系列（使わない理由は reason に書く）。 */
  unused?: string;
  /**
   * 法律の題名で系列を決める指標（利用件数）。題名がちょうど1つの規則の keyword だけを含むときに、その施設・交通機関の系列を実質GDPと比べる。
   * 0個または2個以上に当たる題名は系列なし（施設・交通機関を一意に名指していない）。
   */
  titleRules?: TitleRule[];
  /** 新しく配線した系列で判定できないとき（日本の開始前が3年に足りない等）に、元の判定を保つ。 */
  keepVerdict?: '系列なし' | '比較群なし' | '国内系列なし';
  /** 代理の系列（field-expansion-v1 の代理の語に当たる法律）。向き（高いほど良い）は機械的な仮定にすぎないので、貢献・悪影響とは読まず「上昇／低下」と書く。合計・公開・議員への配分には使わない。 */
  reference?: boolean;
};
export type TitleRule = { keyword: string; name: string; ref: Ref };

const sna = (base: string) => `domestic-stats/sna_gdp_by_industry_${base}base.csv`;
const snaReal = (base: string, activity: string): Ref => ({ file: sna(base), where: { 価格: '実質(連鎖方式)', 経済活動: activity } });
const snaNominal = (base: string, activity: string): Ref => ({ file: sna(base), where: { 価格: '名目', 経済活動: activity } });
const lfs = (cls: string, industry: string): Ref => ({ file: `domestic-stats/lfs_employed_by_industry_${cls}.csv`, where: { 産業: industry } });
const cpi = (base: string, where: Row): Ref => ({ file: `domestic-stats/cpi_items_annual_${base}base.csv`, where });

/** SNA の基準ごとの経済活動名。2000基準は運輸と通信が1つで、分けられないものは入れない。 */
const SNA_BASES = ['2020', '2015', '2011', '2005', '2000'] as const;
type SnaKey = 'ict' | 'transport' | 'lodging' | 'electricity' | 'electronics' | 'finance'
  | 'agriculture' | 'construction' | 'realEstate' | 'education' | 'health' | 'manufacturing' | 'commerce' | 'professional' | 'otherServices';
const SNA_NAMES: Record<SnaKey, Partial<Record<(typeof SNA_BASES)[number], string>>> = {
  ict: { 2020: '9.情報通信業', 2015: '9.情報通信業', 2011: '9.情報通信業', 2005: '(10)情報通信業' },
  transport: { 2020: '7.運輸・郵便業', 2015: '7.運輸・郵便業', 2011: '7.運輸・郵便業', 2005: '(9)運輸業' },
  lodging: { 2020: '8.宿泊・飲食サービス業', 2015: '8.宿泊・飲食サービス業', 2011: '8.宿泊・飲食サービス業' },
  electricity: { 2020: '4.電気・ガス・水道・廃棄物処理業', 2015: '4.電気・ガス・水道・廃棄物処理業', 2011: '4.電気・ガス・水道・廃棄物処理業', 2005: '(5)電気・ガス・水道業', 2000: '(5)電気・ガス・水道業' },
  electronics: { 2020: '(10)電子部品・デバイス', 2015: '(10)電子部品・デバイス', 2011: '(10)電子部品・デバイス' },
  finance: { 2020: '10.金融・保険業', 2015: '10.金融・保険業', 2011: '10.金融・保険業', 2005: '(7)金融・保険業', 2000: '(7)金融・保険業' },
  // field-expansion-v1（docs/提案/分野の拡張-v1.md の3）。2005・2000基準は教育・保健衛生・専門サービス・その他のサービスを1つの「サービス業」にまとめていて
  // 分けられないので入れない（別の定義の行を代わりに使わず、つながない）。その分野の候補は2011・2015・2020基準だけ。
  agriculture: { 2020: '1.農林水産業', 2015: '1.農林水産業', 2011: '1.農林水産業', 2005: '(1)農林水産業', 2000: '(1)農林水産業' },
  construction: { 2020: '5.建設業', 2015: '5.建設業', 2011: '5.建設業', 2005: '(4)建設業', 2000: '(4)建設業' },
  realEstate: { 2020: '11.不動産業', 2015: '11.不動産業', 2011: '11.不動産業', 2005: '(8)不動産業', 2000: '(8)不動産業' },
  education: { 2020: '14.教育', 2015: '14.教育', 2011: '14.教育' },
  health: { 2020: '15.保健衛生・社会事業', 2015: '15.保健衛生・社会事業', 2011: '15.保健衛生・社会事業' },
  manufacturing: { 2020: '3.製造業', 2015: '3.製造業', 2011: '3.製造業', 2005: '(3)製造業', 2000: '(3)製造業' },
  commerce: { 2020: '6.卸売・小売業', 2015: '6.卸売・小売業', 2011: '6.卸売・小売業', 2005: '(6)卸売・小売業', 2000: '(6)卸売・小売業' },
  professional: { 2020: '12.専門・科学技術、業務支援サービス業', 2015: '12.専門・科学技術、業務支援サービス業', 2011: '12.専門・科学技術、業務支援サービス業' },
  otherServices: { 2020: '16.その他のサービス', 2015: '16.その他のサービス', 2011: '16.その他のサービス' },
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

/** 日本銀行 貸出先別貸出金（国内銀行、12月末残高）。年は暦年の12月末なので、暦年の国民経済計算と組にできる。 */
const bojLoans = (sector: string): Ref => ({ file: 'more-stats/bank_loans_by_sector_boj.csv', where: { 区分: sector } });
/** 貸出残高（名目・億円）対 名目GDP（10億円）。単位は100にそろえるので消える。国民経済計算の基準ごとに候補を作る（つながない）。 */
const loansVsNominalGdp: PairOption[] = SNA_BASES.map(base => ({
  name: `日本銀行 貸出先別貸出金「総貸出」（国内銀行、12月末残高）対 国民経済計算${base}基準 名目「合計」`, treated: bojLoans('総貸出'), control: snaNominal(base, '合計'),
}));
/** 年が4月始まりの年度のファイル。年度の系列は年度の系列とだけ組にする（暦年の系列と組にしない）。 */
export const FISCAL_YEAR_FILES = ['more-stats/energy_total_energy_statistics.csv'];
/** 総合エネルギー統計（年度）。 */
const energy = (series: string, category: string): Ref => ({ file: 'more-stats/energy_total_energy_statistics.csv', where: { 系列: series, 区分: category } });
/** 世界銀行 WDI の追加取得分（more-stats/worldbank_extra.csv）。国は「区分」列、指標コードは「備考」列にある。 */
const wbExtra = (code: string): IntlSource => ({ file: 'more-stats/worldbank_extra.csv', countryColumn: '区分', where: { 備考: `世界銀行 WDI ${code}` } });

/** gap-stats（data/acquired/gap-stats/）の表。 */
const gap = (file: string, where: Row): IntlSource => ({ file: `gap-stats/${file}`, countryColumn: '国', where });
const AIRPORTS = 'gap-stats/airport_passengers.csv';
const airport = (division: string): Ref => ({ file: AIRPORTS, where: { 国: 'JPN', 区分: `${division}／暦年／合計` } });
/**
 * 利用件数：題名に施設・交通機関の名前がちょうど1つだけあるときの系列。空港別の乗降客数（暦年・国際線＋国内線）。
 * 港湾・道路・自動車は利用件数を取得していない。鉄道（鉄道統計年報）は年度の系列で、年度の比較群（年度のGDPなど）が取得済みの統計に無く、
 * 暦年の実質GDPと組にしない方針（年度と暦年を組にしない）のため配線しない。
 */
export const USAGE_TITLE_RULES: TitleRule[] = [
  { keyword: '中部国際空港', name: '空港管理状況調書 中部国際空港の乗降客数（暦年）', ref: airport('中部国際（会社管理）') },
  { keyword: '成田国際空港', name: '空港管理状況調書 成田国際空港の乗降客数（暦年）', ref: airport('成田国際（会社管理）') },
  { keyword: '関西国際空港', name: '空港管理状況調書 関西国際空港の乗降客数（暦年）', ref: airport('関西国際（会社管理）') },
  { keyword: '東京国際空港', name: '空港管理状況調書 東京国際空港の乗降客数（暦年）', ref: airport('東京国際（国管理）') },
  { keyword: '航空法', name: '空港管理状況調書 全空港計の乗降客数（暦年）', ref: airport('全空港計３（全空港計１、全空港計２）') },
];
/** 題名から利用件数の規則を1つ決める。0個・2個以上は null。 */
export function matchTitleRule(rules: TitleRule[], title: string): TitleRule | null {
  const hit = rules.filter(r => title.includes(r.keyword));
  return hit.length === 1 ? hit[0] : null;
}
/** 題名で系列を決める対応表から、この法律の対応を作る。当たる規則が無ければ null。titleRules が無い対応はそのまま。 */
export function resolveMapping(mapping: Mapping, law: { title: string }): Mapping | null {
  if (!mapping.titleRules) return mapping;
  const rule = matchTitleRule(mapping.titleRules, law.title);
  if (!rule) return null;
  return {
    ...mapping,
    target: {
      definition: `${rule.name}の指数と実質GDP指数（開始前最後の年=100）`, better: 'higher',
      options: SNA_BASES.map(base => ({ name: `${rule.name}対 国民経済計算${base}基準 実質「合計」`, treated: rule.ref, control: snaReal(base, '合計') })),
    },
  };
}

const none = (indicator: string, field: string, reason: string): Mapping => ({ indicator, field, match: '系列なし', target: null, economy: null, share: [], intl: null, reason });
/** 比較群なし：国内の比較群は作れない。intl があれば国際比較だけ行い、判定は「比較群なし」のまま国際比較の欄に結果を書く。 */
const noControl = (indicator: string, field: string, unused: string, reason: string, intl: IntlSpec | null = null): Mapping => ({ indicator, field, match: '比較群なし', target: null, economy: null, share: [], intl, reason, unused });

/**
 * triage の指標 → 取得済みの系列。結果を見る前に固定する（docs/indicator-control-table.md の考え方）。
 * 比較群は「その分野の値」対「経済全体の同じ種類の値」（付加価値なら GDP、就業者なら就業者総数、物価なら総合指数）。
 */
const BASE_MAP: Mapping[] = [
  {
    indicator: '不良債権比率', field: '金融', match: '直接',
    target: null, economy: null, share: [],
    intl: {
      code: 'WB:FB.AST.NPER.ZS', label: '世界銀行 銀行の不良債権比率（総貸出に対する%）', rebase: false, better: 'lower', source: { ...wbExtra('FB.AST.NPER.ZS'), name: 'WDI FB.AST.NPER.ZS（日本2010〜2022年）' },
      altSources: [{ ...gap('npl_wb_gfdd.csv', { 区分: 'WB:GFDD.SI.02' }), name: 'GFDD.SI.02（日本1998〜2020年）' }],
    },
    unused: '金融庁 金融再生法開示債権の状況（全国銀行、不良債権比率、1999年3月期〜）［more-stats/npl_fsa_all_banks.csv］',
    reason: '対象の法律（預金保険法・金融再生法など）は全国の銀行に及ぶため、国内には影響を受けない比較群がない。金融庁の全国銀行の系列は取得したが、比べる相手がないので国内の判定には使わない（金融再生プログラム用の主要行対地域銀行の比較群も、全銀行に及ぶ法律では比較群も同時に影響を受けるため流用しない）。判定ルールが比較群なしで扱えるのは国際比較だけなので、世界銀行の不良債権比率で日本と12か国を比べる。金融庁の系列とは定義（金融再生法開示債権と IMF の金融健全性指標）が違うため、日本の値も世界銀行の系列を使う。日本の値は2010〜2022年だけなので、2004年以前に施行の法律は日本の開始前の値がない。世界銀行 GFDD.SI.02（日本1998〜2020年、gap-stats）は同じ名前の指標だが重なる年でも値が一致しない（最大2.3ポイント差）ため、つながずに別の候補とし、法律ごとに日本の判定に必要な10年を最も多く覆う方を1つ選ぶ（同数なら WDI）。1998年施行の法律は GFDD にも開始前の値がない',
  },
  {
    indicator: '貸出残高', field: '金融', match: '代理',
    target: { definition: '国内銀行の総貸出残高（12月末）の指数と名目GDP指数（開始前最後の年=100）', better: 'higher', options: loansVsNominalGdp },
    economy: { definition: '金融・保険業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('finance') },
    share: snaShare('finance'),
    intl: { code: 'WB:FD.AST.PRVT.GD.ZS', label: '世界銀行 預金銀行の民間向け国内与信（GDP比%）', rebase: false, better: 'higher', source: wbExtra('FD.AST.PRVT.GD.ZS') },
    reason: '日本銀行の貸出先別貸出金の総貸出（国内銀行の銀行・信託・海外店勘定の合計、12月末残高）を名目GDPと比べる（貸出の量が経済の規模より伸びたか）。法律の多くが全銀行・全借り手に及ぶため、業種や中小企業の区分ではなく総貸出を使う。信用金庫・政府系金融機関（日本政策投資銀行・日本政策金融公庫・商工中金など）の貸出は含まないため代理。貸出が増えるほど良いとみなす（向きは機械的な仮定。貸金業の規制のように貸出を抑える法律もある）。国際比較は世界銀行の預金銀行の民間向け与信のGDP比（比率のまま）',
  },
  none('企業倒産件数', '金融', '公式の倒産件数の系列を取得していない。よく使われる倒産件数は東京商工リサーチの集計で民間データのため使わない。公式の候補の司法統計（破産事件の新受件数）は機械的に取れず、推測で埋めないため未取得（docs/reports/more-stats.md）'),
  {
    indicator: '旅客輸送の付加価値', field: '交通・移動', match: '代理',
    target: { definition: '運輸業（旅客と貨物・郵便を含む）の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('transport') },
    economy: { definition: '運輸業の就業者数と就業者総数（開始前最後の年=100）', better: 'higher', options: lfsVsTotal('transport') },
    share: snaShare('transport'), intl: null,
    reason: '国民経済計算に旅客輸送だけの付加価値はなく、運輸業（2011基準以降は運輸・郵便業）で代える。貨物・郵便を含むため代理。2000基準は運輸・通信業が1つなので使わない。国際統計に産業別付加価値がないため国際比較なし',
  },
  {
    indicator: '利用件数', field: '交通・移動', match: '直接',
    target: null, titleRules: USAGE_TITLE_RULES, keepVerdict: '系列なし',
    economy: { definition: '運輸業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('transport') },
    share: snaShare('transport'), intl: null,
    reason: '題名が空港名（中部国際・成田国際・関西国際・東京国際）か「航空法」をちょうど1つだけ含む法律に限り、国土交通省 空港管理状況調書の乗降客数（暦年、国際線＋国内線）を実質GDPと比べる（利用が増えるほど良いとみなす。向きは機械的な仮定）。題名が施設・交通機関を一意に名指さない法律（交通政策基本法・港湾法・道路法・バリアフリー法・自動車関連など）は系列なし。港湾・道路・自動車の利用件数は未取得。鉄道（鉄道統計年報、年度）は取得したが、年度の比較群が取得済みの統計に無く、暦年のGDPと組にしないため配線しない。空港別の統計は2007年からで、2009年以前に施行の法律は開始前が3年に足りず、系列なしのままにする',
  },
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
    indicator: 'ブロードバンド普及率', field: '通信・ネット', match: '直接',
    target: null, economy: null, share: snaShare('ict'),
    intl: {
      code: 'WB:IT.NET.BBND.P2', label: '固定ブロードバンド契約数（人口100人当たり）', rebase: false, better: 'higher',
      source: { ...gap('broadband.csv', { 区分: 'WB:IT.NET.BBND.P2' }), name: '世界銀行 WDI IT.NET.BBND.P2（日本1998〜2023年）' },
      altSources: [{ ...gap('broadband.csv', { 系列: '固定ブロードバンド契約数（人口100人当たり、OECD）' }), name: 'OECD DF_BB_TEL_DATABASE（日本2009〜2025年）' }],
    },
    reason: '国内のブロードバンド契約数の時系列表は取得できていない（影響を受けない国内の比較群もない）ため、国際比較だけ行う。契約率そのものの系列（固定ブロードバンド契約数、人口100人当たり）を使う。世界銀行（1998年〜）と OECD（2009年〜）は出所が違うので、つながずに別の候補とし、法律ごとに日本の判定に必要な10年を最も多く覆う方を1つ選ぶ（同数なら世界銀行）。以前使ったインターネット利用者比率（契約率ではないため代理）はやめた。比率のまま比べる',
  },
  none('ネット企業の時価総額', '通信・ネット', '業種別の株式時価総額を載せた公式の時系列表が見つからず、取得していない'),
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
  {
    indicator: '発電構成', field: 'エネルギー', match: '直接',
    target: { definition: 'ゼロエミッション電源（原子力・再生可能）の発電量と総発電量（年度、開始前最後の年度=100）', better: 'higher', period: 'fiscal',
      options: [{ name: '総合エネルギー統計 電源構成（発電量）「ゼロエミッション電源」対「合計」（年度）', treated: energy('4.電源構成(発電量）', 'ゼロエミッション電源'), control: energy('4.電源構成(発電量）', '合計') }] },
    economy: { definition: '電気・ガス・水道業の実質付加価値指数と実質GDP指数（開始前最後の年=100）', better: 'higher', options: snaVsGdp('electricity') },
    share: snaShare('electricity'),
    intl: { code: 'WB:EG.ELC.FOSL.ZS', label: '世界銀行 化石燃料の発電比率（%）', rebase: false, better: 'lower', source: wbExtra('EG.ELC.FOSL.ZS') },
    reason: '対象の法律は原子力（立地・規制）と再生可能エネルギー（固定価格買取・洋上風力）で、どちらも化石燃料以外の電源を増やす向きなので、ゼロエミッション電源の発電量を総発電量と比べる（部分対全体）。総合エネルギー統計の電源構成は2010年度からしかないため、2012年度以前に施行の法律は国内の開始前が足りない。年度の系列なので4月始まりの年度で窓を作る。国際比較は世界銀行の化石燃料の発電比率（低いほど良い、比率のまま、1990年〜）',
  },
  {
    indicator: 'エネルギー効率', field: 'エネルギー', match: '代理',
    target: null, economy: null, share: [],
    intl: { code: 'WB:EG.EGY.PRIM.PP.KD', label: '世界銀行 一次エネルギー集約度（MJ/2021年PPP米ドル）', rebase: true, better: 'lower', source: wbExtra('EG.EGY.PRIM.PP.KD') },
    unused: '総合エネルギー統計 最終消費（部門別、PJ、年度）［more-stats/energy_total_energy_statistics.csv］と国民経済計算の実質GDP（暦年）［domestic-stats/sna_gdp_by_industry_*base.csv］',
    reason: '国内で「最終エネルギー消費÷実質GDP」を作るには、年度の総合エネルギー統計と暦年の国民経済計算を組にする必要があり、期間が3か月ずれるため作らない（同じ期間の系列だけを組にする。国民経済計算の年度の表は未取得）。省エネ法は全部門に及ぶため部門対全体の比較群もない。国際比較だけ行い、世界銀行の一次エネルギー集約度（GDP当たりの一次エネルギー供給、2000〜2022年）を日本の開始前最後の年=100にそろえて比べる。最終消費ではなく一次供給のため代理',
  },
  {
    indicator: '労働生産性', field: '労働市場', match: '代理',
    target: null, economy: null, share: [],
    intl: { code: 'WB:NY.GDP.MKTP.KD', ratio: 'WB:SL.TLF.TOTL.IN', label: '世界銀行 実質GDP（2015年米ドル）÷労働力人口', rebase: true, better: 'higher' },
    reason: '経済全体の法律なので国内に比較群がない。国際比較で、労働力人口1人当たり実質GDP（就業者・労働時間ではないため代理）を比べる',
  },
  noControl('賃金', '労働市場', '毎月勤労統計調査 現金給与総額など（産業×就業形態×規模）［more-stats/wages_monthly_labour_survey.csv］',
    '毎月勤労統計の賃金は取得したが、対象の法律（労働基準法・労働組合法・男女雇用機会均等法・短時間労働者法など）は全産業の労働者に及ぶため、影響を受けない産業がなく、分野対経済全体の比較群が作れない。国内の判定は行わず「比較群なし」のままにし、国際比較だけ行う: OECD の平均年間賃金（フルタイム換算の雇用者1人当たり、実質・2025年価格・米ドル購買力平価）を日本の開始前最後の年=100にそろえて13か国で比べる（高いほど良いとみなす。向きは機械的な仮定）。法律ごとに対象の集団（介護労働者なら医療,福祉、短時間労働者ならパート）を決めて比べる方法はありうるが、指標ごとに1つの対応に固定するこの段階では行わない',
    { code: 'OECD:AV_AN_WAGE_REAL_USD_PPP', label: 'OECD 平均年間賃金（実質・2025年価格・米ドル購買力平価）', rebase: true, better: 'higher', source: gap('oecd_wages.csv', { 系列: '平均年間賃金（OECD）', 区分: '実質（2025年価格）／米ドル（購買力平価）' }) }),
  noControl('雇用の流動性', '労働市場', '雇用動向調査 入職率・離職率・転職入職率（1991〜2025年）［more-stats/employment_turnover.csv］; 労働力調査 転職者数・転職者比率（2002〜2025年）［more-stats/job_changers_lfs.csv］',
    '雇用動向調査と労働力調査の転職の系列は取得したが、対象の法律（雇用保険法・高年齢者雇用安定法・育児介護休業法など）は全産業の労働者に及ぶため、影響を受けない産業がなく、分野対経済全体の比較群が作れない。国内の判定は行わず「比較群なし」のままにし、国際比較だけ行う: OECD の勤続1年未満の就業者の割合（就業者全体・男女計・年齢計、%、比率のまま）を日本と比較国で比べる。日本は2013年からなので、施行が2016年以降（開始前が3年以上）の法律だけが判定でき、それ以前は「国際：保留」。就業者全体の区分が無い米国・韓国は比較国に入らない（雇用者の区分とはつながない）。転職が多いほど良いか悪いかは決められない（流動性が高いことを望ましいとする既存の取り決めが無い）ので、向きは決めない「参考」とし、貢献・悪影響ではなく日本が比較国より「上昇／低下」と書き、議員への配分には使わない。年齢・性別の区分で対象の集団と全体を比べる方法はありうるが、法律ごとの対象の集団を決める必要があり、この段階では行わない',
    { code: 'OECD:TENURE_LT12', label: 'OECD 勤続1年未満の就業者割合（就業者全体・男女計、%）', rebase: false, better: 'higher', reference: true, source: gap('oecd_tenure.csv', { 区分: '勤続1年未満／就業者全体／男女計' }) }),
  none('電子申請率', '行政のデジタル化', '総務省の報道資料から国の行政手続のオンライン利用率（2007〜2015年度、日本のみ。2009年度は定義が変わる）を取得した（gap-stats/egov_online_rate.csv）が、系列なしのままにする。理由は3つ。国内にも国際にも比べる相手（比較群）がなく、日本の率だけでは差の差が作れない。2016年度以降は同じ定義で続く値が資料に無い。評価対象の6本のうち、施行が2005年の1本は開始前の値がなく、2016年以降の5本は開始後の値がない（開始前3年と開始後2年が要る）'),
  none('行政手続きの時間', '行政のデジタル化', '行政手続きの所要時間の公式系列がない'),
];

/**
 * field-expansion-v1 の新分野（docs/提案/分野の拡張-v1.md の3、承認項目 B1・B3・B4 の推奨）の指標。水道・廃棄物は作らない（B3）。
 * 国内は、その産業の実質付加価値（連鎖方式）対「合計」の指数（開始前最後の年=100）。基準ごとに候補を作り、つながない。GDP比は名目の産業÷「合計」。
 * 経済全体の指標（economy）は、独立に確かめられる系列を固定していないので置かない（労働力調査の就業者は産業の括りが SNA と一致しない行があり、採用後に決める）。
 * そのため判定は段階1までで、損失額は参考として出るだけになる。
 * 直接の語に当たった法律はその産業の指標そのまま、代理の語に当たった法律は「（代理）」付きの別の指標（reference）。
 */
const expansion = (indicator: string, field: string, key: SnaKey, label: string, match: '直接' | '代理', reason: string): Mapping => ({
  indicator: match === '代理' ? indicator + PROXY_SUFFIX : indicator, field, match,
  target: { definition: `${label}の実質付加価値指数と実質GDP指数（開始前最後の年=100）`, better: 'higher', options: snaVsGdp(key) },
  economy: null, share: snaShare(key), intl: null, reference: match === '代理',
  reason: `${reason}。国民経済計算の「${label}」を「合計」と比べる（高いほど良いとみなす。向きは機械的な仮定）。経済全体の指標は固定していないため段階1まで。国際比較は OECD 産業別付加価値（損失額の段階、loss-batch.ts）${match === '代理' ? '。代理：題名の語が法律の対象と産業の括りを直接には結ばないため、向きを決めない参考（上昇／低下）。合計に入れず、公開せず、議員への配分に使わない' : ''}`,
});
/** 新分野 → SNA の経済活動のキーと、指標名から「の付加価値」を除いた呼び方。 */
const EXPANSION_SNA: Record<NewField, SnaKey> = {
  '農林水産': 'agriculture', '建設': 'construction', '住宅・不動産': 'realEstate', '教育': 'education', '医療・福祉': 'health',
  '製造業': 'manufacturing', '商業': 'commerce', '専門サービス・研究開発': 'professional', '文化・娯楽・生活サービス': 'otherServices',
};
export const EXPANSION_MAP: Mapping[] = NEW_FIELDS.flatMap(field => {
  const { indicator, direct } = NEW_FIELD_WORDS[field];
  const label = indicator.replace(/の付加価値$/, ''), reason = `field-expansion-v1 の新分野「${field}」`;
  return [
    ...(direct.length ? [expansion(indicator, field, EXPANSION_SNA[field], label, '直接', reason)] : []),
    expansion(indicator, field, EXPANSION_SNA[field], label, '代理', reason),
  ];
});

/** triage の指標 → 取得済みの系列（既存8分野＋field-expansion-v1 の新分野）。 */
export const INDICATOR_MAP: Mapping[] = [...BASE_MAP, ...EXPANSION_MAP];

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
/** 開始日を含む期間の番号。暦年はその年、年度は4月始まり（1〜3月は前年度）。 */
export const startPeriod = (start: string, period: Period = 'calendar') =>
  period === 'fiscal' && Number(start.slice(5, 7)) < 4 ? startYear(start) - 1 : startYear(start);
/** 判定ルールが使う年：開始前5年（開始年の前年まで）と、開始年（1年目、除外される）から4年後（5年目）まで。年度の系列は年度で数える。 */
export const neededYears = (start: string, period: Period = 'calendar') => { const y = startPeriod(start, period); return Array.from({ length: 10 }, (_, i) => y - 5 + i); };
/** 期末日。暦年は12月31日、年度は翌年3月31日。判定ルールは期末日が開始日より前の期間を開始前とする。 */
export const asOfYear = (year: number, period: Period = 'calendar') => period === 'fiscal' ? `${year + 1}-03-31` : `${year}-12-31`;

/** 対象と比較の両方に値がある年。 */
const commonYears = (a: Map<number, number>, b: Map<number, number>) => [...a.keys()].filter(y => b.has(y)).sort((x, y) => x - y);

/**
 * 候補（基準年・分類の違うファイル）から1つ選ぶ。判定に必要な10年のうち両方に値がある年が最も多いもの、同数なら先に書いた（新しい）もの。
 * 基準の違う系列はつながない。
 */
export function chooseOption<T>(tables: Tables, start: string, options: T[], pick: (o: T) => [Ref, Ref], period: Period = 'calendar'): { option: T; a: Map<number, number>; b: Map<number, number>; coverage: number } | null {
  let best: { option: T; a: Map<number, number>; b: Map<number, number>; coverage: number } | null = null;
  const need = neededYears(start, period);
  for (const option of options) {
    const [ra, rb] = pick(option);
    const a = extractSeries(tables, ra), b = extractSeries(tables, rb);
    const coverage = need.filter(y => a.has(y) && b.has(y)).length;
    if (best === null || coverage > best.coverage) best = { option, a, b, coverage };
  }
  return best;
}

/** 開始前の最後の共通年を100にそろえた対象・比較の点列。開始前に共通年が無ければそろえずに返す（判定ルールが年数不足で保留にする）。 */
export function buildPairPoints(a: Map<number, number>, b: Map<number, number>, start: string, period: Period = 'calendar'): { points: ImpactPoint[]; baseYear: number | null } {
  const years = commonYears(a, b);
  const pre = years.filter(y => y < startPeriod(start, period));
  const baseYear = pre.length ? pre[pre.length - 1] : null;
  const scale = (m: Map<number, number>, y: number) => baseYear === null ? m.get(y)! : (m.get(y)! / m.get(baseYear)!) * 100;
  return { points: years.map(y => ({ asOf: asOfYear(y, period), treated: scale(a, y), control: scale(b, y) })), baseYear };
}

export function buildImpactSeries(tables: Tables, mapping: Mapping, start: string): { series: ImpactSeries; label: string; baseYear: number | null } | null {
  if (!mapping.target) return null;
  const period = mapping.target.period ?? 'calendar';
  const chosen = chooseOption(tables, start, mapping.target.options, o => [o.treated, o.control], period);
  if (!chosen || chosen.coverage === 0) return null;
  const { points, baseYear } = buildPairPoints(chosen.a, chosen.b, start, period);
  let economy: ImpactSeries['economy'] = null, economyLabel = '経済全体の指標なし';
  if (mapping.economy) {
    const ePeriod = mapping.economy.period ?? 'calendar';
    const e = chooseOption(tables, start, mapping.economy.options, o => [o.treated, o.control], ePeriod);
    if (e && e.coverage > 0) {
      economy = { definition: mapping.economy.definition, better: mapping.economy.better, points: buildPairPoints(e.a, e.b, start, ePeriod).points };
      economyLabel = `経済全体：${e.option.name}`;
    }
  }
  const sectorGdpShare = gdpShare(tables, mapping.share, start);
  const label = `${chosen.option.name}（${baseYear ?? '—'}${period === 'fiscal' ? '年度' : '年'}=100）／${economyLabel}／GDP比${sectorGdpShare === null ? 'なし' : sectorGdpShare.toFixed(4)}`;
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
  if (spec.source) {
    if (spec.ratio) throw new Error(`source のある国際系列では ratio を使えない: ${spec.code}`);
    const { file, countryColumn, where } = spec.source;
    const rows = tables.get(file);
    if (!rows) throw new Error(`未読込のファイル: ${file}`);
    const out = new Map<string, Map<number, number>>();
    for (const country of [...new Set(rows.filter(r => Object.entries(where).every(([k, v]) => r[k] === v)).map(r => r[countryColumn]))]) {
      out.set(country, extractSeries(tables, { file, where: { ...where, [countryColumn]: country } }));
    }
    return out;
  }
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
 * source と altSources のうち、日本の判定に必要な10年（開始前5年と開始後5年）の値を最も多く持つものを1つ選ぶ。同数なら先に書いたもの。
 * 候補が1つだけならそのまま返す。選ばれたものは source に入り、altSources は外れる。
 */
export function chooseIntlSpec(tables: Tables, spec: IntlSpec, start: string): IntlSpec {
  if (!spec.source || !spec.altSources?.length) return spec;
  const need = neededYears(start);
  let best = spec.source, bestCoverage = -1;
  for (const source of [spec.source, ...spec.altSources]) {
    const jp = intlByCountry(tables, { ...spec, source, altSources: undefined }).get('JPN');
    const coverage = jp ? need.filter(y => jp.has(y)).length : 0;
    if (coverage > bestCoverage) { best = source; bestCoverage = coverage; }
  }
  return { ...spec, source: best, altSources: undefined };
}

/**
 * 日本と比較国の点列。指数・金額は日本の開始前最後の年を全員100にそろえ、その年の値が無い国は外す。比率（%）はそろえない。
 */
export function buildCrossCountry(byCountry: Map<string, Map<number, number>>, spec: IntlSpec, start: string, treatedCountry = 'JPN') {
  const jp = byCountry.get(treatedCountry);
  if (!jp) return null;
  const pre = [...jp.keys()].filter(y => y < startYear(start)).sort((a, b) => a - b);
  // 日本に開始前の値が1つも無ければ比べられない（判定ではなく、データが無いという事実）。
  if (!pre.length) return null;
  const baseYear = spec.rebase ? pre[pre.length - 1] : null;
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
/** 向きを決めない（参考）指標は、貢献・悪影響ではなく、日本が比較国より上がったか下がったかだけを書く。 */
const refDirLabel = (d: 'benefit' | 'harm' | null) => d === null ? '' : d === 'benefit' ? '上昇' : '低下';

export function evaluateLaw(tables: Tables, law: Law, mappings: Mapping[] = INDICATOR_MAP): LawResult {
  const base = mappings.find(m => m.indicator === law.indicator);
  const blank = { series: '', verdict: '系列なし', direction: '', effect: null, spread: null, cross: '系列なし' };
  if (!base) return { ...law, ...blank, reason: `系列なし：指標「${law.indicator}」が対応表にない` };
  if (base.match === '系列なし') return { ...law, ...blank, reason: `系列なし：${base.reason}` };
  if (base.match === '比較群なし' && !base.intl) return { ...law, ...blank, verdict: '比較群なし', reason: `比較群なし：${base.reason}` };
  const mapping = resolveMapping(base, law);
  if (!mapping) return { ...law, ...blank, reason: `系列なし：題名が施設・交通機関をちょうど1つだけ名指していない（題名で系列を決める指標）／${base.reason}` };

  const reasons: string[] = [];
  const keep = mapping.keepVerdict;
  let result: Omit<LawResult, keyof Law | 'cross' | 'reason'> = { ...blank, verdict: mapping.match === '比較群なし' ? '比較群なし' : '国内系列なし' };
  if (mapping.target) {
    const built = buildImpactSeries(tables, mapping, law.start);
    if (!built) { result = { ...blank, verdict: keep ?? '保留' }; reasons.push('国内：期間が足りない（判定に必要な年に系列の値がない）'); }
    else {
      const j = judgeImpact(built.series);
      // 新しく配線した系列の開始が施行より後で、開始前が足りないときは、元の判定（系列なし）を保つ。
      const verdict = keep && j.stage === null && j.preYears < MIN_PRE_YEARS ? keep : stageLabel(j.stage);
      result = { series: built.label, verdict, direction: (mapping.reference ? refDirLabel : dirLabel)(j.direction), effect: j.effect, spread: j.spread };
      reasons.push(`国内：${j.preYears < 3 || j.effect === null ? '期間が足りない。' : ''}${j.reason}`);
    }
  } else if (mapping.match === '比較群なし') reasons.push(`比較群なし：国内に影響を受けない比較群がない。${mapping.reason}`);
  else reasons.push('国内：国内に比較群がない');

  let cross = '系列なし';
  if (mapping.intl) {
    const spec = chooseIntlSpec(tables, mapping.intl, law.start);
    const sourceNote = base.intl?.altSources?.length && spec.source?.name ? `、出所：${spec.source.name}` : '';
    const built = buildCrossCountry(intlByCountry(tables, spec), spec, law.start);
    const first = built ? Math.min(...built.treated.map(p => Number(p.asOf.slice(0, 4)))) : null;
    const jpPre = built ? Math.min(built.treated.filter(p => p.asOf < law.start).length, 5) : 0;
    if (!built) { cross = '保留'; reasons.push('国際：日本の開始前の値がない'); }
    else if (jpPre < MIN_PRE_YEARS) {
      cross = '保留';
      reasons.push(`国際（${spec.label}${sourceNote}）：日本の開始前の観測が${jpPre}年で、${MIN_PRE_YEARS}年に足りない（日本の系列は${first}年から）。元の判定を保つ`);
    } else {
      const j = judgeAcrossCountries({ definition: spec.label, start: law.start, better: spec.better, sectorGdpShare: null, treated: built.treated, controls: built.controls });
      const passed = j.countries.filter(c => c.passes).length;
      const label = spec.reference ? refDirLabel : dirLabel;
      cross = `${stageLabel(j.stage)}${j.direction ? '・' + label(j.direction) : ''}${spec.reference && j.direction ? '（参考：向きは決めない）' : ''}（比較国${built.controls.length}か国、条件を満たした国${passed}）`;
      reasons.push(`国際（${spec.label}${built.baseYear ? `、${built.baseYear}年=100` : ''}${sourceNote}）：${j.reason}`);
    }
    if (!result.series) result = { ...result, series: `国際：${spec.label}` };
  }
  if (mapping.reference) reasons.push('参考：代理の語に当たった法律なので、向きは決めず「上昇／低下」と書く（貢献・悪影響とは読まない）');
  if (mapping.match === '代理') reasons.push(`代理系列：${mapping.reason}`);
  const overlap = pandemicOverlap(law.start);
  if (overlap.length) reasons.push(`注意：判定に使う開始後2〜5年目（${startYear(law.start) + 1}〜${startYear(law.start) + 4}年）に新型コロナの${overlap.join('・')}年を含む。判定ルールは同時期の別の出来事を除かない`);
  return { ...law, ...result, cross, reason: reasons.join('／') };
}

export const IMPACT_HEADER = ['id', '題名', '分野', '指標', '施行日', '系列', '判定', '向き', '効果', 'ばらつき', '国際比較', '理由'];
export const impactRow = (r: LawResult) => [r.id, r.title, r.field, r.indicator, r.start, r.series, r.verdict, r.direction, r.effect, r.spread, r.cross, r.reason];

export const MAP_HEADER = ['指標', '分野', '対応', '国内_対象と比較（候補を優先順に）', '国内_向き', '向き（指標ごとの扱い）', '経済全体の指標（候補を優先順に）', 'GDP比（候補を優先順に）', '国際比較_指標コード', '国際比較_説明', '取得済みだが判定に使わない系列', '理由'];
/** 指標ごとの向きの扱い。国内の系列があればその向き、無ければ国際の向き。決められないものは「参考」（議員への配分に使わない）。 */
export const directionOf = (m: Mapping) => {
  if (m.match === '系列なし') return '';
  if (m.reference || m.intl?.reference) return '参考（向きは決めない。議員への配分に使わない）';
  const better = m.target?.better ?? (m.titleRules ? 'higher' : m.intl?.better);
  return better === undefined ? '' : better === 'higher' ? '高いほど良い' : '低いほど良い';
};
export const mapRow = (m: Mapping) => [
  m.indicator, m.field, m.match,
  m.target ? m.target.options.map(o => `${o.name}［${o.treated.file === o.control.file ? o.treated.file : `${o.treated.file} 対 ${o.control.file}`}］`).join('; ')
    : m.titleRules ? `題名がちょうど1つだけ含む語で決める: ${m.titleRules.map(r => `「${r.keyword}」→ ${r.name}［${r.ref.file}］`).join('; ')}（実質GDPと比べる。当たらない題名は系列なし）` : m.unused ? '国内では作らない（理由欄）' : '系列なし',
  m.target ? (m.target.better === 'higher' ? '高いほど良い' : '低いほど良い') : m.titleRules ? '高いほど良い' : '',
  directionOf(m),
  m.economy ? m.economy.options.map(o => `${o.name}［${o.treated.file}］`).join('; ') : '',
  m.share.map(o => o.name).join('; '),
  m.intl ? (m.intl.ratio ? `${m.intl.code} ÷ ${m.intl.ratio}` : m.intl.code) : '系列なし',
  m.intl ? `${m.intl.label}（${m.intl.reference ? '向きは決めない（参考）' : m.intl.better === 'higher' ? '高いほど良い' : '低いほど良い'}${m.intl.rebase ? '、日本の開始前最後の年=100' : '、比率のまま'}）${m.intl.source ? `［${[m.intl.source, ...(m.intl.altSources ?? [])].map(x => x.file + (x.name ? `：${x.name}` : '')).join(' ／ ')}］` : ''}` : '',
  m.unused ?? '',
  m.reason,
];
