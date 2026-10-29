/**
 * 計算方法の仕様（設計決定0013）の式の正本。
 * /methodology の数式（KaTeX）と docs/計算式.md（scripts/build_formula_doc.mjs が作る）は、どちらもここから作る。
 * 式を変えるときは、ここの版を上げ、設計決定0013 の「変更の記録」に理由と影響（上位がどう動くか）を足す。
 * コードの計算そのものは各ルールのファイル（impact-rule.ts など）にあり、ここは読むための清書です。式とコードの対応は code に書く。
 */

/** 仕様全体の版。部品の版が1つでも変われば上げる。 */
export const SPEC_VERSION = 'method-spec-v2.3';
export const SPEC_DATE = '2026-10-29';

export type SpecStatus = '採用' | '案';
export type SpecFormula = { tex: string; note?: string };
export type SpecSection = {
  id: string;
  title: string;
  /** 部品の版（公開データの rules と同じ名前）。 */
  version: string;
  /** 同じ部品の中で公開データに出る別名の版（members-reference.json の rules など）。 */
  alsoVersions?: string[];
  status: SpecStatus;
  /** 式を実装しているファイル。 */
  code: string[];
  lead: string;
  formulas: SpecFormula[];
  /** 記号の定義。 */
  symbols: [string, string][];
  /** 式の外の決まり（しきい値・除外・保留の条件）。 */
  rules: string[];
};

/** 計算に使っている定番の手法（method-spec-v2.2 で6本に絞った。これ以外の独自の式は使わない）。 */
export type StandardMethod = { name: string; use: string; refs: string[]; sections: string[] };
export const STANDARD_METHODS: StandardMethod[] = [
  { name: '差の差', use: '法律の前後で、日本と比較国の差がどう変わったか', refs: ['Angrist & Pischke, Mostly Harmless Econometrics (2009), ch. 5'], sections: ['impact', 'loss', 'macro'] },
  { name: '合成対照と置換検定', use: '差が偶然の範囲かどうか（置換検定の順位で確かさを決める）', refs: ['Abadie, Diamond & Hainmueller (2010), Journal of the American Statistical Association 105(490)'], sections: ['cause-axis'] },
  { name: '費用便益分析', use: '規制の便益を公的な単価で円にし、損失から差し引く。税や交付金などの移転は数えない', refs: ['Boardman et al., Cost-Benefit Analysis: Concepts and Practice', '国土交通省「公共事業評価の費用便益分析に関する技術指針」'], sections: ['benefit', 'covid'] },
  { name: 'シャープレイ＝シュービック投票力指数', use: '1票が法律の成立にどれだけ効いたか', refs: ['Shapley & Shubik (1954), American Political Science Review 48(3)'], sections: ['allocation-v0', 'allocation-v1', 'reference-members'] },
  { name: '実質化（GDP デフレーター）', use: '違う年の円を、同じ年の円にそろえる', refs: ['United Nations et al., System of National Accounts 2008, ch. 15'], sections: ['price'] },
  { name: '成長会計', use: '差を、働く人の数・資本・生産性の分に分ける', refs: ['Solow (1957), Review of Economics and Statistics 39(3)', 'OECD, Measuring Productivity (2001)'], sections: ['cause-axis'] },
];

