import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReadableEvidence, SelectedPolicy } from './local-inspection';

const positions = { for: '賛成', against: '反対', not_voted: '投票なし', unknown: '不明' };
const PAGE_SIZE = 10;

/** 明示的に開いたファイルだけを読む。採点・送信・人物照合はしない。 */
export function ReadableEvidencePanel({ data, policies = [] }: { data: ReadableEvidence; policies?: Pick<SelectedPolicy, 'id' | 'billId' | 'title' | 'sourceUrl'>[] }) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  useEffect(() => { setQuery(''); setPage(0); }, [data]);
  const records = [
    ...data.speeches.map(row => ({ ...row, kind: '発言', name: row.speakerName, title: '発言本文', position: null })),
    ...data.votes.map(row => ({ ...row, kind: '投票行', name: row.nameText, position: positions[row.position] })),
  ];
  const needle = query.trim().toLocaleLowerCase('ja');
  const filtered = records.filter(row => `${row.name} ${row.text} ${row.title}`.toLocaleLowerCase('ja').includes(needle));
  const lastPage = Math.max(0, Math.ceil(filtered.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  return <section aria-label="読める実資料（未採点）">
    <h4>読める実資料（未採点）</h4>
    <p>{data.selectionScope}</p>
    <p>資料は未検証です。記載名は人物と照合していません。ブラウザでファイルを開いても、原資料との一致やハッシュの正しさを確認したことにはなりません。</p>
    <div className="inspection-summary"><span>保存原本（ページ） {data.counts.savedRecords}件</span><span>読める発言本文 {data.counts.readableSpeechBodies}件</span><span>原資料の投票行 {data.counts.sourceVoteRows}件</span><span>確認済み行動証拠 {data.counts.confirmedActionEvidence}件</span></div>
    <section aria-label="選定政策ごとの収録状況">
      <h4>選定政策ごとの収録状況</h4>
      <p>登録済み候補集合内の選定です。全国の政策を網羅した一覧ではありません。</p>
      {policies.length === 0 ? <p>選定政策はこのファイルに明示されていません。</p> : <ul>{policies.map(policy => {
        const count = data.votes.filter(vote => vote.policyId === (policy.billId ?? policy.id)).length;
        return <li key={policy.id}><strong>{policy.title}</strong>
          <p>{count > 0 ? `投票行 ${count}件・未検証` : 'このファイルには投票行がありません。活動なし・反対・0点とは判断しません。'}</p>
          <a href={policy.sourceUrl} target="_blank" rel="noopener noreferrer">公式の議案ページを開く</a>
        </li>;
      })}</ul>}
      <p>発言と選定政策の対応は未確認です。読める本文を、関連発言や確認済み行動へ自動認定しません。</p>
    </section>
    <label>記載名・本文を検索<input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label>
    <p role="status">検索結果 {filtered.length}件・{currentPage + 1} / {lastPage + 1}ページ</p>
    {filtered.length === 0 ? <p>条件に合う資料がありません。記録がないことは活動がなかったことを意味しません。</p> : <ul>{filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(row => <li key={row.id}>
      <details><summary>{row.kind}：{row.name}・{row.date}{row.position ? `・${row.position}` : ''}</summary>
        <p>記載名：{row.name}（人物未照合）</p><strong>{row.title}</strong>
        {row.position === '投票なし' && <p>「投票なし」は原資料の区分です。欠席・棄権・反対を推定しません。</p>}
        <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{row.text}</p>
        <small>引用箇所 {row.locator}</small><small>取得日時 {row.observedAt}</small><small style={{ overflowWrap: 'anywhere' }}>照合値（SHA-256）{row.sha256}</small>
        <a href={row.sourceUrl} target="_blank" rel="noopener noreferrer">原資料を開く</a>
      </details>
    </li>)}</ul>}
    <nav aria-label="実資料のページ"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={16} aria-hidden="true" />前の資料</button><button type="button" disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}>次の資料<ChevronRight size={16} aria-hidden="true" /></button></nav>
  </section>;
}
