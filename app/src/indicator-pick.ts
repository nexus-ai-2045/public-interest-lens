/**
 * indicator-pick-v1：分野の中で指標を1つ選ぶ固定の順序（提案 docs/提案/指標の選び方-v1.md の 3）と、
 * 評価対象かどうかの固定ルール D1〜D5（同 4-4）を、そのままコードにしたもの。
 *
 * - 入力は「題名」と、各系統の AI が付けた「種類」「分野」だけ。第1条の原文・付託委員会・統計の値は読まない。
 * - 語の一致は、題名の文字列にその語がそのまま含まれるかだけで決める（意味の解釈をしない）。
 * - 分野の割り当ては AI の判断のまま（D1 は「題名に8分野のどの語も無いのに8分野と付けた」ときだけ対応表なしに直す）。
 *   種類も AI の判断のままだが、D3・D4 で組織手続を直す。
 * - 純関数。系統1と系統2の両方がこの同じ規則を当てる（scripts/triage_v2_line2.py は同じ文書から別に書き起こした実装で、
 *   tests/test_triage_v2.py が全題名でこの実装と出力が同じことを確かめる）。
 * - 規則は、2系統の食い違い28本を見たあとで作ったので、170本での確認は学習内（in-sample）。
 */

export const TRIAGE_VERSION = 'bill-triage-v2';

export const KINDS = ['新規', '実質改正', '定型改正', '組織手続'] as const;
export const FIELDS = ['金融', '交通・移動', '宿泊・観光', '通信・ネット', '半導体・電子', 'エネルギー', '労働市場', '行政のデジタル化'] as const;
export const NO_FIELD = '対応表なし';
export type Field = (typeof FIELDS)[number];

export type PickRule = { id: string; words: string[]; indicator: string };
export type PickTable = { rules: PickRule[]; default: string };

/** 提案 3 の表。上の行から順に見て、題名に最初に当たった行の指標を選ぶ。 */
export const PICK_TABLES: Record<Field, PickTable> = {
  '金融': { rules: [
    { id: 'F1', words: ['預金保険', '貯金保険', '破綻', '不良債権', '早期健全化', '金融機能', '債権債務の処理', '債権管理回収', '債権の管理'], indicator: '不良債権比率' },
    { id: 'F2', words: ['倒産', '再生', '更生手続', '信用保険', '信用保証'], indicator: '企業倒産件数' },
  ], default: '貸出残高' },
  '交通・移動': { rules: [
    { id: 'T1', words: ['運転者', '乗務員', '船員', '従事者', '労働時間'], indicator: '就業者数' },
    { id: 'T2', words: ['運送事業', '運送法', '事業法', '事業の適正化', '鉄道株式会社'], indicator: '旅客輸送の付加価値' },
    { id: 'T3', words: ['空港', '港湾', '道路', '新幹線', '鉄道', '整備', '施設'], indicator: '利用件数' },
  ], default: '利用件数' },
  '宿泊・観光': { rules: [
    { id: 'H1', words: ['旅館', 'ホテル', '宿泊施設'], indicator: '客室数' },
    { id: 'H2', words: ['宿泊業'], indicator: '宿泊業の付加価値' },
  ], default: '宿泊者数' },
  '通信・ネット': { rules: [
    { id: 'C1', words: ['ブロードバンド', '光ファイバ', '高度情報通信', 'ネットワーク', '基盤の整備'], indicator: 'ブロードバンド普及率' },
    { id: 'C2', words: ['電子商取引', '電子消費者契約', '電子承諾', 'インターネット上', 'プラットフォーム'], indicator: 'ネット企業の時価総額' },
  ], default: '通信業の付加価値' },
  '半導体・電子': { rules: [
    { id: 'S1', words: ['輸出', '国際競争力'], indicator: '世界輸出シェア' },
  ], default: '生産額' },
  'エネルギー': { rules: [
    { id: 'G1', words: ['省エネルギー', 'エネルギーの使用の合理化', '消費性能'], indicator: 'エネルギー効率' },
    { id: 'G2', words: ['再生可能', '原子力', '原子炉', '核燃料', '電源', '水素', 'アンモニア', '発電'], indicator: '発電構成' },
  ], default: '電力価格' },
  '労働市場': { rules: [
    { id: 'L1', words: ['賃金', '給与', '報酬', '待遇', '労働基準', '労働時間'], indicator: '賃金' },
    { id: 'L2', words: ['職業能力開発', '労働安全', '衛生', '作業環境', '過労', '災害'], indicator: '労働生産性' },
    { id: 'L3', words: ['職業訓練', '就職', '求職', '職業安定', '派遣'], indicator: '雇用の流動性' },
  ], default: '雇用の流動性' },
  '行政のデジタル化': { rules: [
    { id: 'E1', words: ['電子', 'オンライン', 'デジタル', '情報システム', '情報通信技術'], indicator: '電子申請率' },
    { id: 'E2', words: ['簡素', '迅速', '負担軽減', '手続の時間'], indicator: '行政手続きの時間' },
  ], default: '電子申請率' },
};

/**
 * D1：分野を決める題名の語（`data/derived/bill-triage-v1-line2/criteria.md` の2の表の語に、PICK_TABLES の語を足したもの）。
 * 題名にこの語が1つも無いのに8分野と付けられていれば、対応表なしに直す。「脱炭素」「温室効果ガス」「資源循環」「環境」は含めない。
 * 末尾の語（社債・振替・割賦・信託・ツーリズム・交通・移動・データ活用）は、一致していた142本が誤って対応表なしにならないよう
 * 170本を見て足した語（学習内）。
 */
