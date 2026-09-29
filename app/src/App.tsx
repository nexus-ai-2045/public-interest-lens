import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, BookOpen, CheckCircle2, ChevronRight, Clock3, Info, Scale, SlidersHorizontal } from 'lucide-react';
import { actionKey, DOMAINS, RANKING_VERSION, ROLE_FACTOR, rankPeople, type Domain, type Period, type RankingOptions } from './ranking';
import { rankingDataset as data } from './ranking-data';

const domainLabels: Record<Domain | 'overall', string> = { economy: '経済成長', technology: '科学技術', fiscal: '財政', security: '安全保障', governance: '統治・実行力', overall: '総合' };
const roleLabels = { lead: '主導・決定', coauthor: '共同提出・具体的修正', vote: '確認できる個人の賛否', context: '関係情報のみ' };
const pendingDomains = new Set<Domain>(['fiscal', 'security', 'governance']);
const asOf = data.asOf;
type LocalInspection = { asOf: string; scope: string; assessedPeople: number; sourceRecords: number | null; sourceStatus: 'capped' | 'query_exhausted' | 'pages_captured'; held: { id: string; reason: string; sourceSpeechId: string | null; title: string | null; submittedAt: string | null; sourceUrl: string | null; voteUrl: string | null }[] };

function officialSangiinUrl(value: unknown): string | null {
  if (value == null || value === '') return null;
  if (typeof value !== 'string') throw new Error('公式資料URLが不正です');
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('公式資料URLが不正です'); }
  if (url.protocol !== 'https:' || url.hostname !== 'www.sangiin.go.jp' || url.username || url.password || url.port) throw new Error('公式資料URLが参議院のHTTPSではありません');
  return url.toString();
}

function parseLocalInspection(text: string): LocalInspection {
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== 'object') throw new Error('JSONの形式が不正です');
  const record = value as Record<string, unknown>;
  const coverage = record.coverage as Record<string, unknown> | undefined;
  if (record.schemaVersion !== 'ranking-dataset/v1' || record.fictional !== false || !coverage || typeof coverage !== 'object') throw new Error('実データ用 ranking-dataset/v1 ではありません');
  if (!['people', 'policies', 'involvements', 'evidence'].every(key => Array.isArray(record[key]))) throw new Error('必要な配列がありません');
  if (typeof record.asOf !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(record.asOf) || typeof coverage.scope !== 'string') throw new Error('基準日または収録範囲が不正です');
  if (!Number.isInteger(coverage.assessedPeople) || (coverage.assessedPeople as number) < 0 || !['capped', 'query_exhausted', 'pages_captured'].includes(coverage.sourceStatus as string)) throw new Error('取得・評価状態が不正です');
  if (coverage.sourceRecords != null && (!Number.isInteger(coverage.sourceRecords) || (coverage.sourceRecords as number) < 0)) throw new Error('取得件数が不正です');
  if (record.held !== undefined && !Array.isArray(record.held)) throw new Error('保留情報が不正です');
  const held = (record.held as unknown[] | undefined ?? []).map(item => {
    if (!item || typeof item !== 'object') throw new Error('保留情報が不正です');
    const entry = item as Record<string, unknown>;
    if (typeof entry.id !== 'string' || typeof entry.reason !== 'string' || !entry.reason.trim()) throw new Error('保留理由が不正です');
    const submittedAt = entry.submittedAt == null ? null : entry.submittedAt;
    if (submittedAt !== null && (typeof submittedAt !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(submittedAt) || Number.isNaN(Date.parse(submittedAt)) || new Date(submittedAt).toISOString().slice(0, 10) !== submittedAt)) throw new Error('議案提出日が不正です');
    return { id: entry.id.slice(0, 120), reason: entry.reason.slice(0, 500), sourceSpeechId: typeof entry.sourceSpeechId === 'string' ? entry.sourceSpeechId.slice(0, 120) : null, title: typeof entry.title === 'string' && entry.title.trim() ? entry.title.slice(0, 300) : null, submittedAt, sourceUrl: officialSangiinUrl(entry.sourceUrl), voteUrl: officialSangiinUrl(entry.voteUrl) };
  });
  return { asOf: record.asOf, scope: coverage.scope.slice(0, 300), assessedPeople: coverage.assessedPeople as number, sourceRecords: coverage.sourceRecords as number | null ?? null, sourceStatus: coverage.sourceStatus as LocalInspection['sourceStatus'], held };
}

