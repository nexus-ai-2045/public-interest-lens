export const meta = {
  name: 'law-eval-audit',
  description: '額なし375本の除外が妥当か、全産業で測った1303本が産業に結べるかを Haiku 2系統→Sonnet→Opus で判定',
  phases: [
    { title: 'Haiku', detail: '束ごとに独立2系統で判定' },
    { title: 'Sonnet', detail: '不一致だけ突き合わせ' },
    { title: 'Opus', detail: '変更案だけ最終確認' },
  ],
}

const SECTIONS = ['A','B','C','D','F','G','H','I','J','K','L','M','P','Q','R','TOTAL','NONMARKET']
const SEC_HELP = 'A=農林水産 B=鉱業 C=製造業 D=電気・ガス・蒸気 F=建設 G=卸売・小売 H=運輸・保管 I=宿泊・飲食 J=情報通信 K=金融・保険 L=不動産 M=専門・科学技術サービス(士業・研究開発・知財含む) P=教育 Q=医療・福祉 R=芸術・娯楽・その他サービス TOTAL=特定の産業に結べず経済全体に効く NONMARKET=公務・司法・防衛・選挙など市場の付加価値で測れない'

const A_SCHEMA = { type: 'object', properties: { items: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, verdict: { enum: ['excluded_ok', 'substantive'] }, section: { enum: SECTIONS }, reason: { type: 'string' } },
  required: ['id', 'verdict', 'section', 'reason'] } } }, required: ['items'] }
const B_SCHEMA = { type: 'object', properties: { items: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, section: { enum: SECTIONS }, confidence: { enum: ['high', 'low'] }, reason: { type: 'string' } },
  required: ['id', 'section', 'confidence', 'reason'] } } }, required: ['items'] }

const promptA = (file, lens) => `ファイル ${file} (JSON配列) を Read して、各法律について判定せよ。
各行は、これまで「効果を測らない」と決めた法律（定例改正や、定型改正・組織手続だけの法律）。規則名は「規則」列（RT1給与改定 RT2地方交付税 RT3公債特例 RT4剰余金 RT5年金額特例 RT6用語整理 RT7選挙経費 RT8時限措置の延長のみ）。
判定: 題名と「何をする」から、本当に毎年・毎回の定例／字句整理／組織手続だけなら excluded_ok。国民や産業に実質的な制度変更（新しい義務・給付の仕組み・料率や対象の変更・新制度）が含まれうるなら substantive。迷うときは excluded_ok ではなく substantive にせよ…とはせず、題名と説明に実質変更を示す語が実際にあるときだけ substantive。
substantive のときは測る産業 section を選べ（${SEC_HELP}）。excluded_ok のときは section は NONMARKET か TOTAL を入れてよい。
${lens}
事実は題名・説明だけから。人物・属性には触れない。全件について items に1つずつ返せ（id は入力のまま）。reason は40字以内。`

const promptB = (file, lens) => `ファイル ${file} (JSON配列) を Read して、各法律の「主に効果が及ぶ産業」を1つ選べ。選択肢: ${SEC_HELP}。
現状はどれも TOTAL（全産業）で測っている。題名と「何をする」から、特定の産業の付加価値の動きで効果を測るのが自然なら、その産業の節を選べ。複数にまたがる・産業を狙わない一般法は TOTAL。公務・司法・防衛・選挙・外交・年金給付の移転などは NONMARKET。
${lens}
事実は題名・説明だけから。人物・属性には触れない。確信が低ければ confidence=low。全件について items に1つずつ返せ（id は入力のまま）。reason は40字以内。`

const LENS1 = '（系統1）産業への経路を厳密に問え。経路が説明できる場合だけ産業を選ぶ。'
const LENS2 = '（系統2）法律が直接規制・支援する事業者や取引は何かから逆に考えよ。事業者が属する産業を選ぶ。'

const jobs = []
for (let b = 0; b < 8; b++) jobs.push({ kind: 'A', file: `/tmp/audit/in_${b}.json`, tag: `A${b}` })
for (let b = 0; b < 27; b++) jobs.push({ kind: 'B', file: `/tmp/audit/b_${b}.json`, tag: `B${b}` })

