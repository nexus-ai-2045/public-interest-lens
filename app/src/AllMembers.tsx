import { memberLocation } from './member-navigation';
import { useEffect, useMemo, useState } from 'react';
import { formatYen } from './LawRankingPage';
import { pageCount, pageSlice } from './law-ranking-view';
import type { PublicMember } from './members-build';
import type { PublicMembersReference } from './members-reference';
import { LawName, namingOf, useLawNames } from './law-name';
import { breakdownOf, filterRows, joinConfirmed, partiesOf, SORT_LABEL, sortRows, type HouseFilter, type Row, type SortKey } from './all-members-view';

const signed = (v: number) => v === 0 ? '0円' : `${v < 0 ? '−' : '＋'}${formatYen(Math.abs(v))}`;
const tone = (v: number | null) => v === null || v === 0 ? 'zero' : v < 0 ? 'loss' : 'benefit';

function RowDetail({ row }: { row: Row }) {
  const names = useLawNames();
  return <div className="all-member-detail">
    {row.reason && <p className="fine-note">{row.reason}</p>}
    {row.top.length > 0 && <>
      <p className="fine-note">参考の額が大きい法律（最大5本）。額は同じ観測を共有する法律の本数で割ってから、提出・参議院の賛成で配っています。</p>
      <ul className="all-member-laws">{row.top.map(t => <li key={t.lawId + t.role} className={t.side}>
        <a href={`/ranking#${encodeURIComponent(t.lawId)}`}><LawName title={t.title} {...namingOf(names, t.lawId)} compact /></a>
        <span>{t.role === 'proposer' ? '提出' : '参議院で賛成'}・{t.side === 'loss' ? '国賊側' : '国士側'} {formatYen(t.share)}</span>
      </li>)}</ul>
    </>}
    {row.confirmedRank !== null && <p><a href={memberLocation(row.id, window.location.search, true)}>確かな額の順位（{row.confirmedRank}位）と一次資料のつながりを上の一覧で開く</a></p>}
  </div>;
}

export function AllMembers({ confirmed, data, error }: { confirmed: PublicMember[]; data: PublicMembersReference | null; error: string }) {
  const [house, setHouse] = useState<HouseFilter>('all');
  const [party, setParty] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortKey>('reference-loss');
  const [withAmount, setWithAmount] = useState(false);
  const [page, setPage] = useState(1);
  const rows = useMemo(() => data ? joinConfirmed(data.members, confirmed) : [], [data, confirmed]);
  const breakdown = useMemo(() => breakdownOf(rows), [rows]);
  const parties = useMemo(() => partiesOf(rows), [rows]);
  const shown = useMemo(() => sortRows(filterRows(rows, { house, party, query, withAmount }), sort), [rows, house, party, query, withAmount, sort]);
  useEffect(() => setPage(1), [house, party, query, withAmount, sort]);
  const pages = pageCount(shown.length);
  return <section id="all-members" className="all-members" aria-label="全議員">
    <h3>全議員（現職の衆参全員と、過去に関わった人）</h3>
    {error && <p className="state-banner" role="alert">{error}</p>}
    {data && <>
      <p className="all-members-lead">公開しているのは{breakdown.total.toLocaleString('ja-JP')}人。うち現職{breakdown.current.toLocaleString('ja-JP')}人（衆{breakdown.shu}・参{breakdown.san}）で、額のある現職は{breakdown.currentWithAmount.toLocaleString('ja-JP')}人（衆{breakdown.shuWithAmount}・参{breakdown.sanWithAmount}）です。額のない衆議院の現職{(breakdown.shu - breakdown.shuWithAmount).toLocaleString('ja-JP')}人は、個人の賛否が記録に残らず（会派ごとの賛否だけ）、0円になっています。額のある人は全体で{breakdown.withAmount.toLocaleString('ja-JP')}人（参考の額は{data.counts.laws.toLocaleString('ja-JP')}本の法律から配りました）。</p>
      <p className="fine-note">一次資料につながる「確かな額」があるのは{breakdown.confirmed.toLocaleString('ja-JP')}人だけです。参考の額の人は、一次資料の鎖ではなく、提出者の記録と参議院の個人別の賛成記録から配った額です（会派の賛否から個人へは配っていません）。</p>
      <div className="all-members-legend">
        <span className="badge confirmed">確かな額</span><span>影響の段階まで確かめた法律の額。上の順位と同じ。</span>
        <span className="badge reference">参考</span><span>産業や経済全体の差を法律に当てた額。確かさは低く、確かな額と足しません。</span>
      </div>
      <div className="members-controls all-members-controls">
        <div role="group" aria-label="院">{(['all', '衆議院', '参議院', 'former'] as HouseFilter[]).map(h => <button key={h} type="button" aria-pressed={house === h} onClick={() => setHouse(h)}>{h === 'all' ? 'すべて' : h === 'former' ? '元職・当時' : `現職の${h}`}</button>)}</div>
        <label>会派 <select value={party} onChange={e => setParty(e.target.value)}><option value="">すべて</option>{parties.map(p => <option key={p} value={p}>{p}</option>)}</select></label>
        <label>並べ方 <select value={sort} onChange={e => setSort(e.target.value as SortKey)}>{(Object.keys(SORT_LABEL) as SortKey[]).map(k => <option key={k} value={k}>{SORT_LABEL[k]}</option>)}</select></label>
        <label>名前・会派・選挙区で探す <input type="search" value={query} onChange={e => setQuery(e.target.value)} /></label>
        <label className="knob-check"><input type="checkbox" checked={withAmount} onChange={e => setWithAmount(e.target.checked)} /> 額のある人だけ</label>
      </div>
      <p className="fine-note" role="status">{shown.length.toLocaleString('ja-JP')}人{pages > 1 && `（${page}／${pages}ページ）`}</p>
      <ol className="all-members-list" start={(page - 1) * 50 + 1}>{pageSlice(shown, page).map(row => <li key={row.id}>
        <details>
          <summary>
            <span className="all-member-name">{row.name}{row.current ? <small>{row.current.house === '衆議院' ? '衆' : '参'}・{row.current.party}・{row.current.district}</small> : <small>{row.lastSangiinParty ? `元職（参議院では${row.lastSangiinParty}）` : '元職・当時'}</small>}</span>
            <span className={`all-member-amount ${tone(row.confirmed)}`}><span className="badge confirmed">確かな額</span>{row.confirmed === null ? '—' : signed(row.confirmed)}</span>
            <span className={`all-member-amount ${tone(row.net.median)}`}><span className="badge reference">参考</span>{signed(row.net.median)}</span>
            <span className="all-member-laws-count">{row.laws}本</span>
          </summary>
          <RowDetail row={row} />
        </details>
      </li>)}</ol>
      {pages > 1 && <nav className="pager" aria-label="ページ">
        <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>前へ</button>
        <span>{page}／{pages}</span>
        <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>次へ</button>
      </nav>}
      <p className="fine-note">参考の額の決まり：同じ観測（同じ額の系列・同じ期間）を共有する法律は、観測の額を本数で割ります。提出者（閣法は提出時の内閣総理大臣、議員立法は提出者の欄）と参議院の押しボタン投票の賛成者に、確かな額と同じ Shapley 値で配ります。参議院の個人別の賛否が見つからない法律は、会派の分を人に配りません。衆議院は起立採決で個人の賛否が残らないため、衆議院だけの議員は提出者でない限り0円です。同姓同名で分けた名前は、所属を示す一次資料を添えた対応表に載った行だけ人に結び、決まらないものは配りません。</p>
    </>}
  </section>;
}
