/**
 * indicator-pick-v1：分野の中で指標を1つ選ぶ固定の順序（提案 docs/提案/指標の選び方-v1.md の 3）と、
 * 評価対象かどうかの固定ルール D1〜D5（同 4-4）を、そのままコードにしたもの。
 *
 * - 入力は「題名」と、各系統の AI が付けた「種類」「分野」だけ。第1条の原文・付託委員会・統計の値は読まない。
 * - 語の一致は、題名の文字列にその語がそのまま含まれるかだけで決める（意味の解釈をしない）。
 * - 分野は D1 により題名で最初に現れる語の分野へ決め直す。AI の入力分野は来歴として保持する。
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

/**
 * R4（2026-10-18、額の大きい法律の点検）：金融の既定を「貸出残高」から金融・保険業の付加価値に改める。貸出残高は題名に貸出の語（F3）があるときだけ。
 * この指標は影響の表に無いので影響は「系列なし」になり、全体指標の参考の額（macro-v1）で金融・保険業（ISIC K）の付加価値を使う。
 */
export const FINANCE_VALUE_ADDED = '金融・保険業の付加価値';

/** 提案 3 の表。上の行から順に見て、題名に最初に当たった行の指標を選ぶ。 */
export const PICK_TABLES: Record<Field, PickTable> = {
  '金融': { rules: [
    { id: 'F1', words: ['預金保険', '貯金保険', '破綻', '不良債権', '早期健全化', '金融機能', '債権債務の処理', '債権管理回収', '債権の管理'], indicator: '不良債権比率' },
    { id: 'F2', words: ['倒産', '再生', '更生手続', '信用保険', '信用保証'], indicator: '企業倒産件数' },
    { id: 'F3', words: ['貸付', '融資', '政策金融', '公庫', '金庫', '政策投資'], indicator: '貸出残高' },
  ], default: FINANCE_VALUE_ADDED },
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
 * 全分野の語のうち題名の最初の位置で分野を決め、語が無ければ対応表なし。「脱炭素」「温室効果ガス」「資源循環」「環境」は含めない。
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

/**
 * field-expansion-v1（docs/提案/分野の拡張-v1.md の3）の新分野。既存8分野の語が題名に1つも無いときだけ当てる（既存優先）。
 * 水道・廃棄物は承認項目 B3 の推奨に従い作らない。直接の語は指標名そのまま、代理の語に当たったときは「（代理）」付きの別の指標にする
 * （代理は参考扱い：合計に入れず、公開せず、議員への配分に使わない）。scripts/triage_v2_line2.py は同じ文書から別に書き起こした実装。
 */
export const NEW_FIELD_WORDS = {
  '農林水産': { indicator: '農林水産業の付加価値', direct: ['農業', '農地', '農林', '林業', '森林', '水産', '漁業', '漁船', '漁港', '漁場', '畜産', '家畜', '酪農', '農産物', '農薬', '肥料', '種苗', '農協', '農業協同組合', '森林組合', '漁業協同組合', '植物防疫', '米穀', '木材', '農村', '牧野', '農作物', '原料乳', 'お茶', '花き', '真珠', '棚田', '土地改良', '養殖', '養ほう', '野菜', '生産調整', '国有林野', '農山漁村', '農住', '農産加工'],
    proxy: ['食料', '食糧', '飼料'] },
  '建設': { indicator: '建設業の付加価値', direct: ['建設', '建築', '公共工事', '工事', '測量'],
    proxy: ['都市計画', '都市再生', '都市再開発', '市街地', '区画整理', '宅地造成', '耐震', '国土強靱化', '国土形成', '公共施設', '無電柱化', '基盤整備', '河川', '海岸', '砂防', '景観', '歴史的風致', '首都圏整備', '津波防災地域'] },
  '住宅・不動産': { indicator: '不動産業の付加価値', direct: [],
    proxy: ['住宅', '不動産', '賃貸', '借地', '借家', '宅地建物', 'マンション', '区分所有', '土地基本', '土地収用', '建物', '居住', '地価', '空家', '住生活'] },
  '教育': { indicator: '教育の付加価値', direct: [],
    proxy: ['教育', '学校', '大学', '義務教育', '奨学', '学習', '教職員', '幼稚園', '就学', '学級', '教科用', '留学', '育英'] },
  '医療・福祉': { indicator: '保健衛生・社会事業の付加価値', direct: [],
    proxy: ['医療', '健康保険', '医師', '歯科', '薬事', '医薬', '薬剤師', '薬局', '看護', '介護', '福祉', '保健', '健康増進', '感染症の予防', '予防接種', '精神保健', '老人', '母子', '難病', '臓器', '献血', '血液', '保育', '子育て', '児童福祉', '障害福祉', '障害者総合支援', '障害児', '児童虐待', '医薬品', '診療', '病院', '原子爆弾被爆者', '結核', '検疫', '狂犬病', '社会福祉', '栄養', '生活衛生', '母体', 'あん摩', '柔道整復', '臨床', '移植', '造血幹細胞', '死因究明', 'アレルギー', 'インフルエンザ', '自殺対策', '障害者自立支援', '障害者の日常生活', 'がん対策', 'がん登録', '肝炎', '循環器病', '公認心理師', '高齢者虐待', '次世代育成', '子どもの貧困', '生活困窮者'] },
  '製造業': { indicator: '製造業の付加価値', direct: ['製造', '工業', '鉱工業', '工場', '繊維', '化学物質', '計量', '産業標準', '火薬', '高圧ガス'],
    proxy: ['容器包装', '再商品化', '食品', 'たばこ', '電気用品', '消費生活用', '企業立地', '産業集積', '伝統的工芸品', 'アルコール', '酒類'] },
  '商業': { indicator: '卸売・小売業の付加価値', direct: ['小売', '卸売', '商店街', '商業', '流通', '古物', '質屋'],
    proxy: ['訪問販売', '特定商取引', '販売', '中心市街地', '景品', '表示'] },
  '専門サービス・研究開発': { indicator: '専門・科学技術、業務支援サービス業の付加価値', direct: ['弁護士', '司法書士', '行政書士', '税理士', '公認会計士', '弁理士', '社会保険労務士', '土地家屋調査士', '建築士', '技術士', '不動産鑑定', '警備業', '探偵', '研究開発', '試験研究', '科学技術', '研究所', '研究施設', '産業技術'],
    proxy: ['特許', '実用新案', '意匠', '商標', '知的財産', '著作権'] },
  '文化・娯楽・生活サービス': { indicator: 'その他のサービス業の付加価値', direct: [],
    proxy: ['文化', '芸術', '文化財', 'スポーツ', '体育', '競馬', '自転車競技', '小型自動車競走', 'モーターボート競走', '興行', '遊技', '風俗', '公衆浴場', '宗教', '映画', '博物館', '図書館', '劇場', 'オリンピック', '万国博覧会', '博覧会', '墓地', '理容', '美容', 'クリーニング', '美術', '競技大会', '温泉'] },
} as const satisfies Record<string, { indicator: string; direct: readonly string[]; proxy: readonly string[] }>;
export type NewField = keyof typeof NEW_FIELD_WORDS;
export const NEW_FIELDS = Object.keys(NEW_FIELD_WORDS) as NewField[];
export const PROXY_SUFFIX = '（代理）';
export type WordMatch = '直接' | '代理';
/** 新分野の指標。直接の語は指標名そのまま、代理の語は「（代理）」付き。 */
export const newIndicator = (field: NewField, match: WordMatch) => NEW_FIELD_WORDS[field].indicator + (match === '代理' ? PROXY_SUFFIX : '');

/** D2：設置法・整備法を含む題名は、題名の最初の法律で決める。「…及び法務省設置法の一部を…」の「及び法務省設置法」を除く。 */
export function firstLawTitle(title: string): string {
  return title.replace(/及び[^及]*(設置法|整備法)/g, '');
}

/**
 * R1（2026-10-18、額の大きい法律の点検）：語の境界。語が、ここに挙げた複合語の一部として題名に現れたところは当たりにしない
 * （「国民健康保険」の「保険」、「財政投融資」の「融資」、「農産加工業」の「工業」など）。scripts/triage_v2_line2.py にも同じ表があり、
 * tests/test_triage_v2.py が2つの表が同じことを確かめる。
 */
export const WORD_EXCLUSIONS: Record<string, string[]> = {
  '保険': ['健康保険', '社会保険', '介護保険', '雇用保険', '保険医'],
  '融資': ['財政投融資'],
  '金融': ['資金融通', '国際金融公社'],
  '銀行': ['国際復興開発銀行', 'アジア開発銀行', '米州開発銀行', 'アフリカ開発銀行', '欧州復興開発銀行', 'アジアインフラ投資銀行'],
  '工業': ['加工業'],
  '報酬': ['診療報酬'],
  '災害': ['海上災害'],
};

/** 題名で語が最初に現れる位置。除外表の複合語の一部として現れたところは飛ばす。無ければ -1。 */
export function findWord(text: string, word: string): number {
  const compounds = WORD_EXCLUSIONS[word] ?? [];
  for (let pos = text.indexOf(word); pos >= 0; pos = text.indexOf(word, pos + 1)) {
    const inside = compounds.some(c => {
      for (let q = text.indexOf(c); q >= 0; q = text.indexOf(c, q + 1)) if (q <= pos && pos + word.length <= q + c.length) return true;
      return false;
    });
    if (!inside) return pos;
  }
  return -1;
}

const matchedWord = (text: string, words: string[]): string | null => words.find(w => findWord(text, w) >= 0) ?? null;

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
/** HR2（v2.1）：「…機構法等の一部を改正する法律案」（他の法律との同時改正）も D4 と同じく実質改正に直す。 */
const AMEND_CORPORATION_ETC = /(機構|公庫|公団|事業団|基金|銀行|金庫)法等の一部を改正する法律案$/;

/**
 * 同じ位置に別々の分野の語が重なったときの解消（HR1・v2.1）。他の語の一部になっている短い語（「電子」と「電子消費者契約」、「再生」と「再生可能」）を除き、
 * 残った語の分野が1つならその分野を採る。残りが複数分野（同じ長さの別の語など）なら解けないので保留（D5）で、競合した分野と語を理由に残す。
 */
export function resolveTie<T extends { field: string; word: string }>(at: T[]):
  { kind: 'hit'; hit: T } | { kind: 'hold'; reason: string } {
  const top = at.filter(hit => !at.some(g => g.word !== hit.word && g.word.includes(hit.word)));
  if (new Set(top.map(hit => hit.field)).size > 1) {
    const list = [...new Set(top.map(hit => `${hit.field}「${hit.word}」`))].join('／');
    return { kind: 'hold', reason: `D5：最初の語の位置で複数の分野が競合し、他の語の一部でない語が複数の分野に残るため保留（${list}）` };
  }
  return { kind: 'hit', hit: top.reduce((a, b) => (b.word.length > a.word.length ? b : a)) };
}

export type TriageInput = { title: string; kind: string; field: string };
export type TriageOutput = {
  kind: string; field: string; indicator: string; verdict: '評価対象' | '評価対象外' | '保留';
  /** 当てた規則（D1〜D5、指標の行）。 */
  rules: string[];
  reason: string;
};

/**
 * 1本分の振り分け。AI の種類・分野を来歴として受け、D1 で分野を決め直し D2〜D5 と指標の表を当てる。
 * D5：種類か分野が定義にない値（迷い・空）なら、評価対象外にも評価対象にもせず保留。
 */
export function triageV2(input: TriageInput): TriageOutput {
  const rules: string[] = [];
  const notes: string[] = [];
  let { kind, field } = input;
  if (!(KINDS as readonly string[]).includes(kind) || !([...FIELDS, ...NEW_FIELDS, NO_FIELD] as string[]).includes(field)) {
    return { kind, field, indicator: '', verdict: '保留', rules: ['D5'], reason: `D5：種類「${kind}」・分野「${field}」が定義にない値のため保留` };
  }
  const seg = firstLawTitle(input.title);
  if (seg !== input.title) { rules.push('D2'); notes.push('D2：題名の最初の法律で決める'); }
  // D3・D4：組織手続を直す
  if (kind === '組織手続' && !input.title.includes('設置法')) {
    if (NEW_CORPORATION.test(seg)) { kind = '新規'; rules.push('D3'); notes.push('D3：新設法人の根拠法は新規'); }
    else if (AMEND_CORPORATION.test(seg)) { kind = '実質改正'; rules.push('D4'); notes.push('D4：機構法などの改正は実質改正'); }
    else if (AMEND_CORPORATION_ETC.test(seg)) { kind = '実質改正'; rules.push('HR2'); notes.push('HR2（v2.1）：機構法等の一部改正はD4と同じく実質改正'); }
  }
  // D1：全分野の語を探し、題名の最初の位置の分野を採用する。
  const hits = FIELDS.flatMap(f => FIELD_WORDS[f].map(word => ({ field: f, word, pos: findWord(seg, word) })))
    .filter(hit => hit.pos >= 0).sort((a, b) => a.pos - b.pos);
  let first: (typeof hits)[number] | undefined = hits[0];
  if (first) {
    const at = hits.filter(hit => hit.pos === first!.pos);
    if (at.some(hit => hit.field !== first!.field)) {
      const tie = resolveTie(at);
      if (tie.kind === 'hold') return { kind, field: '', indicator: '', verdict: '保留', rules: [...rules, 'D5'], reason: tie.reason };
      first = tie.hit; rules.push('HR1'); notes.push(`HR1（v2.1）：最初の位置で競合した語のうち、他の語の一部でない最長の語「${tie.hit.word}」の分野`);
    }
  }
  let newMatch: WordMatch | null = null;
  let firstWord = first?.word ?? '';
  // 新分野の語。R3（2026-10-18）：既存8分野の語が無いときに加え、新分野の語が既存8分野の語より題名の先にあるときも新分野を当てる（同じ位置なら既存優先）。
  // 同じ位置の語が別の語の一部なら長い語を採り、別々の分野の語が重なれば保留（D5）。
  const nh = NEW_FIELDS.flatMap(f => (['直接', '代理'] as const).flatMap(match =>
    (match === '直接' ? NEW_FIELD_WORDS[f].direct : NEW_FIELD_WORDS[f].proxy).map(word => ({ field: f, word, match, pos: findWord(seg, word) }))))
    .filter(hit => hit.pos >= 0);
  const newPos = nh.length ? Math.min(...nh.map(hit => hit.pos)) : -1;
  if (first && newPos >= 0 && newPos < first.pos) {
    rules.push('R3'); notes.push(`R3：新分野の語が既存8分野の語「${first.word}」より題名の先にある`);
    first = undefined;
  }
  if (!first) {
    if (nh.length) {
      const pos = newPos;
      const at = nh.filter(hit => hit.pos === pos);
      const tie = resolveTie(at);
      if (tie.kind === 'hold') return { kind, field: '', indicator: '', verdict: '保留', rules: [...rules, 'D5'], reason: tie.reason };
      const best = tie.hit;
      field = best.field; newMatch = best.match; firstWord = best.word;
    }
  } else field = first.field;
  if (!first && newMatch === null) field = NO_FIELD;
  rules.push('D1');
  notes.push(firstWord ? `D1：題名で最初の語「${firstWord}」の分野` : 'D1：題名に8分野の語が無い');
  let indicator = '';
  if (newMatch !== null) {
    indicator = newIndicator(field as NewField, newMatch);
    const sign = `${field}${newMatch}`;
    rules.push(sign);
    notes.push(`${sign}（語「${firstWord}」）`);
  } else if (field !== NO_FIELD) {
    const p = pickIndicator(field as Field, seg);
    indicator = p.indicator;
    rules.push(p.rule);
    notes.push(p.word ? `${p.rule}（語「${p.word}」）` : `${p.rule}`);
  }
  const verdict = field === NO_FIELD || kind === '定型改正' || kind === '組織手続' ? '評価対象外' : '評価対象';
  return { kind, field, indicator, verdict, rules, reason: `${verdict}（${kind}・${field}${indicator ? '・' + indicator : ''}）／${notes.join('、')}` };
}
