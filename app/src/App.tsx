import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, BookOpen, ChevronRight, FileText, Info, Scale, Search, SlidersHorizontal } from 'lucide-react';
import { actionKey, actionMatchesView, RANKING_VERSION, ROLE_FACTOR, rankPeople, type Domain, type Period, type RankingOptions } from './ranking';
import { rankingDataset as data } from './ranking-data';
import { PolicyFlow } from './PolicyFlow';
import { EvidenceMotion } from './EvidenceMotion';
import { ExpandableControls } from './ExpandableControls';
import { readViewState, serializeViewState, type ViewState } from './view-state';
import { parseLocalInspection, type LocalInspection } from './local-inspection';
import { ReadableEvidencePanel } from './ReadableEvidencePanel';
import { getPersonSummaries } from './person-summary';
import { PersonSummary } from './PersonSummary';
import { getRelatedActions, resolveView } from './view-resolution';

const domainLabels: Record<Domain | 'overall', string> = { economy: '経済成長', technology: '科学技術', fiscal: '財政', security: '安全保障', governance: '統治・実行力', overall: '総合' };
const roleLabels = { lead: '主導・決定', coauthor: '共同提出・具体的修正', vote: '確認できる個人の賛否', context: '関係情報のみ' };
const pendingDomains = new Set<Domain>(['fiscal', 'security', 'governance']);
const asOf = data.asOf;

function restoreUrlView(): ViewState {
  const search = window.location.search;
  return resolveView(data, readViewState(search, asOf), new URLSearchParams(search).has('history') ? 'interaction' : 'url');
}