function initialOptions(): RankingOptions {
  const params = new URLSearchParams(window.location.search);
  const domain = params.get('domain');
  const direction = params.get('direction');
  const period = params.get('period');
  const numberOr = (key: string, fallback: number) => { const value = Number(params.get(key)); return params.has(key) && Number.isFinite(value) && value >= 0 && value <= 100 ? value : fallback; };
  return {
    domain: domain === 'overall' || DOMAINS.includes(domain as Domain) ? domain as RankingOptions['domain'] : 'economy',
    direction: direction === 'benefit' ? 'benefit' : 'harm',
    period: period === '2' || period === '4' || period === '8' ? Number(period) as Period : period === 'cumulative' ? 'cumulative' : 4,
    asOf,
    weights: { economy: numberOr('economy', 70), technology: numberOr('technology', 30) },
  };
}

function App() {
  const [options, setOptions] = useState<RankingOptions>(initialOptions);
  const [query, setQuery] = useState(() => new URLSearchParams(window.location.search).get('q') ?? '');
  const [house, setHouse] = useState(() => new URLSearchParams(window.location.search).get('house') ?? 'all');
  const [roleClass, setRoleClass] = useState(() => new URLSearchParams(window.location.search).get('role') ?? 'all');
  const [selectedPersonId, setSelectedPersonId] = useState(() => new URLSearchParams(window.location.search).get('person') ?? '');
  const [selectedActionKey, setSelectedActionKey] = useState(() => new URLSearchParams(window.location.search).get('action') ?? '');
  const [advanced, setAdvanced] = useState(false);
  const [assessment, setAssessment] = useState<'actions' | 'outlook'>(() => new URLSearchParams(window.location.search).get('assessment') === 'outlook' ? 'outlook' : 'actions');
  const [inspection, setInspection] = useState<LocalInspection | null>(null);
  const [inspectionError, setInspectionError] = useState('');
  const rows = useMemo(() => rankPeople(data, options), [options]);
  const visible = rows.filter(row => row.person.name.includes(query.trim()) && (house === 'all' || row.person.house === house) && (roleClass === 'all' || row.person.roleClass === roleClass));
  const selected = visible.find(row => row.person.id === selectedPersonId) ?? visible[0];
  const related = data.involvements.filter(item => item.personId === selected?.person.id)
    .map(action => ({ action, policy: data.policies.find(item => item.id === action.policyId)! }))
    .sort((a, b) => b.action.actionDate.localeCompare(a.action.actionDate));
  const detail = related.find(item => actionKey(item.action) === selectedActionKey) ?? related[0];
  const evidenceIds = new Set(detail ? [...detail.policy.evidenceIds, ...detail.action.evidenceIds] : []);
  const evidence = data.evidence.filter(item => evidenceIds.has(item.id));
  const selectedContribution = selected?.contributions.find(item => item.policyId === detail?.policy.id);
  const assessed = rows.filter(row => row.score !== null).length;
  const weightTotal = options.weights.economy + options.weights.technology;
  const pending = pendingDomains.has(options.domain as Domain);

  useEffect(() => {
    const params = new URLSearchParams();
    params.set('domain', options.domain); params.set('direction', options.direction); params.set('period', String(options.period));
    if (query) params.set('q', query);
    if (house !== 'all') params.set('house', house);
    if (roleClass !== 'all') params.set('role', roleClass);
    if (selectedPersonId) params.set('person', selectedPersonId);
    if (selectedActionKey) params.set('action', selectedActionKey);
    if (assessment !== 'actions') params.set('assessment', assessment);
    if (options.domain === 'overall') { params.set('economy', String(options.weights.economy)); params.set('technology', String(options.weights.technology)); }
    window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }, [options, query, house, roleClass, selectedPersonId, selectedActionKey, assessment]);

  const change = <K extends keyof RankingOptions>(key: K, value: RankingOptions[K]) => setOptions(previous => ({ ...previous, [key]: value }));
  const inspectFile = async (file?: File) => {
    if (!file) return;
    try {
      if (file.size > 5_000_000) throw new Error('5MB以下のJSONを選んでください');
      const parsed = parseLocalInspection(await file.text());
      setInspection(parsed);
      setInspectionError('');
    } catch (error) {
      setInspection(null);
      setInspectionError(error instanceof Error ? error.message : 'ファイルを読み取れません');
    }
  };

  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark"><Scale size={18} /></span>国賊ランキング<span className="prototype-label">架空データ版</span></a><nav aria-label="主要ナビゲーション"><a href="#ranking">ランキング</a><a href="#person">人物と行動</a><a href="#method">評価方法</a></nav></header>
    <main id="top">
      <section className="hero"><div><p className="eyebrow">国会の記録から政策の影響をたどる</p><h1 aria-label="国賊ランキング"><span className="hero-title-lead">国賊</span><span className="hero-title-tail">ランキング</span></h1><p className="hero-lead">政治家の行動をたどり、国への貢献と悪影響を視点ごとに比べる。</p></div><div className="hero-note"><Info size={22} /><p><strong>全人物・政策・資料が架空です。</strong><br />表示と算定を確かめるローカルMVPです。実在人物の評価や国政の事実を示していません。</p></div></section>
      <section className="scope-strip" aria-label="収録範囲"><span><CheckCircle2 size={17} />算定版 {RANKING_VERSION}</span><span><Clock3 size={17} />基準日 {asOf}</span><span>{data.coverage.scope} / 算定可能 {assessed}人</span><span>国政全体の収録率：未確認</span></section>
      <section id="ranking" className="panel ranking-panel"><div className="section-head"><div><p className="section-kicker">視点を選んで比較</p><h2>人物ランキング</h2></div><span className="pill">条件はURLに保存</span></div>
        <div className="primary-controls">
          <label>評価分野<select aria-label="評価分野" value={options.domain} onChange={event => change('domain', event.target.value as RankingOptions['domain'])}><option value="economy">経済成長</option><option value="technology">科学技術</option><option value="fiscal">財政（準備中）</option><option value="security">安全保障（準備中）</option><option value="governance">統治・実行力（準備中）</option><option value="overall">総合（詳細設定）</option></select></label>
          <label>比較期間<select aria-label="比較期間" value={options.period} onChange={event => change('period', event.target.value === 'cumulative' ? 'cumulative' : Number(event.target.value) as Period)}><option value="2">直近2年</option><option value="4">直近4年</option><option value="8">直近8年</option><option value="cumulative">累積</option></select></label>
          <div className="direction-control" aria-label="影響方向"><span>影響の方向</span><div><button type="button" className={options.direction === 'harm' ? 'active harm' : ''} aria-pressed={options.direction === 'harm'} onClick={() => change('direction', 'harm')}>悪影響</button><button type="button" className={options.direction === 'benefit' ? 'active benefit' : ''} aria-pressed={options.direction === 'benefit'} onClick={() => change('direction', 'benefit')}>貢献</button></div></div>
        </div>
        <div className="secondary-controls"><label className="search-control">人物名で検索<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="名前を入力" /></label><button type="button" className="settings-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><SlidersHorizontal size={17} />詳細設定</button></div>
        {advanced && <div className="advanced-controls"><label>議院<select value={house} onChange={event => setHouse(event.target.value)}><option value="all">すべて</option><option value="衆議院">衆議院</option><option value="参議院">参議院</option></select></label><label>立場<select value={roleClass} onChange={event => setRoleClass(event.target.value)}><option value="all">すべて</option><option value="一般議員">一般議員</option><option value="大臣">大臣</option><option value="非在職">非在職</option></select></label><label>評価の種類<select value={assessment} onChange={event => setAssessment(event.target.value as 'actions' | 'outlook')}><option value="actions">行動・実績</option><option value="outlook">見込み・公約（未評価）</option></select></label>{options.domain === 'overall' && <div className="weight-controls"><p>経済70％・技術30％は製品上の初期設定</p><label>経済の重み <input type="range" min="0" max="100" value={options.weights.economy} onChange={event => change('weights', { ...options.weights, economy: Number(event.target.value) })} /><output>{options.weights.economy}</output></label><label>技術の重み <input type="range" min="0" max="100" value={options.weights.technology} onChange={event => change('weights', { ...options.weights, technology: Number(event.target.value) })} /><output>{options.weights.technology}</output></label></div>}</div>}
        <p className="view-summary" role="status" aria-live="polite">現在の比較条件：{domainLabels[options.domain]}・{options.period === 'cumulative' ? '累積' : `直近${options.period}年`}・{options.direction === 'harm' ? '悪影響' : '貢献'}。{assessment === 'outlook' ? '公約・見込みは未評価' : `算定可能${visible.filter(row => row.score !== null).length}人`}</p>
        {pending && <p className="state-banner" role="status">{domainLabels[options.domain]}は評価準備中です。点数0ではなく未評価として表示します。</p>}
        {assessment === 'outlook' && <p className="state-banner" role="status">見込み・公約の検証データは未収録です。行動・実績の順位とは混ぜません。</p>}
        {options.domain === 'overall' && weightTotal === 0 && <p className="state-banner" role="status">重みがすべて0のため、全員未評価です。</p>}
          <div className="table-wrap"><table><caption className="sr-only">{domainLabels[options.domain]}・{options.direction === 'harm' ? '悪影響' : '貢献'}の順位。未評価は影響なしを意味しません。</caption><thead><tr><th scope="col">順位</th><th scope="col">人物</th><th scope="col">評価点</th><th scope="col">算定政策</th><th scope="col">保留</th></tr></thead><tbody>{visible.map(row => <tr key={row.person.id} className={[selected?.person.id === row.person.id ? 'selected-row' : '', row.rank === 1 && row.score !== null && assessment !== 'outlook' && !pending ? 'top-ranked-row' : ''].filter(Boolean).join(' ')}><td>{assessment === 'outlook' ? '—' : row.rank ?? '—'}</td><td><button className="person-select" aria-pressed={selected?.person.id === row.person.id} onClick={() => { setSelectedPersonId(row.person.id); setSelectedActionKey(''); document.getElementById('person')?.scrollIntoView({ behavior: 'smooth' }); }}>{row.person.name}<ChevronRight size={15} /></button><small>{row.person.house} · {row.person.district}</small></td><td><strong className="score">{assessment === 'outlook' || pending ? '未評価' : row.score === null ? '未評価' : row.score.toFixed(2)}</strong></td><td>{assessment === 'outlook' || pending ? '—' : row.eligibleCount}</td><td>{assessment === 'outlook' ? '—' : row.heldCount}</td></tr>)}</tbody></table></div>
        {!visible.length && <p className="empty-state" role="status">該当する人物がいません。検索・絞り込み条件を変更してください。</p>}
        <p className="method-note">収録した架空の行動だけを集計。未評価は貢献・悪影響がないという意味ではありません。政策の長期影響を毎年重複加算しません。</p>
      </section>
      <section id="person" className="person-section"><div className="section-head"><div><p className="section-kicker">何をしたか、資料までたどる</p><h2>{selected ? `${selected.person.name}の行動` : '人物と行動'}</h2></div><a className="back-to-ranking" href="#ranking">ランキングへ戻る</a></div>
        {selected && <div className="person-summary panel"><div><span className="person-avatar">{selected.person.name.slice(-2)}</span><div><h3>{selected.person.name}</h3><p>{selected.person.house} · {selected.person.district} · {selected.person.roleClass}</p></div></div><p>この画面の対象行動 {related.length}件。活動全体の網羅性は未確認です。過去の行動も履歴として表示します。</p></div>}
        {!detail ? <p className="panel empty-state">表示できる行動がありません。記録なしを活動なしとは判定しません。</p> : <div className="evidence-grid"><aside className="panel action-list" aria-label="選択人物の行動">{related.map(({ action, policy }) => <button key={actionKey(action)} className={detail.action === action ? 'selected' : ''} aria-pressed={detail.action === action} onClick={() => setSelectedActionKey(actionKey(action))}><small>{action.actionDate} · {domainLabels[policy.domain]}</small><strong>{policy.title}</strong><span>{action.description}</span></button>)}</aside><article className="panel evidence-detail"><div className="detail-meta"><span className={`status-badge ${detail.policy.reviewStatus}`}>{detail.policy.reviewStatus === 'reviewed' ? '架空設定内で評価可能' : '評価保留'}</span><span>{detail.action.actionDate}</span></div><h3>{detail.policy.title}</h3><p>{detail.policy.rationale}</p><dl className="policy-metrics"><div><dt>政策影響の仮置き段階</dt><dd>{detail.policy.impact} / 3</dd></div><div><dt>確認した行動</dt><dd>{roleLabels[detail.action.role]}</dd></div><div><dt>関与係数</dt><dd>{ROLE_FACTOR[detail.action.role]}</dd></div><div><dt>現在の条件での寄与点</dt><dd>{assessment === 'outlook' ? '公約・見込みは未評価' : pending ? '評価準備中' : selectedContribution && selectedContribution.actionDate === detail.action.actionDate && selectedContribution.role === detail.action.role ? selectedContribution.score.toFixed(2) : '採点には重複算入しない'}</dd></div></dl><p><strong>行動：</strong>{detail.action.description}</p><p><strong>反証：</strong>{detail.policy.counterEvidence}</p><p><strong>別の説明：</strong>{detail.policy.alternativeExplanation}</p><p className="exclusion-note">この係数は創作の動作検証値です。因果確率やGDP損失額ではありません。</p></article><aside className="panel source-panel"><p className="section-kicker">根拠資料</p><h3>根拠を確認</h3>{evidence.map(item => <article className="source-card" key={item.id}><span className={`status-badge ${item.kind}`}>{item.kind === 'verified' ? '架空設定内で確認済み' : '未確認'}</span><strong>{item.title}</strong><small>{item.date}</small><p>{item.summary}</p><code>{item.source}</code>{item.url && <a href={item.url} target="_blank" rel="noreferrer">原資料を開く <ArrowUpRight size={14} /></a>}</article>)}<p className="timeline-note">実在する原資料へのリンクはありません。資料公開日、取得日、行動日は本番データで別々に保持します。</p></aside></div>}
      </section>
      <section id="method" className="panel method-panel"><div className="section-head"><div><p className="section-kicker">評価方法・更新履歴</p><h2>行動の事実と、影響の評価を分ける</h2></div><BookOpen size={22} /></div><div className="method-columns"><p>個人の採決、法案提出・修正、政策決定を根拠付きで記録します。所属・訪問・発言だけでは得点にしません。政策ごとの本人の複数行動は最大の関与を一度だけ集計します。</p><p>貢献と悪影響は独立した順位です。影響の方向・大きさや個人の関与を判断できない政策は保留します。公約と見込み評価は実績順位へ混ぜません。</p></div><p className="method-formula">政策影響段階（1〜3） × 関与係数（主導1、共同0.5、個人賛否0.25） × 分野の重み。表示点は小数第2位に丸め、同点は同順位。</p><p>画面は架空データ専用です。対象選挙の実際の候補者名簿・資料収集・実人物の評価・自動更新・公開審査は未接続です。順位は比較条件に依存します。</p><p className="version">算定版 {RANKING_VERSION} · {data.coverage.sourceStatus}</p></section>
      <section className="panel local-inspection" aria-label="資料の取得状況"><div><p className="section-kicker">資料の取得状況</p><h2>取得結果をローカルで確認</h2><p>収集器が出力した current.json を、このブラウザだけで読み取ります。実人物の点数や順位は作りません。</p></div><label>ローカル評価データJSONを開く<input type="file" accept=".json,application/json" aria-label="ローカル評価データJSONを開く" onChange={event => void inspectFile(event.target.files?.[0])} /></label>{inspectionError && <p className="inspection-error" role="alert">読み取り失敗：{inspectionError}</p>}{inspection && <div className="inspection-result"><h3>ローカル実データの確認</h3><p>基準日 {inspection.asOf} · {inspection.scope} · 算定可能 {inspection.assessedPeople}人 · 取得記録 {inspection.sourceRecords ?? '不明'}件</p><p className="inspection-state">{inspection.sourceStatus === 'capped' ? '資料取得は上限到達' : inspection.sourceStatus === 'pages_captured' ? '指定した公式議案ページを取得、全件網羅ではない' : '指定範囲の取得完了'}。国政全体の網羅を意味しません。</p><h4>保留 {inspection.held.length}件</h4>{inspection.held.length ? <ul>{inspection.held.map(item => <li key={item.id}>{item.title && <strong>{item.title}</strong>}{item.submittedAt && <small>提出日 {item.submittedAt}</small>}<span>{item.reason}</span>{item.sourceSpeechId && <small>資料ID {item.sourceSpeechId}</small>}{item.sourceUrl && <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer">公式資料を開く <ArrowUpRight size={13} /></a>}{item.voteUrl && <a href={item.voteUrl} target="_blank" rel="noopener noreferrer">採決資料を開く <ArrowUpRight size={13} /></a>}</li>)}</ul> : <p>保留記録はありません。評価可能性は収録範囲で確認してください。</p>}<p>ファイル内容は送信・保存せず、画面更新で消えます。上の架空ランキングはこのファイルを採点していません。</p></div>}</section>
    </main><footer><span><Scale size={16} />国賊ランキング</span><span>架空データによるローカル動作検証版</span></footer>
  </div>;
}

export default App;
