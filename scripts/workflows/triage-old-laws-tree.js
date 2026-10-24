export const meta = {
  name: 'triage-old-laws-tree',
  description: '第77〜141回の成立法（R1）の題名に、独立した3つの AI（v1 の A・B と系統2）が種類・分野を付ける',
  phases: [{ title: 'Haiku 3系統' }],
}
// args：dir（b000.json… のフォルダ、各行は id＝法令番号・題名）、n（バッチ数）、
// v1spec（data/derived/bill-triage-v1/spec.md）、line2（[criteria.md, criteria-v2-fields.md] の絶対パス）
const KINDS = ['新規', '実質改正', '定型改正', '組織手続', '保留']
const V1_FIELDS = ['金融', '交通・移動', '宿泊・観光', '通信・ネット', '半導体・電子', 'エネルギー', '労働市場', '行政のデジタル化', '対応表なし', '保留']
const NEW_FIELDS = ['農林水産', '建設', '住宅・不動産', '教育', '医療・福祉', '製造業', '商業', '専門サービス・研究開発', '文化・娯楽・生活サービス']
// スキーマのキーは ASCII にする（kind＝種類、field＝分野、reason＝理由）
const out = (fields) => ({
  type: 'object',
  properties: { items: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' }, kind: { type: 'string', enum: KINDS }, field: { type: 'string', enum: fields }, reason: { type: 'string' },
  }, required: ['id', 'kind', 'field', 'reason'] } } },
  required: ['items'],
})
const batches = Array.from({ length: args.n }, (_, i) => `${args.dir}/b${String(i).padStart(3, '0')}.json`)
const COMMON = `各行は成立した法律1本（id は法令番号）。題名だけを材料に、推測で事実を足さず、迷ったら「保留」にする。` +
  `付託委員会は無いので使わない。ファイル内の全行を、同じ順で、id をそのまま写して返す。理由（reason）は根拠を短い日本語1文で書く。`

const label = (file, who) => {
  const v1 = who !== 'line2'
  const prompt = v1
    ? `あなたは法律の振り分けの系統${who}です。${args.v1spec} を Read で読み、その定義（種類と分野。分野は8分野か対応表なし）に従ってください。` +
      `${file} を Read で読んでください。${COMMON} 指標と判定は返さない（後で機械的に決める）。`
    : `あなたは法律の振り分けの系統2です。${args.line2.join(' と ')} を Read で読み、その基準（種類、分野は8分野を優先し、どれにも当たらないときだけ新分野9つ、それにも当たらなければ対応表なし）に従ってください。` +
      `${file} を Read で読んでください。${COMMON} 指標と判定は返さない（後で機械的に決める）。`
  return agent(prompt, { label: `${who}:${file.slice(-9, -5)}`, phase: 'Haiku 3系統', schema: out(v1 ? V1_FIELDS : [...V1_FIELDS, ...NEW_FIELDS]), model: 'haiku', effort: 'low' })
}

const results = await pipeline(batches, async (file) => {
  const [a, b, c] = await parallel([() => label(file, 'A'), () => label(file, 'B'), () => label(file, 'line2')])
  return { file, A: a?.items ?? [], B: b?.items ?? [], line2: c?.items ?? [] }
})
const done = results.filter(Boolean)
log(`バッチ ${done.length}/${batches.length}、A ${done.reduce((s, r) => s + r.A.length, 0)}行・B ${done.reduce((s, r) => s + r.B.length, 0)}行・系統2 ${done.reduce((s, r) => s + r.line2.length, 0)}行`)
return {
  A: done.flatMap(r => r.A), B: done.flatMap(r => r.B), line2: done.flatMap(r => r.line2),
  missing: done.filter(r => !r.A.length || !r.B.length || !r.line2.length).map(r => r.file),
}
