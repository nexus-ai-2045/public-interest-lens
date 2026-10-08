import { useEffect, useMemo, useRef, useState } from 'react';
import type { QuoteRef } from './evidence-evaluation';
import { availableRealRelease, createReleaseLoader, readRealRoute, realRouteLocation, recordedIdentityCoverage, realActionHeading, REAL_RELEASE_MAX_BYTES, type RealRelease, type RealRoute } from './real-release-view';
import { ProductHeader } from './ProductHeader';
import { evaluationStage } from './evaluation-stage';
import { RealRecordsPage } from './RealRecordsPage';
import { parsePolicyCatalog, type PolicyCatalog } from './policy-context';
import { EconomyPage } from './EconomyPage';
import { PoliciesPage } from './PoliciesPage';

function Quotes({ quotes, release }: { quotes: QuoteRef[]; release: RealRelease }) {
  return <ul className="real-quotes">{quotes.map((q, index) => {
    const m = release.input.evidenceEvaluation.materials.find(item => item.id === q.materialId)!;
    return <li key={`${q.materialId}:${q.start}:${index}`}><blockquote style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{q.text}</blockquote><p>取得日時：{m.observedAt}</p><details><summary>検証用の情報</summary><p>引用の位置：{q.start}〜{q.end}</p><p style={{ overflowWrap: 'anywhere' }}>原本の照合値：{m.originalHash}</p></details><a href={m.url} target="_blank" rel="noopener noreferrer">原資料を開く</a></li>;
  })}</ul>;
}
export function RealEvaluationPanel({ route, navigate }: { route: RealRoute; navigate: (route: RealRoute) => void }) {
  const [stored, setStored] = useState<RealRelease | null>(null);
  const [catalog, setCatalog] = useState<PolicyCatalog | null>(null);
  const [error, setError] = useState('');
  const [personSearch, setPersonSearch] = useState('');
  const autoRequest = useRef<AbortController | null>(null);
  const release = availableRealRelease(route, stored);
  useEffect(() => {
    if (!release || !import.meta.env.DEV) return;
    const controller = new AbortController();
    void fetch(`/__local__/policy-context?release=${release.releaseId}`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => { if (!response.ok) throw new Error('Unavailable'); return parsePolicyCatalog(await response.text(), release.releaseId); })
      .then(value => { if (!controller.signal.aborted) setCatalog(value); })
      .catch(() => { if (!controller.signal.aborted) setCatalog(null); });
    return () => controller.abort();
  }, [release]);
  const policies = catalog && catalog.releaseId === release?.releaseId ? catalog.policies : [];
  const heldCounts = new Map<string, number>();
  for (const item of release?.result.held ?? []) heldCounts.set(item.reason, (heldCounts.get(item.reason) ?? 0) + 1);
  const identities = release ? recordedIdentityCoverage(release) : null;
  const loader = useMemo(() => createReleaseLoader(next => { setStored(next); setError(''); navigate({ dataset: 'real', release: next.releaseId, person: '' }); }, setError), [navigate]);
  useEffect(() => () => loader.cancel(), [loader]);
  useEffect(() => { loader.cancel(); }, [route.release, route.person, loader]);
  useEffect(() => {
    if (!import.meta.env.DEV || (stored && stored.releaseId === route.release)) return;
    const controller = new AbortController();
    autoRequest.current = controller;
    const localLoader = createReleaseLoader(next => {
      if (controller.signal.aborted) return;
      setStored(next); setError('');
      if (!route.release) navigate({ dataset: 'real', release: next.releaseId, person: route.person });
    }, message => { if (!controller.signal.aborted) setError(message); });
    void (async () => {
      try {
        const response = await fetch(`/__local__/evaluation${route.release ? `?release=${encodeURIComponent(route.release)}` : ''}`, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Unavailable');
        const blob = await response.blob();
        if (blob.size > REAL_RELEASE_MAX_BYTES) throw new Error('TooLarge');
        if (!controller.signal.aborted) await localLoader.load(blob, route.release);
      } catch { if (!controller.signal.aborted) setError('指定されたローカル評価版を読み込めませんでした。同じ版のファイルを開いてください。別版や架空データへ自動では切り替えません。'); }
    })();
    return () => { controller.abort(); localLoader.cancel(); if (autoRequest.current === controller) autoRequest.current = null; };
  }, [route.release, route.person, stored, navigate]);
  const selected = release?.result.rows.find(row => row.person.id === route.person);
  const title = release?.input.evidenceEvaluation.options.direction === 'benefit' ? '国士ランキング' : '国賊ランキング';
  const stage = evaluationStage(release?.result ?? null);
  useEffect(() => { document.title = `${title}｜非公開実評価`; }, [title]);
  return <div className="app-shell real-evaluation" data-theme={release?.input.evidenceEvaluation.options.direction === 'benefit' ? 'light' : 'dark'} data-direction={release?.input.evidenceEvaluation.options.direction ?? 'harm'}>
    <ProductHeader title={title} label="非公開実評価"><nav aria-label="データ版の切り替え"><button type="button" onClick={() => navigate({ dataset: 'fiction', release: '', person: '' })}>架空デモへ切り替える</button></nav></ProductHeader>
    <main id="top"><div className="comparison-heading"><h2>公的な行動と根拠</h2><span className="fiction-warning">非公開の保存評価版です</span></div>
    <section className="real-intake" aria-labelledby="real-stage-heading"><div className="real-stage"><h2 id="real-stage-heading">{stage.label}</h2><p role="status">{stage.explanation}</p><p>全国を代表する順位や人格認定ではありません。</p></div><div className="real-upload"><label className="file-control">非公開実評価版JSONを開く<input type="file" accept=".json,application/json" onChange={event => { const file = event.target.files?.[0]; if (file) { autoRequest.current?.abort(); loader.cancel(); void loader.load(file); } event.target.value = ''; }} /></label><p>明示的に設定したローカル開発サーバーでは、保存版を読み込みます。手動入力はこのブラウザのメモリだけで保持し、送信や公開はしません。</p></div>{error && <p role="alert" className="inspection-error">{error}</p>}</section>
    {!release ? <section className="real-empty" aria-label="実評価版の読み込み案内"><h2>保存した根拠を、この画面で確認します</h2><p>人物の行動から引用・原資料までたどれます。採点されていない記録は、保留理由とともに表示します。</p><p>該当版のファイルを開いてください。{route.release && <span className="real-reference">参照版 {route.release}</span>}架空データや別の評価版へ自動では切り替えません。</p></section> : <>
      <section className="real-version" aria-label="保存評価版の条件"><details><summary>保存版の識別情報</summary><code>{release.releaseId}</code></details><p>保存条件：{release.input.evidenceEvaluation.options.domain === 'economy' ? '経済成長' : release.input.evidenceEvaluation.options.domain === 'technology' ? '科学技術' : '総合'}・{release.input.evidenceEvaluation.options.period === 'cumulative' ? '累積' : `${release.input.evidenceEvaluation.options.period}年`}・{release.input.evidenceEvaluation.options.direction === 'harm' ? '悪影響' : '貢献'}・基準日 {release.input.evidenceEvaluation.options.asOf}・経済{release.input.evidenceEvaluation.options.weights.economy}／技術{release.input.evidenceEvaluation.options.weights.technology}</p>
      <div className="inspection-summary"><span>記載人物 {release.result.rows.length}人</span>{identities ? <><span>保存版の照合済み {identities.matched}人</span><span>照合未確認 {identities.unresolved}人</span></> : <span>人物照合の記録は未確認です</span>}<span>評価可能 {release.result.rows.filter(row => row.score !== null).length}人</span><span>入力行動 {release.result.coverage.inputActions}件</span><span>算定採用行動 {release.result.coverage.assessedActions}件</span><span>保留 {release.result.held.length}件</span></div><p>照合件数は保存された検証記録です。このブラウザで公式プロフィールや候補者名簿を再照合した結果ではありません。</p>
      </section><div className="workspace-grid real-workspace"><section className="ranking-pane" aria-label="保存評価版の人物一覧"><div className="pane-heading"><h2>人物一覧</h2><p className="view-summary">保存条件における計算結果です。独立検証の成功や公開許可を示す順位ではありません。</p></div><label>氏名で探す<input type="search" value={personSearch} onChange={event => setPersonSearch(event.target.value)} placeholder="氏名を入力してください" /></label><ul className="real-people">{release.result.rows.filter(row => row.person.name.replace(/\s+/gu, '').includes(personSearch.replace(/\s+/gu, ''))).map(row => <li key={row.person.id}><button className="real-person-select" type="button" aria-pressed={route.person === row.person.id} onClick={() => navigate({ ...route, person: row.person.id })}><span className="real-person-rank">{row.rank === null ? '—' : `${row.rank}位`}</span><span className="real-person-name">{row.person.name}<small>保留{row.heldCount}件</small></span><span className={`score${row.score === null ? ' unassessed' : ''}`}>{row.score === null ? '未評価' : `${row.score.toFixed(2)}点`}</span></button></li>)}</ul>{!release.result.rows.length && <p className="empty-state">照合済みの人物はまだありません。</p>}</section><div className="person-pane real-person-pane">
      {route.person && !selected && <p role="alert">この版には指定された人物がありません。</p>}
      {selected && <p className="view-summary">人物照合：{identities && (release.verification as { resolvedPersonIds: string[] }).resolvedPersonIds.includes(selected.person.id) ? '保存版に照合記録があります。' : '未確認です。記載名だけで本人と認定しません。'}</p>}
      {selected && <section className="inspection-result" aria-label="実評価の人物詳細"><h2>{selected.person.name}</h2><p>保存評価点 {selected.score === null ? '未評価' : selected.score.toFixed(2)}。分析仮説と記録された行動を分けて確認してください。</p>{release.input.evidenceEvaluation.actions.filter(a => a.personId === selected.person.id).map(a => <details key={a.actionId}><summary>{policies.find(p => p.policyId === a.policyId)?.formalTitle ?? realActionHeading(a)}</summary><p>{realActionHeading(a)}</p>{policies.filter(p => p.policyId === a.policyId).map(p => <section key={p.policyId} aria-label="議案の内容"><h3>何を変える法案ですか？</h3><p>{p.summary}</p>{p.summaryStatus === 'unverified_explanation' && <p className="fine-note">上の短い説明は原文の引用ではなく、内容確認中の説明候補です。</p>}{p.sourceExcerpt && <details><summary>公式資料に書かれた内容を、このページで読む</summary><blockquote style={{ whiteSpace: 'pre-wrap' }}>{p.sourceExcerpt}</blockquote></details>}<a href={p.officialUrl} target="_blank" rel="noopener noreferrer">国会の議案説明を読む</a><p>この投票は法案全体への賛否です。個々の条文への賛否や、経済への効果を示すものではありません。</p></section>)}{!policies.some(p => p.policyId === a.policyId) && <p>議案の説明をまだ読み込めていません。投票の原資料から確認できます。</p>}<details><summary>抽出・検証記録</summary><p>{a.description}</p><p>政策ID {a.policyId}・役割 {a.role}・改訂 {a.revisionId}</p></details>{a.position === 'not_voted' && <p>投票なしを欠席・棄権・反対へ変換しません。</p>}<h3>行動の引用記録</h3><Quotes quotes={a.quotes} release={release} /><h3>この行動はどう評価されますか？</h3>{!release.input.evidenceEvaluation.assessments.some(s => s.policyId === a.policyId && s.policyVersion === a.policyVersion && s.position === a.position) && <p>政策の効果を判断する根拠が不足しているため、まだ採点していません。賛成・反対した事実と、良い影響・悪い影響の評価は別です。</p>}{release.input.evidenceEvaluation.assessments.filter(s => s.policyId === a.policyId && s.policyVersion === a.policyVersion && s.position === a.position).map(s => <details key={s.id}><summary>{s.domain}・{s.direction === 'harm' ? '悪影響' : '貢献'}・影響段階{s.impact}</summary><p>分析仮説：{s.rationale}</p><p>反証：{s.counterEvidence}</p><p>代替説明：{s.alternativeExplanation}</p><p>基準 {s.criterionVersion}・分析版 {s.analysisVersion}・改訂日時 {s.evaluatedAt}</p><Quotes quotes={s.quotes} release={release} /></details>)}</details>)}<h3>保留理由</h3><ul>{release.result.held.filter(h => h.personId === selected.person.id).map((h, i) => <li key={i}>{h.reason === '立場別の影響根拠が不足しています' ? 'この政策による効果を判断する根拠が不足しているため、採点していません。' : h.reason === '人物照合が未検証です' ? '投票表の記載名と本人の対応をまだ確認できていません。' : h.reason}</li>)}</ul></section>}
      {!route.person && <section className="real-person-empty"><h2>行動と根拠を確認する</h2><p>人物一覧から選ぶと、行動の引用、立場別の分析、反証、保留理由を表示します。</p></section>}
      </div></div><section className="lower-panel real-held" aria-label="評価版全体の保留"><h2>まだ確認できていないこと</h2><p>未確認の記録は0点ではありません。根拠を確認できるまで、順位や採点には使いません。</p>{heldCounts.size ? <ul>{[...heldCounts].map(([reason, count]) => <li key={reason}>{reason === '人物照合が未検証です' ? '投票表の記載名と本人の対応を確認中' : reason === '立場別の影響根拠が不足しています' ? '政策の効果を判断する根拠を確認中' : reason}：{count}件</li>)}</ul> : <p>保留中の記録はありません。ただし、すべての資料を調査済みという意味ではありません。</p>}</section>
    </>}
  </main></div>;
}

export function EvidenceDatasetRoot({ fictional }: { fictional: React.ReactNode | ((navigate: (route: RealRoute) => void) => React.ReactNode) }) {
  const [route, setRoute] = useState(() => readRealRoute(window.location.search, window.location.pathname));
  const navigate = useMemo(() => (next: RealRoute) => { window.history.pushState(null, '', realRouteLocation(next)); setRoute(next); }, []);
  useEffect(() => { const restore = () => setRoute(readRealRoute(window.location.search, window.location.pathname)); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore); }, []);
  if (window.location.pathname === '/policies') return <PoliciesPage />;
  if (route.dataset === 'real') return <RealEvaluationPanel route={route} navigate={navigate} />;
  if (window.location.pathname === '/history' || (window.location.pathname === '/' && !window.location.search)) return <EconomyPage />;
  if (window.location.pathname === '/records' || (window.location.pathname === '/' && !window.location.search)) return <RealRecordsPage onDemo={() => navigate({ dataset: 'fiction', release: '', person: '' })} onEvaluation={() => navigate({ dataset: 'real', release: '', person: '' })} />;
  return <>{typeof fictional === 'function' ? fictional(navigate) : fictional}</>;
}
