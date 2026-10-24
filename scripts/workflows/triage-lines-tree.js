export const meta = {
  name: 'triage-lines-tree',
  description: '振り分け v2 で2系統が食い違う法律を、どちらの系統を採るか Haiku 2系統→Sonnet→Opus で決める（R2）',
  phases: [{ title: 'Haiku 2系統' }, { title: 'Sonnet 突き合わせ' }, { title: 'Opus 確認' }],
}
const DIR = args.dir
// v2 の基準（8分野＋新分野9つ）を渡す。旧 v1 の spec は新分野を「対応表なし」としているので使わない
const SPECS = args.specs.join('、')
const CHOICES = ['系統1', '系統2', '保留']
// スキーマのキーは ASCII にする（pick＝採用、reason＝理由、how＝決め方）
const ITEM = { type: 'object', properties: { id: { type: 'string' }, pick: { type: 'string', enum: CHOICES }, reason: { type: 'string' } }, required: ['id', 'pick', 'reason'] }
const OUT = { type: 'object', properties: { items: { type: 'array', items: ITEM } }, required: ['items'] }
const FINAL_ITEM = { type: 'object', properties: { ...ITEM.properties, how: { type: 'string', enum: ['一致', 'Sonnetが決定'] } }, required: ['id', 'pick', 'reason', 'how'] }
const FINAL = { type: 'object', properties: { items: { type: 'array', items: FINAL_ITEM } }, required: ['items'] }
const batches = Array.from({ length: args.n }, (_, i) => `${DIR}/l${String(i).padStart(3, '0')}.json`)

const RULES = `各行は成立した法律1本で、独立した2つの振り分け（系統1・系統2）の判定・種類・分野・指標・理由と、` +
  `国会会議録の提案理由の要約（何をする・狙い。無い行もある）がある。` +
  `種類の定義：新規＝新しい法律を作る。実質改正＝規制・制度・税率・対象範囲などの中身を変える改正。` +
  `定型改正＝毎年の税法改正の定例部分、給与法、期限の延長だけ、名称・字句の整理だけ。組織手続＝設置法・定員・組織の再編・手続きや事務の整理・整備法。` +
  `分野は8分野と、新分野9つ（農林水産・建設・住宅・不動産・教育・医療・福祉・製造業・商業・専門サービス・研究開発・文化・娯楽・生活サービス）で、新分野にも対応表がある。どれにも当たらないときだけ対応表なし。` +
  `判定は、種類が定型改正か組織手続、または分野が対応表なしなら評価対象外、それ以外は評価対象。` +
  `あなたの仕事は、定義と、題名・提案理由の要約に書かれた事実だけに照らして、正しいのは系統1か系統2かを選ぶこと（pick）。` +
  `新しい値は作らない。片方の判定が「保留」ならもう片方を採るかどうかだけを決める。` +
  `期限の延長が中心でも、対象や中身を変える改正が書かれていれば実質改正。要約が無く題名だけで期限延長か中身の改正か決まらないなど、` +
  `どちらとも決められない場合だけ「保留」にする。推測で事実を足さない。理由（reason）は根拠を短い日本語1文で書く。`

const judge = (file, line) => agent(
  `あなたは法律の振り分けの第3の判定者（系統${line}）です。必要なら ${SPECS} を Read で読んで定義を確かめてください。` +
  `${file} を Read で読んでください。${RULES} ファイル内の全行を返してください。`,
  { label: `haiku${line}:${file.slice(-9, -5)}`, phase: 'Haiku 2系統', schema: OUT, model: 'haiku', effort: 'low' })

const judged = await pipeline(batches, async (file) => {
  const [a, b] = await parallel([() => judge(file, 1), () => judge(file, 2)])
  return { file, a: a?.items ?? [], b: b?.items ?? [] }
})
// Sonnet は2バッチずつ見る
const pairs = []
for (let i = 0; i < judged.length; i += 2) pairs.push(judged.slice(i, i + 2).filter(Boolean))
const results = await parallel(pairs.map((pair, i) => () => agent(
  `あなたは法律の振り分けの突き合わせ役です。${pair.map(p => p.file).join(' と ')} を Read で読んでください。${RULES}\n` +
  `第3の判定者2系統（Haiku）の結果は次のとおりです。\n` +
  pair.map(p => `${p.file}\n判定者1：${JSON.stringify(p.a)}\n判定者2：${JSON.stringify(p.b)}`).join('\n') + '\n' +
  `各 id について、2人の pick が一致していれば、その値を採り、決め方（how）を「一致」にしてください（明らかに定義に反するときだけ直し、そのときは「Sonnetが決定」）。` +
  `割れていれば、定義と題名・要約に照らして決め、決め方を「Sonnetが決定」にしてください。ファイルの全 id を返してください。`,
  { label: `sonnet:${i}`, phase: 'Sonnet 突き合わせ', schema: FINAL, model: 'sonnet' })))
// 「一致」は Sonnet の自己申告ではなく、Haiku 2系統の pick をここで機械的に比べて決める（ADR 0007）
const haiku = new Map()
for (const j of judged.filter(Boolean)) {
  for (const x of j.a) haiku.set(x.id, { ...(haiku.get(x.id) ?? {}), a: x.pick })
  for (const x of j.b) haiku.set(x.id, { ...(haiku.get(x.id) ?? {}), b: x.pick })
}
const agreed = (x) => { const h = haiku.get(x.id); return !!h && h.a !== undefined && h.a === h.b && h.a === x.pick }
const all = results.filter(Boolean).flatMap(r => r.items).map(x => ({ ...x, how: agreed(x) ? '一致' : 'Sonnetが決定' }))
log(`Sonnet まで：${all.length}行（Haiku 2系統が一致 ${all.filter(x => x.how === '一致').length}行）`)

const REVIEW = { type: 'object', properties: { fixes: { type: 'array', items: ITEM }, error_types: { type: 'array', items: { type: 'string' } } }, required: ['fixes', 'error_types'] }
const review = await agent(
  `あなたは法律の振り分け全体の一貫性を確認する役です。元の行は ${DIR}/l*.json にあります（Read で読んでください）。${RULES}\n` +
  `次の決定を見て、同じ法律の改正なのに違う系統を採って判定が割れている行、給与法・期限延長だけの改正を評価対象にしている行、` +
  `提案理由の要約と食い違う行を探してください。直すべき行だけ fixes に入れ（pick と reason）、見つけた誤りの型を短い日本語で error_types に列挙します。\n` +
  JSON.stringify(all), { label: 'opus', phase: 'Opus 確認', schema: REVIEW, model: 'opus' })
const fixes = review?.fixes ?? []
const byId = new Map(fixes.map(f => [f.id, f]))
const labels = all.map(x => byId.has(x.id) ? { ...byId.get(x.id), how: 'Opusが修正' } : x)
  .map(x => ({ id: x.id, 採用: x.pick, 決め方: x.how, 理由: x.reason }))
return { labels, 誤りの型: review?.error_types ?? [], fixes: fixes.length }