export const FIELD_WORDS: Record<Field, string[]> = {
  '金融': ['銀行', '金庫', '金融', '保険', '証券', '預金', '貯金', '貸金', '融資', '信用保証', '資産の流動化', '公庫', '政策投資', '破綻', '不良債権', '早期健全化', '債権債務の処理', '債権管理回収', '債権の管理', '倒産', '再生', '更生手続', '信用組合', '協同組織', '貸付',
    '社債', '振替', '割賦', '信託'],
  '交通・移動': ['鉄道', '道路', '自動車', '航空', '空港', '港湾', '船舶', '海上運送', '運送', '運転者', '乗務員', '船員', '従事者', '新幹線', '旅客',
    '交通', '移動'],
  '宿泊・観光': ['観光', '旅行業', '通訳案内', '宿泊', '旅館', 'ホテル', 'ツーリズム'],
  '通信・ネット': ['電気通信', '電波', '放送', '郵便', '通信', 'インターネット', 'サイバーセキュリティ', '電話', 'ブロードバンド', '光ファイバ', 'ネットワーク', '電子商取引', '電子消費者契約', '電子承諾', 'プラットフォーム'],
  '半導体・電子': ['半導体', '電子部品', '情報処理'],
  'エネルギー': ['電気事業', 'ガス事業', '石油', '原子力', '原子炉', '核燃料', '再生可能', 'エネルギー', '電源', '水素', 'アンモニア', '発電'],
  '労働市場': ['労働', '雇用', '賃金', '給与', '報酬', '待遇', '職業', '就職', '求職', '派遣', '過労', '災害', '作業環境', '衛生'],
  '行政のデジタル化': ['電子', 'オンライン', 'デジタル', '情報システム', '情報通信技術', '行政手続', '手続',
    'データ活用'],
};

/** D2：設置法・整備法を含む題名は、題名の最初の法律で決める。「…及び法務省設置法の一部を…」の「及び法務省設置法」を除く。 */
export function firstLawTitle(title: string): string {
  return title.replace(/及び[^及]*(設置法|整備法)/g, '');
}

const matchedWord = (text: string, words: string[]): string | null => words.find(w => text.includes(w)) ?? null;

export type Pick = { indicator: string; rule: string; word: string };

/** 提案 3：分野の表を上から順に見て、題名に最初に当たった行の指標。当たらなければ既定。 */
export function pickIndicator(field: Field, title: string): Pick {
  const table = PICK_TABLES[field];
  for (const rule of table.rules) {
    const word = matchedWord(title, rule.words);
    if (word !== null) return { indicator: rule.indicator, rule: `${field}${rule.id}`, word };
  }
  return { indicator: table.default, rule: `${field}既定`, word: '' };
}

/** D3：新しい法人を作る根拠法（「…機構法案」「…公庫法案」など。一部改正ではない）。 */
const NEW_CORPORATION = /(機構|公庫|公団|事業団|基金|銀行|金庫)法案$/;
/** D4：既存の機構法などの改正（題名が「…機構法の一部を改正する法律案」だけ）。 */
const AMEND_CORPORATION = /(機構|公庫|公団|事業団|基金|銀行|金庫)法の一部を改正する法律案$/;

export type TriageInput = { title: string; kind: string; field: string };
export type TriageOutput = {
  kind: string; field: string; indicator: string; verdict: '評価対象' | '評価対象外' | '保留';
  /** 当てた規則（D1〜D5、指標の行）。 */
  rules: string[];
  reason: string;
};

/**
 * 1本分の振り分け。種類・分野は各系統の AI の判断を入力にし、D1〜D5 と指標の表で直す。
 * D5：種類か分野が定義にない値（迷い・空）なら、評価対象外にも評価対象にもせず保留。
 */
export function triageV2(input: TriageInput): TriageOutput {
  const rules: string[] = [];
  const notes: string[] = [];
  let { kind, field } = input;
  if (!(KINDS as readonly string[]).includes(kind) || !([...FIELDS, NO_FIELD] as string[]).includes(field)) {
    return { kind, field, indicator: '', verdict: '保留', rules: ['D5'], reason: `D5：種類「${kind}」・分野「${field}」が定義にない値のため保留` };
  }
  const seg = firstLawTitle(input.title);
  if (seg !== input.title) { rules.push('D2'); notes.push('D2：題名の最初の法律で決める'); }
  // D3・D4：組織手続を直す
  if (kind === '組織手続' && !input.title.includes('設置法')) {
    if (NEW_CORPORATION.test(seg)) { kind = '新規'; rules.push('D3'); notes.push('D3：新設法人の根拠法は新規'); }
    else if (AMEND_CORPORATION.test(seg)) { kind = '実質改正'; rules.push('D4'); notes.push('D4：機構法などの改正は実質改正'); }
  }
  // D1：8分野と付けられていても、題名に8分野の語が1つも無ければ対応表なし
  if (field !== NO_FIELD) {
    const hit = (FIELDS as readonly string[]).some(f => matchedWord(seg, FIELD_WORDS[f as Field]) !== null);
    if (!hit) { field = NO_FIELD; rules.push('D1'); notes.push('D1：題名に8分野の語が無い'); }
  }
  let indicator = '';
  if (field !== NO_FIELD) {
    const p = pickIndicator(field as Field, seg);
    indicator = p.indicator;
    rules.push(p.rule);
    notes.push(p.word ? `${p.rule}（語「${p.word}」）` : `${p.rule}`);
  }
  const verdict = field === NO_FIELD || kind === '定型改正' || kind === '組織手続' ? '評価対象外' : '評価対象';
  return { kind, field, indicator, verdict, rules, reason: `${verdict}（${kind}・${field}${indicator ? '・' + indicator : ''}）／${notes.join('、')}` };
}