const results = await pipeline(jobs,
  async job => {
    phase('Haiku')
    const mk = (lens, n) => agent(job.kind === 'A' ? promptA(job.file, lens) : promptB(job.file, lens),
      { model: 'haiku', schema: job.kind === 'A' ? A_SCHEMA : B_SCHEMA, label: `haiku${n}:${job.tag}`, phase: 'Haiku' })
    const [h1, h2] = await parallel([() => mk(LENS1, 1), () => mk(LENS2, 2)])
    return { job, h1: h1 ? h1.items : [], h2: h2 ? h2.items : [] }
  },
  async r => {
    const { job, h1, h2 } = r
    const m2 = new Map(h2.map(x => [x.id, x]))
    const agreed = [], disputed = []
    for (const x of h1) {
      const y = m2.get(x.id)
      const key = o => job.kind === 'A' ? o.verdict + '/' + (o.verdict === 'substantive' ? o.section : '-') : o.section
      if (y && key(x) === key(y)) agreed.push({ ...x, how: 'agree' })
      else disputed.push({ id: x.id, h1: x, h2: y || null })
    }
    for (const y of h2) if (!h1.find(x => x.id === y.id)) disputed.push({ id: y.id, h1: null, h2: y })
    if (!disputed.length) return { job, agreed, resolved: [] }
    const file = job.file
    const prompt = `2系統の Haiku が判定した結果が食い違った法律がある。入力ファイル ${file} を Read して題名と「何をする」を確認し、各 id の最終判定を出せ。
${job.kind === 'A' ? 'verdict=excluded_ok（定例・字句・組織手続だけ）か substantive（実質的な制度変更。その場合は測る産業 section も）。' : '主に効果が及ぶ産業の節を1つ。'}
産業の選択肢: ${SEC_HELP}
食い違い: ${JSON.stringify(disputed)}`
    const out = await agent(prompt, { model: 'sonnet', schema: job.kind === 'A' ? A_SCHEMA : B_SCHEMA, label: `sonnet:${job.tag}`, phase: 'Sonnet' })
    return { job, agreed, resolved: (out ? out.items : []).map(x => ({ ...x, how: 'sonnet' })) }
  })

const all = results.filter(Boolean)
const A = all.filter(r => r.job.kind === 'A').flatMap(r => [...r.agreed, ...r.resolved])
const B = all.filter(r => r.job.kind === 'B').flatMap(r => [...r.agreed, ...r.resolved])
log(`A: ${A.length}/375, B: ${B.length}/1303`)

// 変更案（現状から動くもの）だけ Opus が確認する
const changeA = A.filter(x => x.verdict === 'substantive')
const changeB = B.filter(x => x.section !== 'TOTAL' && x.section !== 'NONMARKET')
log(`変更案 A:${changeA.length} B:${changeB.length}`)
phase('Opus')
const chunk = (arr, n) => Array.from({ length: Math.ceil(arr.length / n) }, (_, i) => arr.slice(i * n, i * n + n))
const FIN = { type: 'object', properties: { items: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, accept: { type: 'boolean' }, section: { enum: SECTIONS }, note: { type: 'string' } }, required: ['id', 'accept', 'section', 'note'] } } }, required: ['items'] }
const finalA = await parallel(chunk(changeA, 40).map((c, i) => () => agent(
  `次は「効果を測らない」とされていたが、AIの判定で実質的な制度変更を含み産業で測るべきとされた法律の候補。入力の題名・説明は ${JSON.stringify(c.map(x => x.id))} を /tmp/audit/in_*.json から Read して照合し、本当にそうか厳しく確認せよ。確かな場合だけ accept=true とし測る節 section を返せ。判定: ${JSON.stringify(c)}\n産業の選択肢: ${SEC_HELP}`,
  { model: 'opus', schema: FIN, label: `opus:A${i}`, phase: 'Opus' })))
const finalB = await parallel(chunk(changeB, 60).map((c, i) => () => agent(
  `次は全産業で測っているが、特定の産業で測るのが自然とAIが判定した法律の候補。題名・説明は /tmp/audit/b_*.json から id で Read して照合し、その産業の付加価値の動きで効果を測るのが妥当と確かに言える場合だけ accept=true、節を section に。曖昧なら accept=false (TOTAL)。判定: ${JSON.stringify(c)}\n産業の選択肢: ${SEC_HELP}`,
  { model: 'opus', schema: FIN, label: `opus:B${i}`, phase: 'Opus' })))

return {
  A_count: A.length, B_count: B.length,
  A_all: A, B_all: B,
  finalA: finalA.filter(Boolean).flatMap(r => r.items),
  finalB: finalB.filter(Boolean).flatMap(r => r.items),
}