function App() {
  const [view, setView] = useState(restoreUrlView);
  const viewRef = useRef(view);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [desktop, setDesktop] = useState(() => window.matchMedia('(min-width: 1100px)').matches);
  const [inspection, setInspection] = useState<LocalInspection | null>(null);
  const [inspectionError, setInspectionError] = useState('');
  const inspectionRequest = useRef(0);
  const { options, query, house, roleClass, assessment } = view;
  const rows = useMemo(() => rankPeople(data, options), [options]);
  const summaries = useMemo(() => getPersonSummaries(data, options, assessment), [options, assessment]);
  const visible = rows.filter(row => row.person.name.includes(query.trim()) && (house === 'all' || row.person.house === house) && (roleClass === 'all' || row.person.roleClass === roleClass));
  const selected = visible.find(row => row.person.id === view.selectedPersonId);
  const related = getRelatedActions(data, selected?.person.id ?? '', options, view.history);
  const detail = related.find(item => actionKey(item.action) === view.selectedActionKey);
  const detailOutsideView = detail && !actionMatchesView(detail.action, detail.policy, options);
  const evidenceIds = new Set(detail ? [...detail.policy.evidenceIds, ...detail.action.evidenceIds] : []);
  const evidence = data.evidence.filter(item => evidenceIds.has(item.id));
  const contribution = selected?.contributions.find(item => item.policyId === detail?.policy.id);
  const pending = pendingDomains.has(options.domain as Domain);
  const actionCanScore = useMemo(() => detail ? rankPeople({ ...data, involvements: [detail.action] }, options).some(row => row.person.id === detail.action.personId && row.score !== null) : false, [detail?.action, options]);
  const detailScoreLabel = assessment === 'outlook' ? '公約・見込みは未評価です' : pending ? '評価準備中' : detail?.policy.reviewStatus === 'pending' ? '影響の根拠が未検証のため、評価を保留しています' : !actionCanScore ? '現在の条件では未評価です' : contribution && detail && contribution.actionKey === actionKey(detail.action) ? contribution.score.toFixed(2) : 'この行動は重複して加算しません。';
  const productTitle = options.direction === 'harm' ? '国賊ランキング' : '国士ランキング';
  useEffect(() => { document.title = productTitle; }, [productTitle]);

  const saveUrl = (next: ViewState, mode: 'push' | 'replace') => {
    const search = serializeViewState(next);
    const url = `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`;
    if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) window.history[mode === 'push' ? 'pushState' : 'replaceState'](null, '', url);
  };
  const update = (patch: Partial<ViewState>, mode: 'push' | 'search' = 'push') => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const next = resolveView(data, { ...viewRef.current, ...patch });
    viewRef.current = next;
    setView(next);
    if (mode === 'search') searchTimer.current = setTimeout(() => { saveUrl(viewRef.current, 'replace'); searchTimer.current = null; }, 250);
    else saveUrl(next, 'push');
  };
  const change = <K extends keyof RankingOptions>(key: K, value: RankingOptions[K]) => update({ options: { ...viewRef.current.options, [key]: value }, selectedPersonId: '', selectedActionKey: '', selectedPolicyId: '' });
  const selectPerson = (id: string) => {
    update({ selectedPersonId: id, selectedActionKey: '', selectedPolicyId: '', tab: 'actions' });
    if (!desktop) document.getElementById('person')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };
  const changeHistory = (history: ViewState['history']) => update({ history, selectedActionKey: '', selectedPolicyId: '', selectedEvidenceId: '' });
  const moveTab = (event: { key: string; preventDefault(): void }, current: ViewState['tab']) => {
    const order: ViewState['tab'][] = ['actions', 'policy', 'evidence'];
    const index = order.indexOf(current);
    const next = event.key === 'ArrowRight' ? (index + 1) % order.length : event.key === 'ArrowLeft' ? (index + order.length - 1) % order.length : event.key === 'Home' ? 0 : event.key === 'End' ? order.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    update({ tab: order[next] });
    document.getElementById(`tab-${order[next]}`)?.focus();
  };
  useEffect(() => {
    saveUrl(viewRef.current, 'replace');
    const restore = () => {
      if (searchTimer.current) { clearTimeout(searchTimer.current); searchTimer.current = null; }
      const restored = restoreUrlView();
      viewRef.current = restored;
      setView(restored);
    };
    const media = window.matchMedia('(min-width: 1100px)');
    const resize = () => setDesktop(media.matches);
    window.addEventListener('popstate', restore);
    media.addEventListener('change', resize);
    return () => { window.removeEventListener('popstate', restore); media.removeEventListener('change', resize); if (searchTimer.current) clearTimeout(searchTimer.current); inspectionRequest.current++; };
  }, []);
  const inspectFile = async (file?: File) => {
    const request = ++inspectionRequest.current;
    if (!file) return;
    try {
      if (file.size > 5_000_000) throw new Error('5MB以下のJSONを選んでください');
      const parsed = parseLocalInspection(await file.text());
      if (request !== inspectionRequest.current) return;
      setInspection(parsed); setInspectionError('');
    } catch (error) {
      if (request !== inspectionRequest.current) return;
      setInspectionError(error instanceof Error ? error.message : 'ファイルを読み取れません');
    }
  };
  const sources = <aside className="source-panel" aria-label="選択行動の根拠資料"><h3>根拠資料</h3>{evidence.map(item => <article className={`source-record ${view.tab === 'evidence' && view.selectedEvidenceId === item.id ? 'selected-source' : ''}`} data-evidence-id={item.id} key={item.id}><div className="source-heading"><FileText size={17} /><strong>{item.title}</strong></div><small>{item.date} / {item.kind === 'verified' ? '架空設定内で確認済み' : item.kind === 'computed' ? '機械計算' : item.kind === 'ai' ? 'AI解釈' : '未確認'}</small>{view.tab === 'evidence' && <><button className="source-select" aria-pressed={view.selectedEvidenceId === item.id} onClick={() => update({ selectedEvidenceId: item.id })}>この根拠を選択</button><p>{item.summary}</p></>}<code>{item.source}</code>{view.tab === 'evidence' && <dl className="source-provenance"><div><dt>観測時刻</dt><dd>未収録</dd></div><div><dt>照合値（SHA-256）</dt><dd>{item.sha256 ?? '未収録'}</dd></div></dl>}{item.url && <a href={item.url} target="_blank" rel="noreferrer">原資料を開く <ArrowUpRight size={14} /></a>}</article>)}<p className="fine-note">表示している資料はすべて架空です。実在の原資料へのリンクはありません。資料公開日・取得日・行動日は別の情報です。</p></aside>;

  return <div className="app-shell" data-theme={options.direction === 'harm' ? 'dark' : 'light'} data-direction={options.direction}>
    <header className="topbar"><a className="brand" href="#top"><Scale size={23} /><h1>{productTitle}</h1><span className="prototype-label">架空データ版</span></a><nav aria-label="主要ナビゲーション"><a href="#ranking" className="nav-active">ランキング</a><a href="#method">評価方法</a></nav></header>
    <main id="top">
      <section className="comparison-heading"><h2>{domainLabels[options.domain]}への{options.direction === 'harm' ? '悪影響' : '貢献'}</h2><p className="fiction-warning"><Info size={17} />全人物・政策・資料が架空です。</p></section>
      <section className="filter-bar" aria-label="比較条件">
        <label>評価分野<select aria-label="評価分野" value={options.domain} onChange={event => change('domain', event.target.value as RankingOptions['domain'])}><option value="economy">経済成長</option><option value="technology">科学技術</option><option value="fiscal">財政（準備中）</option><option value="security">安全保障（準備中）</option><option value="governance">統治・実行力（準備中）</option><option value="overall">総合（詳細設定）</option></select></label>
        <label>比較期間<select aria-label="比較期間" value={options.period} onChange={event => change('period', event.target.value === 'cumulative' ? 'cumulative' : Number(event.target.value) as Period)}><option value="2">直近2年</option><option value="4">直近4年</option><option value="8">直近8年</option><option value="cumulative">累積</option></select></label>
        <div className="direction-control" aria-label="影響方向"><span>影響の方向</span><div><button className={options.direction === 'harm' ? 'active harm' : ''} aria-pressed={options.direction === 'harm'} onClick={() => change('direction', 'harm')}>悪影響</button><button className={options.direction === 'benefit' ? 'active benefit' : ''} aria-pressed={options.direction === 'benefit'} onClick={() => change('direction', 'benefit')}>貢献</button></div></div>
        <label className="search-control"><span className="sr-only">人物名で検索</span><Search size={17} /><input type="search" aria-label="人物名で検索" value={query} onChange={event => update({ query: event.target.value }, 'search')} placeholder="人物名で検索" /></label>
        <button id="advanced-toggle" className="settings-button" aria-controls="advanced-settings" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><SlidersHorizontal size={17} /><span>詳細設定</span></button>
      </section>
      <ExpandableControls expanded={advanced}><section className="advanced-controls" aria-label="詳細な比較条件"><label>議院<select value={house} onChange={event => update({ house: event.target.value })}><option value="all">すべて</option><option value="衆議院">衆議院</option><option value="参議院">参議院</option></select></label><label>立場<select value={roleClass} onChange={event => update({ roleClass: event.target.value })}><option value="all">すべて</option><option value="一般議員">一般議員</option><option value="大臣">大臣</option><option value="非在職">非在職</option></select></label><label>評価の種類<select value={assessment} onChange={event => update({ assessment: event.target.value as ViewState['assessment'] })}><option value="actions">行動・実績</option><option value="outlook">見込み・公約（未評価）</option></select></label>{options.domain === 'overall' && <div className="weight-controls"><p>経済70％・技術30％は製品上の初期設定です。</p><label>経済の重み<input type="range" min="0" max="100" value={options.weights.economy} onChange={event => change('weights', { ...options.weights, economy: Number(event.target.value) })} /><output>{options.weights.economy}</output></label><label>技術の重み<input type="range" min="0" max="100" value={options.weights.technology} onChange={event => change('weights', { ...options.weights, technology: Number(event.target.value) })} /><output>{options.weights.technology}</output></label></div>}</section></ExpandableControls>
      <div className="workspace-grid console-grid">
        <section id="ranking" className="ranking-pane ranking-panel console-pane"><div className="pane-heading"><h2>人物ランキング</h2><p className="view-summary" role="status" aria-live="polite">現在の比較条件：{domainLabels[options.domain]}・{options.period === 'cumulative' ? '累積' : `直近${options.period}年`}・{options.direction === 'harm' ? '悪影響' : '貢献'}。{assessment === 'outlook' ? '公約・見込みは未評価' : `算定可能${visible.filter(row => row.score !== null).length}人`}</p></div>
          {pending && <p className="state-banner" role="status">{domainLabels[options.domain]}は評価準備中です。点数0ではなく未評価として表示します。</p>}{assessment === 'outlook' && <p className="state-banner" role="status">見込み・公約の検証データは未収録です。行動・実績の順位とは混ぜません。</p>}{options.domain === 'overall' && options.weights.economy + options.weights.technology === 0 && <p className="state-banner" role="status">重みがすべて0のため、全員未評価です。</p>}
          <div className="ranking-scroll"><table><caption className="sr-only">{domainLabels[options.domain]}・{options.direction === 'harm' ? '悪影響' : '貢献'}の順位。未評価は影響なしを意味しません。</caption><thead><tr><th scope="col">順位</th><th scope="col">人物</th><th scope="col">評価点</th></tr></thead><tbody>{visible.map(row => <tr key={row.person.id} className={selected?.person.id === row.person.id ? 'selected-row' : ''}><td>{assessment === 'outlook' ? '—' : row.rank ?? '—'}</td><td><button className="person-select" aria-pressed={selected?.person.id === row.person.id} onClick={() => selectPerson(row.person.id)}><span className="person-dot" aria-hidden="true" /><span>{row.person.name}</span><ChevronRight size={13} /></button><span className="person-trend">{summaries.get(row.person.id)?.label}</span><small>{row.person.house} / {row.person.district}</small><small>算定政策 {assessment === 'outlook' || pending ? '—' : row.eligibleCount} / 保留 {assessment === 'outlook' ? '—' : row.heldCount}</small></td><td><strong className={`score ${options.direction === 'harm' ? 'harm-score' : 'benefit-score'} ${assessment === 'outlook' || pending || row.score === null ? 'unassessed' : ''}`}>{assessment === 'outlook' || pending || row.score === null ? '未評価' : row.score.toFixed(2)}</strong></td></tr>)}</tbody></table></div>
          {!visible.length && <p className="empty-state" role="status">該当する人物がいません。検索・絞り込み条件を変更してください。</p>}<p className="ranking-note">未評価 ≠ 影響なし<br />収録した架空の行動だけを算定しています。国政全体の収録率は未確認です。</p>
        </section>
        <section id="person" className="person-pane inspector console-pane"><div className="pane-heading inspector-heading"><h2>{selected ? `${selected.person.name}の行動` : '人物と行動'}</h2>{selected && <p>{selected.person.house} / {selected.person.district} / {selected.person.roleClass}</p>}<a className="back-to-ranking" href="#ranking">ランキングへ戻る</a></div><div className="inspector-tabs" role="tablist" aria-label="人物詳細">{(['actions', 'policy', 'evidence'] as const).map(tab => <button key={tab} id={`tab-${tab}`} role="tab" tabIndex={view.tab === tab ? 0 : -1} onKeyDown={event => moveTab(event, tab)} aria-selected={view.tab === tab} aria-controls="inspector-content" onClick={() => update({ tab })}>{({ actions: '行動', policy: '政策', evidence: '根拠' })[tab]}</button>)}</div>
          <div className="inspector-content" id="inspector-content" role="tabpanel" aria-labelledby={`tab-${view.tab}`}>
            {selected && summaries.get(selected.person.id) && <PersonSummary summary={summaries.get(selected.person.id)!} context={`${domainLabels[options.domain]}・${options.period === 'cumulative' ? '累積' : `直近${options.period}年`}・${assessment === 'outlook' ? '見込み・公約（未評価）' : '行動・実績'}`} />}
            {selected && <div className="history-controls" aria-label="行動の表示範囲"><button aria-pressed={view.history === 'view'} onClick={() => changeHistory('view')}>現在の条件</button><button aria-pressed={view.history === 'all'} onClick={() => changeHistory('all')}>全履歴</button></div>}
            <EvidenceMotion stateKey={`${view.selectedPersonId}:${view.selectedActionKey}:${view.selectedEvidenceId}:${view.tab}:${view.history}:${assessment}:${options.direction}`} selectionKey={`${view.selectedPersonId}:${view.selectedActionKey}:${view.selectedEvidenceId}:${assessment}:${options.domain}:${options.period}:${options.direction}:${options.weights.economy}:${options.weights.technology}`} navigationKey={`${view.tab}:${view.history}`}>
            {!detail ? <div className="empty-state tree-empty" role="status"><p>{view.history === 'view' ? '現在の条件に合う行動がありません。' : '表示できる行動がありません。'}</p><p className="fine-note">記録なしを活動なしとは判定しません。</p>{selected && view.history === 'view' && <button onClick={() => changeHistory('all')}>全履歴を見る</button>}</div> : <>
              <PolicyFlow data={data} related={related} options={options} selectedActionKey={view.selectedActionKey} selectedPolicyId={view.selectedPolicyId} selectedEvidenceId={view.tab === 'evidence' ? view.selectedEvidenceId : ''} onSelect={update} />
              {detailOutsideView && <p className="outside-view-note" role="status">選択中の行動は現在の条件外です。全履歴として表示しており、現在の順位には算入していません。</p>}
              {view.tab !== 'evidence' && <article className="evidence-detail"><h3>選択中の行動の評価</h3><dl className="policy-metrics"><div><dt>政策影響の仮置き段階</dt><dd>{detail.policy.impact} / 3</dd></div><div><dt>確認した行動</dt><dd>{roleLabels[detail.action.role]}</dd></div><div><dt>関与係数</dt><dd>{ROLE_FACTOR[detail.action.role]}</dd></div><div><dt>現在の条件での寄与点</dt><dd>{detailScoreLabel}</dd></div></dl><p className="fine-note">同じ政策の行動は重複加算しません。係数は創作の動作検証値で、因果確率やGDP損失額ではありません。</p><h3>確認した行動</h3><p>{detail.action.description}</p><h3>評価理由</h3><p>{detail.policy.rationale}</p><h3>反証</h3><p className="counter-evidence">{detail.policy.counterEvidence}</p><h3>別の説明</h3><p>{detail.policy.alternativeExplanation}</p>{view.tab === 'policy' && <p className="policy-context">評価分野：{domainLabels[detail.policy.domain]} / 影響方向：{detail.policy.direction === 'harm' ? '悪影響' : '貢献'}。これは政策単位の評価で、人格への評価ではありません。</p>}</article>}
              {sources}
            </>}{selected && <p className="fine-note">{view.history === 'all' ? '全履歴' : '現在の条件'}の対象行動 {related.length}件です。活動全体の網羅性は未確認です。</p>}<p className="inspector-warning"><Info size={16} />表示している資料はすべて架空です。実在人物の評価ではありません。</p>
            </EvidenceMotion>
          </div>
        </section>
      </div>
      <section id="method" className="method-panel lower-panel"><div className="lower-heading"><BookOpen size={20} /><h2>行動の事実と、影響の評価を分ける</h2></div><div className="method-columns"><p>個人の採決、法案提出・修正、政策決定を根拠付きで記録します。所属・訪問・発言だけでは得点にしません。政策ごとの本人の複数行動は最大の関与を一度だけ集計します。</p><p>貢献と悪影響は独立した順位です。影響の方向・大きさや個人の関与を判断できない政策は保留します。公約と見込み評価は実績順位へ混ぜません。</p></div><p className="method-formula">政策影響段階（1〜3） × 関与係数（主導1、共同0.5、個人賛否0.25） × 分野の重み。表示点は小数第2位に丸め、同点は同順位とします。</p><p className="fine-note">画面は架空データ専用です。対象選挙の実際の候補者名簿・資料収集・実人物の評価・自動更新・公開審査は未接続です。順位は比較条件に依存します。</p></section>
      <section className="local-inspection lower-panel" aria-label="資料の取得状況"><div><h2>取得結果をローカルで確認</h2><p>収集器が出力した current.json を、このブラウザだけで読み取ります。実人物の点数や順位は作りません。</p></div><label className="file-control">ローカル評価データJSONを開く<input type="file" accept=".json,application/json" aria-label="ローカル評価データJSONを開く" onChange={event => void inspectFile(event.target.files?.[0])} /></label>{inspectionError && <p className="inspection-error" role="alert">読み取り失敗：{inspectionError}{inspection && '。直前に読み取れた結果を保持しています。'}</p>}{inspection && <div className="inspection-result"><h3>ローカル実データの確認</h3><div className="inspection-summary"><span>基準日 {inspection.asOf}</span><span>{inspection.scope}</span><span>算定可能 {inspection.assessedPeople}人</span><span>取得記録 {inspection.sourceRecords ?? '不明'}件</span></div><p className="inspection-state">{inspection.sourceStatus === 'capped' ? '資料取得は上限に到達しています' : inspection.sourceStatus === 'pages_captured' ? '指定した公式議案ページを取得していますが、全件を網羅していません' : '指定範囲の取得が完了しています'}。国政全体の網羅を意味しません。</p><h4>保留 {inspection.held.length}件</h4>{inspection.held.length ? <ul>{inspection.held.map(item => <li key={item.id}>{item.title && <strong>{item.title}</strong>}{item.submittedAt && <small>提出日 {item.submittedAt}</small>}<span>{item.reason}</span>{item.sourceSpeechId && <small>資料ID {item.sourceSpeechId}</small>}<small>観測時刻 {item.observedAt ?? '不明'}</small><small>照合値（SHA-256）{item.sha256 ?? '不明'}</small>{item.sourceUrl && <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer">公式資料を開く <ArrowUpRight size={13} /></a>}{item.voteUrl && <a href={item.voteUrl} target="_blank" rel="noopener noreferrer">採決資料を開く <ArrowUpRight size={13} /></a>}</li>)}</ul> : <p>保留記録はありません。評価可能性は収録範囲で確認してください。</p>}<p className="fine-note">ファイル内容は送信・保存せず、画面更新で消えます。上の架空ランキングはこのファイルを採点していません。</p></div>}</section>
      {inspection?.readableEvidence && <div className="local-inspection lower-panel inspection-result"><ReadableEvidencePanel data={inspection.readableEvidence} /></div>}
    </main><footer><span>算定版 {RANKING_VERSION}</span><span>基準日 {asOf} / 算定可能 {rows.filter(row => row.score !== null).length}人 / {data.coverage.scope}</span></footer>
  </div>;
}

export default App;
