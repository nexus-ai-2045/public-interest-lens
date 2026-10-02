import { useEffect, useMemo, useRef, useState } from 'react';
import { ProductHeader } from './ProductHeader';
import { ReadableEvidencePanel } from './ReadableEvidencePanel';
import { parseLocalInspection, type LocalInspection } from './local-inspection';

const PAGE_SIZE = 20;
const positions = { for: '賛成', against: '反対', not_voted: '投票なし', unknown: '不明' };

/** 原資料の記載を閲覧します。人物照合・影響評価・順位生成はしません。 */
export function RealRecordsPage({ onDemo, onEvaluation }: { onDemo: () => void; onEvaluation: () => void }) {
  const [inspection, setInspection] = useState<LocalInspection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const request = useRef(0);
  const controller = useRef<AbortController | null>(null);

  function accept(text: string, id: number) {
    if (id !== request.current) return;
    const parsed = parseLocalInspection(text);
    if (!parsed.readableEvidence) throw new Error('閲覧できる資料がありません');
    setInspection(parsed); setQuery(''); setPage(0); setSelectedId(null); setError('');
  }
  useEffect(() => {
    const id = ++request.current;
    const abort = new AbortController(); controller.current = abort;
    async function load() {
      try {
        const response = await fetch('/__local__/records', { cache: 'no-store', signal: abort.signal });
        if (!response.ok) throw new Error('資料を取得できません');
        accept(await response.text(), id);
      } catch {
        if (id === request.current && !abort.signal.aborted) setError('ローカル資料を自動で開けませんでした。閲覧用JSONを選んでください。');
      } finally { if (id === request.current) setLoading(false); }
    }
    void load();
    return () => { abort.abort(); ++request.current; };
  }, []);

  async function openFile(file: File) {
    const id = ++request.current; controller.current?.abort(); setLoading(true); setError('');
    try {
      if (file.size > 5_000_000) throw new Error('資料が大きすぎます');
      accept(await file.text(), id);
    } catch {
      if (id === request.current) setError('このJSONを開けませんでした。実資料用の5MB以下のJSONを選んでください。直前の正常な資料は保持しています。');
    } finally { if (id === request.current) setLoading(false); }
  }

  const data = inspection?.readableEvidence;
  const votes = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('ja');
    return (data?.votes ?? []).filter(row => `${row.nameText} ${row.text} ${row.title}`.toLocaleLowerCase('ja').includes(needle));
  }, [data, query]);
  const lastPage = Math.max(0, Math.ceil(votes.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const selected = data?.votes.find(row => row.id === selectedId);

  return <div className="app-shell real-records" data-theme="dark" data-direction="harm" id="top">
    <ProductHeader title="国賊／国士ランキング" label="実資料・未採点" brandHref="/records">
      <nav aria-label="表示するデータ"><button type="button" onClick={onDemo}>架空デモ</button><button type="button" onClick={onEvaluation}>評価入口</button></nav>
    </ProductHeader>
    <main><section className="page-heading"><div><p className="eyebrow">原資料の記録</p><h2>実際の行動記録を読む</h2><p className="view-summary">原資料の記載名です。本人・候補者履歴は未照合、影響は未評価です。</p></div></section>
    <section className="real-records-intake" aria-label="実資料の読み込み">
      <label className="file-control">閲覧用JSONを開く<input type="file" accept="application/json,.json" onChange={event => { const file = event.target.files?.[0]; if (file) void openFile(file); event.target.value = ''; }} /></label>
      <p role="status">{loading ? '資料を読み込んでいます。' : inspection ? `基準日 ${inspection.asOf}・${inspection.scope}` : '実資料はまだ開かれていません。架空データへの自動切替はしません。'}</p>
      {error && <p role="alert" className="inspection-error">{error}</p>}
      {data && <div className="inspection-summary"><span>保存原本 {data.counts.savedRecords}件</span><span>読める発言 {data.counts.readableSpeechBodies}件</span><span>投票行 {data.counts.sourceVoteRows}件</span><span>確認済み行動 {data.counts.confirmedActionEvidence}件</span><span>この画面の影響評価：未評価</span></div>}
    </section>
    {data ? <>
      <div className="workspace-grid real-records-workspace">
        <section className="real-records-list" aria-label="原資料の投票行">
          <div className="pane-heading"><h2>原資料の投票行</h2><p className="view-summary">行単位の一覧です。同じ記載名を一人へ統合せず、点数や順位も付けません。</p></div>
          <label className="real-records-search">記載名・本文を検索<input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label>
          <p role="status" className="view-summary">検索結果 {votes.length}件・{currentPage + 1} / {lastPage + 1}ページ</p>
          {votes.length ? <table className="real-records-table"><thead><tr><th scope="col">記載名・行動日</th><th scope="col">原資料の賛否</th><th scope="col">影響評価</th></tr></thead><tbody>{votes.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(row => <tr key={row.id} className={selectedId === row.id ? 'real-records-selected' : undefined}><td><button type="button" aria-pressed={selectedId === row.id} onClick={() => setSelectedId(row.id)}>{row.nameText}</button><small>{row.date}</small></td><td>{positions[row.position]}</td><td>未評価</td></tr>)}</tbody></table> : <p className="empty-state">条件に合う投票行がありません。活動なし・反対・0点とは判断しません。</p>}
          <nav className="real-records-pagination" aria-label="投票行のページ"><button type="button" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>前へ</button><button type="button" disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}>次へ</button></nav>
        </section>
        <section className="person-pane real-records-detail" aria-label="選択した投票行の詳細">
          <h2>記録と原資料</h2>
          {selected ? <><h3>{selected.nameText}</h3><p>{selected.date}・原資料の区分：{positions[selected.position]}</p><h4>{selected.title}</h4>{selected.position === 'not_voted' && <p>「投票なし」は原資料の区分です。欠席・棄権・反対を推定しません。</p>}<blockquote>{selected.text}</blockquote><dl><dt>引用箇所</dt><dd>{selected.locator}</dd><dt>取得日時</dt><dd>{selected.observedAt}</dd><dt>原本照合値（SHA-256）</dt><dd>{selected.sha256}</dd></dl><p>原本との一致、人物の同一性、政策への影響はこの画面では検証していません。</p><a href={selected.sourceUrl} target="_blank" rel="noopener noreferrer">公式の原資料を開く</a></> : <p className="empty-state">記載名を選ぶと、議案名・原文・引用箇所・公式リンクを確認できます。</p>}
        </section>
      </div>
      <section className="lower-panel inspection-result"><details><summary>発言本文・政策ごとの収録状況を見る</summary><ReadableEvidencePanel data={data} policies={inspection.policySelection?.policies} /></details></section>
    </> : !loading && <section className="real-empty"><h2>実資料を開いてください</h2><p>ローカルの閲覧用JSONで、実際の発言と投票行を確認できます。資料がない状態を0点のランキングにはしません。</p></section>}
    </main><footer><span>実資料の閲覧専用・未採点</span><span>引用・人物・影響の検証は別工程です。</span></footer>
  </div>;
}
