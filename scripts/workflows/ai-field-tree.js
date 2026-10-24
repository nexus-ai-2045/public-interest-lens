export const meta = {
  name: 'classify-unmapped-laws-tree',
  description: '対応表の無い法律を Haiku 2系統→Sonnet 突き合わせ→Opus 整合確認の木で産業に振り分ける',
  phases: [{ title: 'Haiku 2系統' }, { title: 'Sonnet 突き合わせ' }, { title: 'Opus 整合確認' }],
}
const DIR = args.dir
const N = args.n, GROUP = 10, OPUS = 3
const FIELDS = ['エネルギー','交通・移動','労働市場','半導体・電子','宿泊・観光','行政のデジタル化','通信・ネット','金融','農林水産','建設','住宅・不動産','教育','医療・福祉','製造業','商業','専門サービス・研究開発','文化・娯楽・生活サービス','経済全体']
const LABEL = { type: 'object', properties: { id: { type: 'string' }, field: { type: 'string', enum: FIELDS }, reason: { type: 'string' } }, required: ['id','field','reason'] }
const SCHEMA = { type: 'object', properties: { labels: { type: 'array', items: LABEL } }, required: ['labels'] }
const RULES = `分野の候補（このどれか1つ、文字列は完全一致）: ${FIELDS.join('、')}
- 特定の産業に結びつかない法律（司法、刑事、選挙、国会、防衛、外交、条約の承認、行政組織、公務員、年金・財政全般、税全般、地方自治、皇室 など）は「経済全体」。
- 迷ったら「経済全体」。推測で特定の産業に寄せない。
- reason は20字以内。`
const file = i => `${DIR}/b${String(i).padStart(3, '0')}.json`
const haiku = (i, line) => agent(`${file(i)} を Read で読んでください（id と title の配列、日本の法律）。各法律について、その法律が効いたときに最も直接に付加価値が変わる産業の分野を1つ選びます。
${RULES}
観点（系統${line}）：${line === 'A' ? '題名に出てくる対象（業・物・制度）がどの産業に属するか。' : 'この法律で行動が変わる事業者（規制される側・補助される側）が主にどの産業か。法律の目的を一般知識で考える。'}
ファイルの全件について、同じ id で1行ずつ返してください。ほかのファイルは読まないでください。`, { label: `haiku${line}:${i}`, phase: 'Haiku 2系統', model: 'haiku', effort: 'low', schema: SCHEMA })

const groups = Array.from({ length: Math.ceil(N / GROUP) }, (_, g) => Array.from({ length: GROUP }, (_, k) => g * GROUP + k).filter(i => i < N))
const DECIDED = { type: 'object', properties: { labels: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, field: { type: 'string', enum: FIELDS }, how: { type: 'string', enum: ['一致', 'Sonnetが決定', '経済全体に倒した'] }, reason: { type: 'string' } }, required: ['id','field','how','reason'] } } }, required: ['labels'] }

const sonnet = await pipeline(groups, async (idx, _, g) => {
  const lines = await parallel(idx.flatMap(i => [() => haiku(i, 'A'), () => haiku(i, 'B')]))
  const a = lines.filter((_, k) => k % 2 === 0).filter(Boolean).flatMap(r => r.labels)
  const b = lines.filter((_, k) => k % 2 === 1).filter(Boolean).flatMap(r => r.labels)
  return { g, idx, a, b }
}, async ({ g, idx, a, b }) => {
  const bm = new Map(b.map(l => [l.id, l]))
  const agree = a.filter(l => bm.get(l.id)?.field === l.field).map(l => ({ id: l.id, field: l.field, how: '一致', reason: l.reason }))
  const agreed = new Set(agree.map(l => l.id))
  const ids = new Set([...a, ...b].map(l => l.id))
  const disputes = [...ids].filter(id => !agreed.has(id)).map(id => ({ id, A: a.find(l => l.id === id) ?? null, B: bm.get(id) ?? null }))
  if (!disputes.length) return { g, labels: agree, disputes: [] }
  const titles = idx.map(file).join(' ')
  const r = await agent(`あなたは Haiku 2系統の振り分けを突き合わせる係です。次のファイルを Read で読み、題名を確認してください: ${titles}
2系統が食い違った（または片方が欠けた）法律について、分野を1つ決めてください。
${RULES}
どちらにも決め手が無ければ「経済全体」に倒し、how を「経済全体に倒した」にする。決めたら how は「Sonnetが決定」。
食い違い(JSON): ${JSON.stringify(disputes)}`, { label: `sonnet:${g}`, phase: 'Sonnet 突き合わせ', model: 'sonnet', schema: DECIDED })
  return { g, labels: [...agree, ...(r ? r.labels : [])], disputes: r ? r.labels : [] }
})
const done = sonnet.filter(Boolean)
log(`Sonnet 完了 ${done.length}/${groups.length} 組`)
const decided = done.flatMap(s => s.disputes.filter(l => l.how === 'Sonnetが決定'))
const per = Math.ceil(decided.length / OPUS) || 1
const FIX = { type: 'object', properties: { fixes: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, field: { type: 'string', enum: FIELDS }, reason: { type: 'string' } }, required: ['id','field','reason'] } } }, required: ['fixes'] }
const opus = await parallel(Array.from({ length: OPUS }, (_, k) => decided.slice(k * per, (k + 1) * per)).filter(x => x.length).map((chunk, k) => () =>
  agent(`Sonnet が食い違いを決めた法律の分野を、分野をまたいで整合しているか確かめてください。題名は ${DIR}/b*.json にあります（id で探せる。Grep を使ってよい）。
${RULES}
同じ種類の法律が別の分野に割れている、特定の産業に寄せすぎている、などの誤りだけを直し、直したものだけ fixes に返す。直すものが無ければ空配列。
決定(JSON): ${JSON.stringify(chunk)}`, { label: `opus:${k}`, phase: 'Opus 整合確認', model: 'opus', schema: FIX })))
const fixes = opus.filter(Boolean).flatMap(r => r.fixes)
const final = new Map(done.flatMap(s => s.labels).map(l => [l.id, l]))
for (const f of fixes) final.set(f.id, { id: f.id, field: f.field, how: 'Opusが修正', reason: f.reason })
log(`確定 ${final.size} 本・Opus 修正 ${fixes.length} 本`)
return { labels: [...final.values()], groups: done.length, fixes: fixes.length }