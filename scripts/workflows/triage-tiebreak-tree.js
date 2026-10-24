export const meta = {
  name: 'triage-tiebreak-tree',
  description: '振り分け v1 で A/B が割れた法律の種類・分野を Haiku 2系統→Sonnet→Opus で決める',
  phases: [{ title: 'Haiku 2系統' }, { title: 'Sonnet 突き合わせ' }, { title: 'Opus 確認' }],
}
const DIR = args.dir
const SPEC = args.spec
const TYPES = ['新規', '実質改正', '定型改正', '組織手続', '保留']
const FIELDS = ['金融', '交通・移動', '宿泊・観光', '通信・ネット', '半導体・電子', 'エネルギー', '労働市場', '行政のデジタル化', '対応表なし', '保留']
// スキーマのキーは ASCII にする（日本語のキーはモデルによって受け付けられない。kind＝種類、field＝分野、reason＝理由、how＝決め方）
const ITEM = { type: 'object', properties: { id: { type: 'string' }, kind: { type: 'string', enum: TYPES }, field: { type: 'string', enum: FIELDS }, reason: { type: 'string' } }, required: ['id', 'kind', 'field', 'reason'] }
const OUT = { type: 'object', properties: { items: { type: 'array', items: ITEM } }, required: ['items'] }
const FINAL_ITEM = { type: 'object', properties: { ...ITEM.properties, how: { type: 'string', enum: ['一致', 'Sonnetが決定'] } }, required: ['id', 'kind', 'field', 'reason', 'how'] }
const FINAL = { type: 'object', properties: { items: { type: 'array', items: FINAL_ITEM } }, required: ['items'] }
const batches = Array.from({ length: args.n }, (_, i) => `${DIR}/t${String(i).padStart(3, '0')}.json`)

const judge = (file, line) => agent(
  `あなたは法律の振り分けの第3の判定者（系統${line}）です。まず ${SPEC} を Read で読み、種類と分野の定義を把握してください。` +
  `次に ${file} を Read で読んでください。各行は成立した法律1本で、AI の A と B が付けた種類・分野と理由があり、「決める項目」で割れた項目が分かります。` +
  `各行について、定義に照らして種類（kind）と分野（field）を1つずつ決めてください。割れていない項目は A と B の一致した値をそのまま返します。` +
  `判断は題名と定義だけで行い、推測で事実を足さないこと。A か B のどちらかの値を採るのが基本で、どちらも定義に合わない場合だけ別の値を選びます。` +
  `本当に決められない場合だけ「保留」とします。理由（reason）は短い日本語1文で書いてください。ファイル内の全行を返してください。`,
  { label: `haiku${line}:${file.slice(-9, -5)}`, phase: 'Haiku 2系統', schema: OUT, model: 'haiku', effort: 'low' })

const results = await pipeline(batches,
  async (file) => {
    const [a, b] = await parallel([() => judge(file, 1), () => judge(file, 2)])
    return { a, b }
  },
  async ({ a, b }, file) => agent(
    `あなたは法律の振り分けの突き合わせ役です。${SPEC} を Read で読んで定義を確認し、${file} を Read で読んでください（元の A・B の値と理由）。` +
    `第3の判定者2系統の結果は次のとおりです。\n系統1：${JSON.stringify(a?.items ?? [])}\n系統2：${JSON.stringify(b?.items ?? [])}\n` +
    `各 id について、2系統の種類と分野が一致していれば、その値を採り、決め方（how）を「一致」にしてください。` +
    `割れていれば、定義と題名に照らして正しいほうを選び（必要なら別の値）、決め方を「Sonnetが決定」にしてください。` +
    `「保留」は定義上どうしても決まらない場合だけ使います。理由は短い日本語1文で書きます。ファイルの全 id を返してください。`,
    { label: `sonnet:${file.slice(-9, -5)}`, phase: 'Sonnet 突き合わせ', schema: FINAL, model: 'sonnet' }),
)
const all = results.filter(Boolean).flatMap(r => r.items)
log(`Sonnet まで：${all.length}行`)

const REVIEW = { type: 'object', properties: { fixes: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, kind: { type: 'string', enum: TYPES }, field: { type: 'string', enum: FIELDS }, reason: { type: 'string' } }, required: ['id', 'kind', 'field', 'reason'] } }, error_types: { type: 'array', items: { type: 'string' } } }, required: ['fixes', 'error_types'] }
const chunks = [all.slice(0, Math.ceil(all.length / 2)), all.slice(Math.ceil(all.length / 2))]
const reviews = await parallel(chunks.map((c, i) => () => agent(
  `あなたは法律の振り分け全体の一貫性を確認する役です。${SPEC} を Read で読み、定義を確認してください。` +
  `次の決定（題名は ${DIR}/t*.json にあります。必要なら Read で読んでください）を見て、分野をまたいだ一貫性を確かめます。` +
  `たとえば、同じ法律の改正なのに種類や分野が違う行、給与法・期限延長が定型改正になっていない行、設置法・整備法が組織手続になっていない行、` +
  `8分野にはっきり当たらないのに8分野になっている行を探してください。直すべき行だけ fixes に入れ、見つけた誤りの型を短い日本語で error_types に列挙します（fixes の kind は種類、field は分野、reason は理由）。\n` +
  JSON.stringify(c), { label: `opus:${i}`, phase: 'Opus 確認', schema: REVIEW, model: 'opus' })))
const fixes = reviews.filter(Boolean).flatMap(r => r.fixes)
const kinds = reviews.filter(Boolean).flatMap(r => r.error_types)
const byId = new Map(fixes.map(f => [f.id, f]))
const labels = all.map(x => byId.has(x.id) ? { ...byId.get(x.id), how: 'Opusが修正' } : x)
  .map(x => ({ id: x.id, 種類: x.kind, 分野: x.field, 理由: x.reason, 決め方: x.how }))
return { labels, 誤りの型: kinds, fixes: fixes.length }