export const SPEC_SECTIONS: SpecSection[] = [
  {
    id: 'triage',
    title: '振り分け（どの法律を、どの分野・指標で測るか）',
    version: 'bill-triage-v2',
    status: '採用',
    code: ['app/src/indicator-pick.ts（系統1）', 'scripts/triage_v2_line2.py（系統2）', 'data/derived/bill-triage-v2/spec.md'],
    lead: '題名から分野と指標を固定の規則で決めます。独立に書いた2つの実装（TypeScript と Python）が一致した行だけを採用します。',
    formulas: [
      { tex: '\\text{採用}(i) \\iff f_1(i) = f_2(i) \\ne \\text{保留}', note: 'f₁・f₂ は2系統の（判定・分野・指標）の組' },
    ],
    symbols: [['f_1,\\ f_2', '系統1（TypeScript）と系統2（Python）の振り分けの結果']],
    rules: ['分野は題名の最初の位置に出る語で決める（D1〜D5、解消規則 HR1〜HR4）。第1条・委員会・統計値は分野の選択に使わない。', '一致しない行は影響の判定に進めない。'],
  },
  {
    id: 'impact',
    title: '影響の段階（貢献か悪影響か、どこまで確かか）',
    version: 'impact-rule-v1',
    status: '採用',
    code: ['app/src/impact-rule.ts'],
    lead: '施行の前後で、日本の指標と比較の差がどれだけ動いたかを測り、ばらつきより大きく続いた差だけに段階を付けます。',
    formulas: [
      { tex: 'd_t = x^{\\mathrm{JP}}_t - x^{\\mathrm{C}}_t', note: '各年の差（対象−比較）' },
      { tex: '\\Delta = \\frac{1}{|Q|}\\sum_{t\\in Q} d_t \\; - \\; \\frac{1}{|P|}\\sum_{t\\in P} d_t, \\qquad \\sigma = \\operatorname{sd}_{t\\in P}(d_t)', note: '効果とばらつき' },
      { tex: '\\text{段階1} \\iff |\\Delta| > 2\\sigma \\;\\wedge\\; \\max \\text{連続}\\{t\\in Q : \\operatorname{sgn}(d_t-\\bar d_P)=\\operatorname{sgn}\\Delta\\} \\ge 2' },
      { tex: '\\text{段階2} \\iff \\text{段階1} \\;\\wedge\\; \\text{経済全体の指標でも段階1と同じ向き}' },
      { tex: 'r = \\frac{1}{|Q|}\\sum_{t\\in Q}\\bigl(d_t - \\hat d_t\\bigr),\\quad \\hat d_t = \\bar d_P + \\beta\\,(t-\\bar t_P);\\qquad \\text{段階3} \\iff \\text{段階2} \\wedge \\operatorname{sgn} r=\\operatorname{sgn}\\Delta \\wedge |r|>2\\sigma \\wedge s_k \\ge 0.01', note: 'β は開始前の差に当てた直線の傾き' },
      { tex: '\\text{向き} = \\begin{cases}\\text{貢献} & (\\Delta<0) = (\\text{低いほど良い})\\\\ \\text{悪影響} & \\text{それ以外}\\end{cases}' },
    ],
    symbols: [
      ['x^{\\mathrm{JP}}_t,\\ x^{\\mathrm{C}}_t', '年 t の日本の指標と比較の指標（同じ定義の系列。定義の違う系列はつながない）'],
      ['P', '開始前の観測（最後の5年まで、3年以上必要）'],
      ['Q', '開始後2〜5年目の観測（1年目は立ち上がりとして除く。2年以上必要）'],
      ['s_k', '対象の産業 k の付加価値の GDP 比'],
    ],
    rules: [
      '国際比較では比較国ごとに同じ判定をし、比較国が3か国以上、そのうち ⌈2n/3⌉ か国以上で同じ向きの段階が出て、開始前の差の変化が効果の半分未満のときだけ段階を出す。段階は条件を満たした国の最低。',
      '条件を満たさないものは段階を作らず保留（0 で埋めない）。',
    ],
  },
  {
    id: 'loss',
    title: '損失額・便益額（反実仮想との差）',
    version: 'loss-rule-v1',
    status: '採用',
    code: ['app/src/loss-rule.ts', 'scripts/source_check.py（recompute：独立に同じ式で再計算）'],
    lead: '「その法律が無く、日本が比較国と同じ伸び方をしていたら」の付加価値を作り、実績との差を最大10年分足します。開始前から続いていた伸びの差は、政策の前からの動きとして反実仮想に織り込みます。',
    formulas: [
      { tex: 'g = \\frac{1}{L}\\ln\\frac{Y_b}{Y_f},\\qquad \\delta = g^{\\mathrm{JP}} - \\operatorname{med}_{c\\in C}\\, g^{c}', note: '開始前の年平均の伸び（対数）と、その差' },
      { tex: '\\hat Y^{(q)}_t = Y_b \\cdot \\mathcal{Q}_q\\!\\left(\\left\\{\\frac{X^{c}_t}{X^{c}_b}\\right\\}_{c\\in C}\\right) \\cdot e^{\\delta\\,(t-b)}', note: '反実仮想（比較国の伸びの分位 q）' },
      { tex: '\\mathrm{Loss}^{(q)} = \\sum_{t\\in T} \\frac{\\hat Y^{(q)}_t - Y_t}{Y_b}\\, N_b,\\qquad q\\in\\{0.25,\\ 0.5,\\ 0.75\\}', note: '累積の額（円）。正は失った額、負は得た額' },
      { tex: '\\text{幅} = \\bigl[\\mathrm{Loss}^{(0.25)},\\ \\mathrm{Loss}^{(0.75)}\\bigr],\\qquad \\text{中央値} = \\mathrm{Loss}^{(0.5)}' },
    ],
    symbols: [
      ['Y_t', '日本の対象産業の実質付加価値（OECD 表6 の連鎖方式の数量 LR。比で使うので単位は問わない）'],
      ['X^{c}_t', '比較国 c の同じ定義の系列'],
      ['b,\\ f,\\ L', '開始前最後の年、その4年前（観測が無ければ最古の開始前の年）、L = b − f'],
      ['T', '開始後の年（最大10年。2020年より前に始まる窓は2019年で切る）'],
      ['N_b', '年 b の日本の対象産業の名目付加価値（円）。金額への換算はこの1点だけ'],
      ['\\mathcal{Q}_q', '比較国の値の q 分位（線形補間）'],
    ],
    rules: [
      '額は影響の段階が1以上で、額の符号が段階の向きと一致するときだけ出す。段階1の額は確かさ「低」として印を付け、議員への配分にも使う（設計決定0014）。比較国は3か国以上。',
      '額の単位は「開始前最後の年の名目円」。同じ年の円にそろえた額は物価の換算（price-v1）で並べる。順位と議員の額は、換算に切り替えるまで名目円のまま（切り替えは版を上げ、上位の動きを記録する）。',
    ],
  },
  {
    id: 'price',
    title: '物価の換算（違う年の円をそろえる）',
    version: 'price-v1',
    status: '採用',
    code: ['scripts/build_price_index.py', 'app/src/price-index.ts'],
    lead: '額は法律ごとに「開始前の年の円」なので、そのままでは年の違う額を比べられません。日本の付加価値の物価（GDP デフレーター）で、最新年の円に直した額を横に並べます。',
    formulas: [
      { tex: 'P_t = 100\\,\\frac{N_t}{V_t}', note: '物価（2020年＝100）。N は名目、V は実質（2020年基準の連鎖）の日本の全産業の付加価値' },
      { tex: 'A^{(T)} = A^{(b)} \\cdot \\frac{P_T}{P_b}', note: '開始前の年 b の円の額を、最新年 T の円に直す' },
    ],
    symbols: [
      ['N_t,\\ V_t', 'OECD 表6 の日本の総付加価値（B1G）の名目と実質'],
      ['b,\\ T', '額の窓の開始前の年と、物価のある最新の年'],
    ],
    rules: [
      '物価の表は1994年から。b がそれより前の額は換算せず、名目円だけを出す。',
      '割り引き（現在価値）はしない。過去の額を割り戻す率に定番の決め方がなく、社会的割引率は将来の費用便益のためのものなので。',
    ],
  },
  {
    id: 'benefit',
    title: '規制の便益と純額',
    version: 'benefit-rule-v1.2',
    status: '採用',
    code: ['app/src/benefit-rule.ts'],
    lead: '安全・環境・消費者保護などの便益を、影響の段階と同じ判定で測り、公的機関の単価がある種類だけ円にして損失から差し引きます。',
    formulas: [
      { tex: '\\tilde x_t = 100\\,\\frac{x_t}{x_b}', note: '開始前最後の年を100にそろえる' },
      { tex: 'K = \\sum_{t\\in T} \\sigma\\,\\frac{(\\tilde x^{\\mathrm{C}}_t + \\bar g_P) - \\tilde x^{\\mathrm{JP}}_t}{100}\\, x^{\\mathrm{JP}}_b,\\qquad B = K\\cdot p', note: '防いだ件数と便益額。σ は低いほど良い指標で +1、高いほど良い指標で −1' },
      { tex: '\\mathrm{Net} = \\bigl[\\,L_{\\mathrm{low}} - B_{\\mathrm{high}},\\ \\ L_{\\mathrm{med}} - B_{\\mathrm{med}},\\ \\ L_{\\mathrm{high}} - B_{\\mathrm{low}}\\,\\bigr]', note: '純額の幅は厳しい側で組む' },
    ],
    symbols: [
      ['\\bar g_P', '開始前の指数の差の平均'],
      ['p', '公的機関が公表した1件あたりの単価（無い種類は「検出・未換算」で円にしない）'],
      ['B', '同じ系列を指す種類は1回だけ数える（二重計上の禁止）'],
    ],
    rules: [
      '公開の判定表 R1〜R6 を上から当て、最初に当たった行で決める。R5：純額の幅が0をまたげば向きが定まらないので保留。',
      '移転（税収・財源・交付金）は便益にも損失にも数えない。「検出されず」は便益0。',
      '貢献の側で、測った分の純額が既に便益の側なら、加算のみの未測定は止めず「下限」と印を付ける（v1.1）。',
    ],
  },
  {
    id: 'macro',
    title: '参考の額（全体指標・産業の付加価値）',
    version: 'macro-v1',
    status: '採用',
    code: ['scripts/build_macro_amounts.py'],
    lead: '影響の段階が付かなかった法律にも、分野の産業の付加価値で同じ式の額を付けます。確かさは「参考」で、全議員の参考の欄へ別に配分します。確かな額の議員順位には合算しません。',
    formulas: [
      { tex: '\\mathrm{Loss}^{(q)}_i = \\mathrm{Loss}^{(q)}\\bigl(Y = \\text{産業 } k(i) \\text{ の付加価値},\\ s = \\text{施行日}_i\\bigr)', note: '式は損失額と同じ' },
      { tex: 'k(i) = \\text{振り分けの分野} \\;\\to\\; \\text{AI 2系統の分野} \\;\\to\\; \\text{全産業}', note: 'この順で最初に決まったもの。同じ元の題名の改正は最多の産業にそろえる' },
    ],
    symbols: [['k(i)', '法律 i の産業（OECD 表6 の ISIC 節）']],
    rules: ['施行日が無ければ公布日で推定し「施行日は推定（公布日）」の印を付ける。'],
  },
  {
    id: 'covid',
    title: 'コロナ対応の法律の費用便益',
    version: 'covid-benefit-v1',
    status: '採用',
    code: ['scripts/build_covid_benefit.py', 'scripts/build_macro_amounts.py（apply_covid）'],
    lead: 'コロナ対応の法律では全体指標の差がコロナの落ち込みそのものになり、その法律の効果ではありません。比べるのは「コロナはあったが、その法律が無かった場合」です。法律に結びつく支出の規模を官公庁の一次資料から取り、定番の費用便益で便益の額にします。',
    formulas: [
      { tex: 'B^{(q)}_i = \\sum_{k} S_{i,k}\\; a^{(q)}_{i,k}\\; m^{(q)}_{i,k},\\qquad q\\in\\{\\text{下},\\text{中},\\text{上}\\}', note: '便益。幅の下・中・上は帰属と乗数の仮定の幅' },
    ],
    symbols: [
      ['S_{i,k}', '法律 i に結びつく支出 k の規模（円）。予算額か実績額で、官公庁の一次資料の原文の抜粋つき（data/acquired/covid-spending/）'],
      ['a_{i,k}', '法律への帰属割合。給付の差押禁止は差押えを受けうる世帯の割合（国保の差押世帯割合〜滞納世帯割合）、雇用保険の特例は財源措置が支えた割合'],
      ['m_{i,k}', '支出が消費・付加価値に回る割合。移転は消費に回る割合12〜22%（内閣府 政策課題分析22）、所得税減税0.25・公共投資1.12（内閣府 経済社会総合研究所 2018）'],
    ],
    rules: [
      '移転そのもの（給付・猶予）は便益にも損失にも数えない。数えるのは、移転が守った・下支えした消費や雇用の分だけ。',
      '財源調達の超過負担（死荷重）は、官公庁の単価が見つからなかったので差し引いていない（総便益）。額の読み方の注意に書く。',
      '規模は取れたが便益に換算する乗数・単価が定番の資料に無い法律は、額を出さず、規模と理由を残す。',
      '確かさは常に「参考」。議員への配分に使わない。全体指標の差の額は、コロナ対応の法律には付けない。',
    ],
  },
  {
    id: 'observation',
    title: '同じ観測を共有する法律の割り算',
    version: 'observation-split-v1',
    status: '採用',
    code: ['app/src/members-build.ts（splitRange・observationKey）', 'scripts/build_public_ranking.py（_reading_notes）'],
    lead: '同じ額の系列・同じ期間・同じ額の幅を複数の法律が共有するとき、それは1つの観測です。観測の額を本数で割ってから人に配り、同じ差を何度も数えません。',
    formulas: [
      { tex: 'o(i) = (\\text{観測グループ},\\ \\text{窓},\\ L_{\\mathrm{low}},\\ L_{\\mathrm{med}},\\ L_{\\mathrm{high}}),\\qquad n_o = \\bigl|\\{\\, j : o(j) = o \\,\\}\\bigr|' },
      { tex: 'A_i = \\operatorname{trunc}\\!\\left(\\frac{\\mathrm{Loss}_i}{n_{o(i)}}\\right)', note: '法律の分（円未満は0の方向へ切り捨て）' },
    ],
    symbols: [['n_o', '公開ランキングに残った、参考でない法律のうち、観測 o を共有する本数']],
    rules: ['法律の一覧では、確かさの高い順（同じなら id の昇順）の1本を代表の行にし、額は足し合わせない。'],
  },
  {
    id: 'allocation-v0',
    title: '成立への寄与（配分 v1 の中で使う Shapley 値）',
    version: 'causal-shapley-v1',
    status: '採用',
    code: ['app/src/causal-allocation.ts', 'app/src/members-build.ts'],
    lead: '「この人の行動が無かったら、その法律は成立したか」を投票のゲームの Shapley 値で測ります。method-spec-v1.0 まではこの割合をそのまま配っていました（配分 v0）。v2.0 からは、この割合を配分 v1（行動 × 向き × 結果）の中で使います。',
    formulas: [
      { tex: 'q = \\left\\lfloor \\frac{Y+N}{2} \\right\\rfloor + 1', note: '参議院本会議で可決に必要な票数' },
      { tex: '\\varphi_{\\mathrm{veto}} = \\frac{1}{n}\\sum_{j=q}^{Y} \\frac{\\binom{Y}{j}}{\\binom{n-1}{j+k-1}},\\qquad n = k + Y', note: '拒否権者1人の値' },
      { tex: '\\varphi_{\\mathrm{vote}} = \\frac{1 - k\\,\\varphi_{\\mathrm{veto}}}{Y}', note: '賛成1票の値' },
      { tex: '\\varphi_{p,i} = \\underbrace{\\frac{\\varphi_{\\mathrm{veto}}}{|\\mathcal P_i|}\\,[p\\in\\mathcal P_i]}_{\\text{提出者}} + \\underbrace{\\varphi_{\\mathrm{vote}}\\,[p\\in\\mathcal V_i]}_{\\text{参院の賛成}}', note: '衆議院の賛成会派の分 φ_veto は党に置き、個人には配らない' },
      { tex: 'S_{p} = \\sum_{i} A_i\\,\\varphi_{p,i},\\qquad \\mathrm{Net}_p = \\sum_{i\\in\\text{貢献}} S_{p,i} - \\sum_{i\\in\\text{悪影響}} S_{p,i}', note: '円の端数は最大剰余法。人・党・名前不明の合計は A_i にぴったり一致' },
    ],
    symbols: [
      ['k', '拒否権者の数（提出者の組と衆議院の賛成会派で 2。感度では委員長を足す）'],
      ['Y,\\ N', '参議院本会議の賛成票・反対票'],
      ['\\mathcal P_i,\\ \\mathcal V_i', '法律 i の提出者（閣法は閣議決定に関わった大臣、衆法は発議者）と、名前の確かめられた参院の賛成議員'],
      ['A_i', '法律の分（上の割り算の後の額）'],
    ],
    rules: [
      '質疑・修正案・基準での委員長は成立を左右しないので配らない（記録として出す）。',
      '「参考」の額は全議員の参考の欄へ別に配り、確かな額の議員順位には合算しない。',
      '見え方のつまみ（提出者の重み・衆院分の置き場所・委員長・帰属率）は、どの値でも割合の合計が1のまま。',
    ],
  },
  {
    id: 'allocation-v1',
    title: '責任の配り方（行動 × 向き × 結果）',
    version: 'allocation-v1',
    status: '採用',
    code: ['app/src/members-build.ts', 'app/src/members-knobs.ts', 'scripts/build_opposing_votes.py', 'scripts/build_auto_involvements.py', 'scripts/build_public_ranking.py'],
    lead: '一次資料に残る本人の行動ごとに、推したか止めたかの向きと、法律の結果の向きを掛けて配ります。閣法を閣議決定した担当の大臣の分は役職の帳簿にし、点数に入れません。コロナ期と分けて測れない法律とコロナ対応の法律は配りません（設計決定0014）。',
    formulas: [
      { tex: '\\text{行動}_{p,i} = \\underbrace{\\frac{\\varphi_{\\mathrm{veto}}}{|\\mathcal P_i|}\\,[p\\in\\mathcal P_i,\\ i\\notin\\text{閣法}]}_{\\text{発議}} + \\underbrace{\\varphi_{\\mathrm{vote}}\\,[p\\in\\mathcal V_i]}_{\\text{参院の賛成}}', note: '成立させた側。φ は「成立への寄与」の Shapley 値' },
      { tex: '\\text{反対}_{p,i} = \\varphi_{\\mathrm{vote}}\\,[p\\in\\mathcal N_i]', note: '参議院本会議の反対票。賛成1票と同じ割合で、向きを逆にする（法律の額の配分 Σ=1 とは別に数える）' },
      { tex: '\\mathrm{Net}_p = \\sum_i A_i\\,\\epsilon_i\\,\\bigl(\\text{行動}_{p,i} - \\text{反対}_{p,i}\\bigr),\\qquad \\epsilon_i = \\begin{cases} +1 & \\text{便益}\\\\ -1 & \\text{損失}\\end{cases}' },
      { tex: '\\text{役職}_{p} = \\sum_{i\\in\\text{閣法}} A_i\\,\\epsilon_i\\,\\frac{\\varphi_{\\mathrm{veto}}}{|\\mathcal P_i|}\\,[p\\in\\mathcal P_i]', note: '役職の帳簿。点数に入れない（つまみ office=1 で入れられる）' },
      { tex: '\\text{会派}_{g} = \\sum_i A_i\\,\\epsilon_i\\,\\frac{\\varphi_{\\mathrm{veto}}}{|\\mathcal G_i|}\\bigl([g\\in\\mathcal G_i] - [g\\in\\mathcal H_i]\\bigr)', note: '衆議院の会派の帳簿（起立採決で個人の賛否が残らない）。議員の点数には足さない' },
    ],
    symbols: [
      ['\\mathcal N_i', '法律 i に参議院本会議で反対した、人物の決まった議員'],
      ['\\mathcal G_i,\\ \\mathcal H_i', '法律 i の衆議院の賛成会派・反対会派（議案の経過。第186回国会ごろから）'],
      ['A_i', '法律の分（同じ観測を共有する本数で割った額）'],
    ],
    rules: [
      '配るのは確かさ「高」「中」「低」の法律（印つき）。「参考」は配らない。',
      '判定表の R3（コロナ期と分けて測れない）と、コロナ対応の法律（data/derived/covid-response-v1/labels.csv）は配らない。',
      '会議録から関与を集めていない法律は、議案の提出者の欄（閣法は提出時の内閣総理大臣）と参議院の個人別の賛否だけで機械的に配る。提出者が決まらない法律は配らない。',
      '同姓同名で人物を決められない票は配らない。',
      '会派を比べるときは総額でなく、賛否を示した法律1本あたり・1人あたりで見る（与党は法案の大半に賛成するため）。',
      '出自・国籍・信仰・家族は扱わない（固定）。',
    ],
  },
  {
    id: 'reference-members',
    title: '全議員の参考の額',
    version: 'reference-party-fallback-v1',
    alsoVersions: ['reference-split-by-observation-v1'],
    status: '採用',
    code: ['app/src/members-reference.ts'],
    lead: '確かさ「参考」の法律の額も、確かな額とは別の欄に、同じ Shapley 値で全議員に配ります。確かな額とは足さず、順位も別です。',
    formulas: [
      { tex: 'A^{\\text{参考}}_i = \\frac{\\mathrm{Loss}_i}{n_{(g,w)}}', note: '同じ指標の組 g・同じ窓 w を共有する本数で等分' },
      { tex: '\\varphi_{\\text{提出者}} = \\varphi_{\\text{衆院会派}} = \\varphi_{\\text{参院会派}} = \\tfrac{1}{3}', note: '参議院の個人別の賛否が見つからない法律（会派の分は人に配らない）' },
    ],
    symbols: [['n_{(g,w)}', '観測（指標の組と窓）を共有する参考の法律の本数']],
    rules: ['提出者は閣法なら提出時の内閣総理大臣、議員立法は提出者の欄の人。「○○君外N名」で一覧が無いときは代表者に 1/(N+1)。', '同姓同名の可能性がある名前は、一次資料で所属が決まる場合だけ人物IDに結ぶ。'],
  },
  {
    id: 'cause-axis',
    title: '伸び損ねた原因の軸の額（経済全体と産業固有に分ける）',
    version: 'cause-axis-v3',
    status: '採用',
    code: ['この式を計算するコードは、まだリポジトリにありません（計算は原因の軸の作業の axis_loss.py で行い、共有フォルダの analysis/伸び損ねた原因の軸_資料_2026-10-24/ にあります。取り込みは未定）。式と決まりは採用ですが、額は公開データに入っていません'],
    lead: '産業の差を「経済全体の差」と「産業固有の差」に分け、経済全体の差は全体にかかる決定（金融政策・財政・為替）に、産業固有の差は産業の決定（法律・規制・国策）に結びます。同じ差を両方に配りません。確かさは置換検定の順位で決め、高くても「参考」です。',
    formulas: [
      { tex: 'R^{j}_{k,t} = \\frac{V^{j}_{k,t} / V^{j}_{k,t_0}}{V^{j}_{t} / V^{j}_{t_0}}', note: '産業 k の実質の伸びを、その国全体の実質の伸びで割った比（t₀ = 2000年）' },
      { tex: 'D_{k,t} = N^{\\mathrm{JP}}_{k,t}\\left(\\frac{\\operatorname{med}_{c\\in C^{*}} R^{c}_{k,t}}{R^{\\mathrm{JP}}_{k,t}} - 1\\right),\\qquad D_k = \\sum_{t=2001}^{2023} D_{k,t}', note: '産業固有の差（その年の名目円で換算して累計。日本が上回る年は負のまま差し引く）' },
      { tex: 'E_t = N^{\\mathrm{JP}}_{t}\\left(\\frac{\\operatorname{med}_{c\\in C^{*}} \\, y^{c}_t / y^{c}_{t_0}}{y^{\\mathrm{JP}}_t / y^{\\mathrm{JP}}_{t_0}} - 1\\right)', note: '経済全体の差（y は就業者1人当たりの実質付加価値）' },
      { tex: 'D^{\\text{内訳}}_{m} \\leftarrow D^{\\text{内訳}}_{m}\\cdot \\frac{D_{\\text{全体}}}{\\sum_{m\'} D^{\\text{内訳}}_{m\'}}', note: '連鎖の実質は足せないので、内訳の差は上位の産業の差を上限に比で配り直す' },
      { tex: '\\Delta\\ln V^{j}_{k} = s^{j}_{L,k}\\,\\Delta\\ln L^{j}_{k} + \\bigl(1-s^{j}_{L,k}\\bigr)\\,\\Delta\\ln K^{j}_{k} + \\Delta\\ln A^{j}_{k}', note: '成長会計：付加価値の伸びを、働く人の数・資本・全要素生産性の伸びに分ける（s_L は労働の分け前）' },
    ],
    symbols: [
      ['V^{j}_{k,t},\\ V^{j}_{t}', '国 j の産業 k と全産業の実質付加価値（連鎖の数量）'],
      ['N^{\\mathrm{JP}}_{k,t}', '日本の産業 k の年 t の名目付加価値（円）'],
      ['C^{*}', '比べる国：OECD STAN に1995〜2023年の実質がある国のうち、追い上げの段階の国（t₀ の就業者1人当たり GDP（購買力平価）が日本の8割未満）とアイルランドを除いた国（15〜18か国。産業ごとに系列のある国）'],
      ['L^{j}_{k},\\ K^{j}_{k},\\ A^{j}_{k},\\ s^{j}_{L,k}', '国 j の産業 k の就業者（労働時間が取れる国は労働時間）、実質の資本ストック、全要素生産性、雇用者報酬の付加価値に占める割合'],
      ['\\rho_k', '置換検定の順位：C* の各国を1つずつ「日本の役」にして同じ差を計算し、日本の差が大きい方から何番目か（日本の差が負＝便益の産業は、負に大きい方から数える）'],
    ],
    rules: [
      '同じ産業の差に結ぶ軸が複数あるときは、本数で等分し「同じ観測を共有」の印を付ける（observation-split-v1 と同じ）。',
      '経済全体の差は、全体にかかる決定の効果の推定（設計決定0013 の3章、v2）ができるまで配らない。',
      'アイルランドは多国籍企業の計上で情報通信の付加価値がゆがむので比べる国から外す。主要5か国だけの中央値は1国（米国）で大きく振れるので使わない（感度として並べるのはよい）。',
      '確かさ：置換検定の順位が3位以内（ρ_k ≤ 3）なら「参考」、4位以下なら「誤差の範囲」とし、額は記録だけにして軸に配らない。日本の差が負（日本の方が伸びた）の産業は便益として同じ基準で扱い、順位は負に大きい方から数える（片側の検定を差の向きにそろえる）。',
      '同じ軸に損失の産業と便益の産業が結ぶときは、相殺した純額をその軸の額にする（法律の額で便益を差し引くのと揃える）。相殺前の損失だけの額は感度として並べ、順位はそれぞれの産業の順位で示す。',
      '成長会計：産業固有の差を、働く人の数の伸びの差・資本の伸びの差・残り（全要素生産性）に分けて並べる。配る額は分ける前の差のまま。内訳は比べる国の平均で出す（中央値では内訳の足し算が合わないため）。期間と比べる国は、就業者と資本の系列がそろう年と国に限る（OECD STAN 2020年版、日本は2019年まで）。就業者や資本の系列が無い国・産業は、分けられない分を残りに含めて「資本の分を含む」の印を付ける。働く人の数の分が差の半分を超える産業には「人の数の差が大きい」の印を付ける。',
      '合成対照（比べる国の重みつき平均。重みは1995〜2000年の当てはまり）は感度の列としてだけ出す。合わせる年が6年しかなく、重みが1〜2か国に偏るため。既定の額には使わない。',
      '他国の支援が強い産業（電子機器 C26・通信 J61）は、支援の強い国（韓国）を除いた額も感度として並べる（外生の分の差し引き）。',
      '追い上げの国の基準は境目に近い国（2000年の韓国は日本の81%）で、基準の年や物価の取り方で入れ替わる。基準を変えるときは版を上げ、入れた額と外した額の両方を並べる。外した額（または入れた額）は感度として出す。品質調整の大きい産業（情報通信・電子部品）には「物価の作り方の差を含む」の印を付ける。',
    ],
  },
  {
    id: 'certainty',
    title: '確かさの印',
    version: 'certainty-v1',
    status: '採用',
    code: ['scripts/build_public_ranking.py（certainty）'],
    lead: '額の横に付ける確かさは、段階と参考の区別で機械的に決まります。段階が3・2でも、コロナ期と分離できない法律は参考に下げます。',
    formulas: [
      { tex: '\\text{確かさ}(i) = \\begin{cases} \\text{高} & \\text{段階3} \\\\ \\text{中} & \\text{段階2} \\\\ \\text{低} & \\text{段階1} \\\\ \\text{参考} & \\text{貸出残高の機械的仮定・代理の指標・全体指標（macro-v1）、または判定表 R3・コロナ対応の法律（段階に関わらず）} \\end{cases}' },
    ],
    symbols: [],
    rules: [
      '議員への配分は高・中・低を配る（低は印つき。設計決定0014）。参考は配らない。',
      '例外：判定表の行が R3（コロナ期と分離できない）の法律と、コロナ対応の法律（covid-response-v1）は、段階が3・2でも確かさを参考に下げ、「コロナ期と分離できない」の印を付けて配らない（設計決定0014 決定3・4。いま段階3・2から下がるのは13本）。',
      '読み方の印：コロナ期と重なる、便益側の一部が未測定、同じ観測を共有、日本の全産業の付加価値1年分を超える額、施行日は推定（公布日）。',
    ],
  },
];

/** その節で使っている定番の手法。 */
export function methodsOf(sectionId: string): StandardMethod[] {
  return STANDARD_METHODS.filter(m => m.sections.includes(sectionId));
}

/** LaTeX の式を Markdown（GitHub の $$ ブロック）に書く。 */
export function sectionMarkdown(s: SpecSection): string {
  const lines = [`## ${s.title}`, '', `版：${[s.version, ...(s.alsoVersions ?? [])].map(v => `\`${v}\``).join('・')}（${s.status}）　実装：${s.code.map(c => `\`${c}\``).join('、')}`, '', s.lead, ''];
  const methods = methodsOf(s.id);
  if (methods.length) lines.push(`定番の手法：${methods.map(m => m.name).join('・')}`, '');
  for (const f of s.formulas) {
    if (f.note) lines.push(`${f.note}：`, '');
    lines.push('$$', f.tex, '$$', '');
  }
  if (s.symbols.length) {
    lines.push('| 記号 | 意味 |', '|---|---|');
    for (const [sym, meaning] of s.symbols) lines.push(`| $${sym}$ | ${meaning.replace(/\|/g, '｜')} |`);
    lines.push('');
  }
  for (const r of s.rules) lines.push(`- ${r}`);
  if (s.rules.length) lines.push('');
  return lines.join('\n');
}

export function specMarkdown(): string {
  return [
    `# 計算式（${SPEC_VERSION}、${SPEC_DATE}）`,
    '',
    'このファイルは `app/src/method-spec.ts` から `node scripts/build_formula_doc.mjs` で作ります。手で直さず、元のファイルを直してください。',
    '版の決まり・変更の記録・マクロ経済の枠組みは [設計決定0013](adr/0013-calculation-spec-versioning.md) にあります。',
    '',
    '## 使っている定番の手法',
    '',
    'この計算は、経済学・統計学・政治学で広く使われている次の手法でできています。これ以外の独自の式は使っていません。',
    '',
    '| 手法 | 何に使うか | 出典 | 式 |',
    '|---|---|---|---|',
    ...STANDARD_METHODS.map(m => `| ${m.name} | ${m.use} | ${m.refs.join('／')} | ${m.sections.map(id => SPEC_SECTIONS.find(x => x.id === id)?.title.replace(/（.*$/, '') ?? id).join('・')} |`),
    '',
    ...SPEC_SECTIONS.map(sectionMarkdown),
  ].join('\n');
}
