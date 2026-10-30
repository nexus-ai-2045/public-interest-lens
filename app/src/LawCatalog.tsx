import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowUpRight, ChevronDown, Layers, Search } from 'lucide-react';
import { ShareButton } from './motion';
import {
  DEFAULT_QUERY, STEP_LABEL, collapseObservations, detailBundleUrl, filterCatalog, formatYen, groupByObservation, isOutlierMark, readQuery, sideLabel, writeQuery,
  type CatalogDetail, type CatalogItem, type CatalogOverview, type CatalogQuery, type LawsCatalog, type OverviewQuote,
} from './laws-catalog';
import { LawName, lawNameText } from './law-name';
import { loadPriceIndex, toLatestYen, windowBaseYear, type PriceIndex } from './price-index';
import { CORRECTION_EMAIL, correctionIssueUrl, correctionListUrl, correctionMailUrl } from './correction-link';
import { isCovidBenefitGroup } from './public-distribution';

const PAGE = 60;
const SIDE_OPTIONS: [CatalogQuery['side'], string][] = [['all', 'すべて'], ['confirmed', '確かな額'], ['amount', '額が出た（参考を含む）'], ['loss', '国賊側'], ['benefit', '国士側'], ['none', '額なし']];
const SORT_OPTIONS: [CatalogQuery['sort'], string][] = [['amount', '額の大きい順'], ['loss', '損失の大きい順'], ['benefit', '便益の大きい順'], ['progress', '計算が進んだ順'], ['newest', '新しい順'], ['oldest', '古い順']];
const ROLE_LABEL: Record<string, string> = { proposer: '提出', vote: '参院で賛成', chair: '委員長' };

/** 詳細は束（提出回次ごと）を、初めてその束の行を開いた時に1回だけ読む。 */
const detailCache = new Map<string, Promise<Record<string, CatalogDetail>>>();
function loadDetails(id: string): Promise<Record<string, CatalogDetail>> {
  const url = detailBundleUrl(id);
  let pending = detailCache.get(url);
  if (!pending) {
    pending = fetch(url).then(async response => {
      if (!response.ok) throw new Error('missing');
      return (await response.json() as { items: Record<string, CatalogDetail> }).items;
    }).catch(error => { detailCache.delete(url); throw error; });
    detailCache.set(url, pending);
  }
  return pending;
}

const hashId = () => { try { return decodeURIComponent(window.location.hash.slice(1)); } catch { return ''; } };

export function LawCatalog({ data }: { data: LawsCatalog }) {
  const all = useMemo(() => [...data.policies, ...data.laws], [data]);
  const [query, setQuery] = useState<CatalogQuery>(() => readQuery(window.location.search));
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<string>(() => hashId());
  const [scrollTo, setScrollTo] = useState('');
  // 同じ観測の法律は代表の1行にまとめる。「すべて表示」で全部並べ、題名の一覧から選んだ法律・#id で開く法律は行として足す。
  const [showAll, setShowAll] = useState(false);
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(() => new Set());
  const showAllRef = useRef(showAll);
  showAllRef.current = showAll;
  const revealedRef = useRef(revealed);
  // 行を開く処理（# のリンクと、同じ観測の一覧から題名を選んだ時の両方で使う）。
  const focusRef = useRef<(id: string) => void>(() => {});
  revealedRef.current = revealed;
  const observations = useMemo(() => groupByObservation(data.laws), [data]);
  const byId = useMemo(() => new Map(all.map(item => [item.id, item])), [all]);
  const queryRef = useRef(query);
  queryRef.current = query;
  const filtered = useMemo(() => filterCatalog(all, query), [all, query]);
  const shown = useMemo(() => showAll ? filtered : collapseObservations(filtered, revealed), [filtered, showAll, revealed]);
  const kinds = useMemo(() => [...new Set(all.map(item => item.kind))], [all]);

  const update = (next: Partial<CatalogQuery>) => {
    const merged = { ...query, ...next };
    setQuery(merged);
    setLimit(PAGE);
    {
      // 最上部の絞り込み（政党・性格）の URL 項目は消さずに残す。
      const params = new URLSearchParams(writeQuery(merged).slice(1));
      const keep = new URLSearchParams(window.location.search);
      for (const key of ['party', 'nature']) { const value = keep.get(key); if (value) params.set(key, value); }
      window.history.replaceState(null, '', `${window.location.pathname}${params.size ? `?${params}` : ''}${window.location.hash}`);
    }
  };

  // URL の #法律ID で開く。絞り込みで隠れていたら外し、その行まで一覧を伸ばしてから移る。
  // 同じ # のリンクをもう一度押した時は hashchange が出ないので、クリックでも拾う。
  useEffect(() => {
    const focus = (id: string) => {
      if (!id || !all.some(item => item.id === id)) return;
      // 代表でない法律の #id は、その法律を行として足す（同じ観測の代表の隣に出る）。
      const reveal = new Set(revealedRef.current).add(id);
      setRevealed(reveal);
      const visible = (query: CatalogQuery) => showAllRef.current ? filterCatalog(all, query) : collapseObservations(filterCatalog(all, query), reveal);
      let list = visible(queryRef.current);
      if (!list.some(item => item.id === id)) {
        setQuery(DEFAULT_QUERY);
        list = visible(DEFAULT_QUERY);
        window.history.replaceState(null, '', `${window.location.pathname}#${encodeURIComponent(id)}`);
      }
      const index = list.findIndex(item => item.id === id);
      setLimit(value => Math.max(value, index + 1));
      setOpen(id);
      setScrollTo(id);
    };
    focusRef.current = focus;
    const onHash = () => focus(hashId());
    const onClick = (event: MouseEvent) => {
      const link = (event.target as Element | null)?.closest?.('a[href^="#"]');
      if (!link) return;
      let id = '';
      try { id = decodeURIComponent(link.getAttribute('href')!.slice(1)); } catch { return; }
      if (id !== hashId()) return;
      event.preventDefault();
      focus(id);
    };
    onHash();
    window.addEventListener('hashchange', onHash);
    document.addEventListener('click', onClick);
    return () => { window.removeEventListener('hashchange', onHash); document.removeEventListener('click', onClick); };
  }, [all]);

  // 行が描かれてから移る（一覧を伸ばした直後はまだ無い）。
  useEffect(() => {
    if (!scrollTo) return;
    const row = document.getElementById(`law-${scrollTo}`);
    if (row) { row.scrollIntoView({ block: 'start' }); setScrollTo(''); }
  }, [scrollTo, shown, limit]);

  const hidden = filtered.length - shown.length;
  const amounted = shown.filter(item => item.amount).length;
  const confirmed = shown.filter(item => item.step === 'published').length;
  return <section className="laws-catalog" aria-label="法律と政策の一覧">
    <h3 id="list">全部の法律と政策（{all.length.toLocaleString('ja-JP')}件）</h3>
    <p className="laws-howto">1行で「何をする法律か・額・向き・確かさ」が分かります。<strong>行を押すと</strong>、誰が出してどう決まったか・反対側の心配・計算の流れ・関わった議員・一次資料が開きます。</p>
    <div className="laws-controls">
      <label className="laws-search"><Search size={16} aria-hidden="true" /><input type="search" value={query.text} onChange={event => update({ text: event.target.value })} placeholder="法律の名前・番号・分野で探す" aria-label="法律の名前・番号・分野で探す" /></label>
      <div className="laws-chips" role="group" aria-label="向きで絞る">{SIDE_OPTIONS.map(([value, label]) => <button key={value} type="button" aria-pressed={query.side === value} className={`laws-chip side-${value}`} onClick={() => update({ side: value })}>{label}</button>)}</div>
      <div className="laws-selects">
        <label>分野<select value={query.field} onChange={event => update({ field: event.target.value })}><option value="">すべて</option>{data.fields.map(field => <option key={field} value={field}>{field}</option>)}</select></label>
        <label>種類<select value={query.kind} onChange={event => update({ kind: event.target.value })}><option value="">すべて</option>{kinds.map(kind => <option key={kind} value={kind}>{kind === '閣法' ? '閣法（内閣が提出）' : kind === '衆法' ? '衆法（衆議院議員が提出）' : kind === '参法' ? '参法（参議院議員が提出）' : kind}</option>)}</select></label>
        <label>並べ替え<select value={query.sort} onChange={event => update({ sort: event.target.value as CatalogQuery['sort'] })}>{SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
    </div>
    <p className="laws-count" role="status">{shown.length.toLocaleString('ja-JP')}件（確かな額{confirmed.toLocaleString('ja-JP')}・参考の額{(amounted - confirmed).toLocaleString('ja-JP')}・額なし{(shown.length - amounted).toLocaleString('ja-JP')}）{JSON.stringify(query) !== JSON.stringify(DEFAULT_QUERY) && <button type="button" onClick={() => update(DEFAULT_QUERY)}>絞り込みを外す</button>} <ShareButton title="法律と政策の一覧｜法律ランキング" text={`法律と政策の一覧（${shown.length.toLocaleString('ja-JP')}件）`} url={`${window.location.origin}/ranking${writeQuery(query)}#list`} label="この一覧を共有" /></p>
    {(hidden > 0 || showAll) && <p className="laws-fold" role="status">
      <Layers size={15} aria-hidden="true" />
      <span>{showAll ? '同じ観測の法律も、すべて別の行で並べています（同じ観測の法律は同じ額。足し合わせないでください）。' : <>同じ観測（同じ額の系列・同じ期間）の法律は、代表の1行にまとめています（ほか{hidden.toLocaleString('ja-JP')}本。同じ額なので足し合わせません）。</>}</span>
      <button type="button" aria-pressed={showAll} onClick={() => { setShowAll(value => !value); setLimit(PAGE); }}>{showAll ? '代表だけにまとめる' : '同じ観測の法律もすべて表示'}</button>
    </p>}
    <ol className="laws-list">
      {shown.slice(0, limit).map(item => <CatalogRow key={item.id} item={item} open={open === item.id} observations={observations} byId={byId} folded={!showAll} revealed={revealed} onReveal={id => {
        // 絞り込みに合わない法律でも開けるように、# と同じ処理を通す（合わなければ絞り込みを外す）。
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${encodeURIComponent(id)}`);
        focusRef.current(id);
      }} onToggle={() => {
        const next = open === item.id ? '' : item.id;
        setOpen(next);
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${next ? `#${encodeURIComponent(next)}` : ''}`);
      }} />)}
    </ol>
    {shown.length > limit && <button type="button" className="laws-more" onClick={() => setLimit(value => value + PAGE * 2)}>続きを表示（残り{(shown.length - limit).toLocaleString('ja-JP')}件）</button>}
    {!shown.length && <p className="empty-state">条件に合う法律がありません。</p>}
  </section>;
}

type RowProps = { item: CatalogItem; open: boolean; onToggle: () => void; observations: Map<string, CatalogItem[]>; byId: Map<string, CatalogItem>; folded: boolean; revealed: ReadonlySet<string>; onReveal: (id: string) => void };

/** 同じ観測の法律。代表の行では「ほか N 本が同じ観測」を押すと題名の一覧が開く。代表でない行には代表へのリンクを出す。 */
function ObservationNote({ item, observations, byId, folded, revealed, onReveal }: Omit<RowProps, 'open' | 'onToggle'>) {
  const [listOpen, setListOpen] = useState(false);
  const observation = item.observation;
  if (!observation || observation.size < 2) return null;
  const others = (observations.get(observation.key) ?? []).filter(other => other.id !== item.id);
  const listId = `laws-peers-${item.id}`;
  const representative = observation.representativeId ? byId.get(observation.representativeId) : undefined;
  const lead = !observation.representative && representative && <span className="laws-peers-rep">代表の<a href={`#${encodeURIComponent(representative.id)}`}>「{lawNameText(representative.title, representative.what)}」</a>と同じ観測（同じ額）。</span>;
  if (!folded) return <div className="laws-peers is-flat"><Layers size={14} aria-hidden="true" /><span>同じ観測の{observation.size}本の1つ（同じ額。足し合わせない）。{lead}</span></div>;
  return <div className={`laws-peers${listOpen ? ' is-open' : ''}`}>
    {lead}
    <button type="button" className="laws-peers-toggle" aria-expanded={listOpen} aria-controls={listId} onClick={() => setListOpen(value => !value)}>
      <Layers size={14} aria-hidden="true" />
      <span>ほか{(observation.size - 1).toLocaleString('ja-JP')}本が同じ観測（同じ額。足し合わせない）</span>
      <ChevronDown size={16} className="laws-peers-chevron" aria-hidden="true" />
    </button>
    {listOpen && <ul id={listId} className="laws-peers-list">
      {others.map(other => <li key={other.id}>
        <a href={`#${encodeURIComponent(other.id)}`} onClick={event => { event.preventDefault(); onReveal(other.id); }}><LawName title={other.title} what={other.what} compact /></a>
        <small>{other.id}{other.year ? `・${other.year}年` : ''}{revealed.has(other.id) ? '・行に表示中' : ''}</small>
      </li>)}
    </ul>}
  </div>;
}

function CatalogRow({ item, open, onToggle, ...peers }: RowProps) {
  const tone = item.side ?? 'none';
  return <li id={`law-${item.id}`} className={`laws-row ${tone} ${item.amount ? 'has-amount' : 'no-amount'} ${open ? 'is-open' : ''}`}>
    <button type="button" className="laws-row-head" aria-expanded={open} onClick={onToggle}>
      <span className="laws-row-main">
        <span className="laws-row-meta"><span className={`laws-side ${tone}`}>{item.amount ? `${sideLabel(item.side)}${item.step === 'amounted' ? '・参考' : ''}` : item.kind === '政策' ? '政策・額は保留' : '額なし'}</span><span>{item.kind === '政策' ? '政策' : item.id}</span>{item.year && <span>{item.year}年</span>}<span>{item.field}</span></span>
        <span className="laws-row-title"><LawName title={item.title} what={item.what} withheld={item.whatWithheld} /></span>
        <span className="laws-row-summary">{item.summary}</span>
        {item.marks.length > 0 && <span className="laws-marks">{item.marks.map(mark => isOutlierMark(mark)
          ? <span key={mark} className="laws-mark is-outlier"><AlertTriangle size={12} aria-hidden="true" />{mark}{item.scale ? `：約${item.scale.toLocaleString('ja-JP', { maximumFractionDigits: 1 })}倍` : ''}</span>
          : <span key={mark} className={`laws-mark${mark.startsWith('確かさ') ? ' is-certain' : mark === '参考の額' ? ' is-reference' : ''}`}>{mark}</span>)}</span>}
      </span>
      <span className="laws-row-amount">
        {item.amount ? <><strong>{formatYen(item.amount.median)}</strong><small>幅 {formatYen(item.amount.low)}〜{formatYen(item.amount.high)}</small></> : <span className="laws-row-noamount">{STEP_LABEL[item.step]}</span>}
        <ChevronDown size={18} className="laws-chevron" aria-hidden="true" />
      </span>
    </button>
    <ObservationNote item={item} {...peers} />
    {open && <CatalogDetailPanel item={item} />}
  </li>;
}

/** 冒頭の5行：何を・誰が・狙い・反対側の心配・結果。事実・AI 要約・計算を見分けられるように印を付ける。 */
function OverviewBox({ overview }: { overview: CatalogOverview }) {
  const quote = (value: OverviewQuote | undefined, label: string) => value?.url && <a className="laws-ov-src" href={value.url} target="_blank" rel="noopener noreferrer">{label}：{value.speaker}・{value.date} <ArrowUpRight size={12} /></a>;
  return <section className="laws-overview" aria-label="概要">
    <dl>
      <div><dt>何をする</dt><dd>{overview.what?.text ? <>{overview.what.text}<span className="laws-ov-tag">AI要約</span>{quote(overview.what, '提案理由の説明')}</> : overview.what?.withheld === 'unchecked' ? <span className="laws-ov-none">見つかった発言がこの法律の提案理由の説明か、まだ確かめていないため示していません。題名と一次資料を見てください。</span> : overview.what?.withheld === 'other' ? <span className="laws-ov-none">見つかった発言は、この法律の提案理由の説明だと確かめられなかったため（別の法案の説明など）、1行にしていません。題名と一次資料を見てください。</span> : overview.what ? <><span className="laws-ov-none">{overview.what.withheld === 'shared' ? 'この法律の名前が出る提案理由の説明は見つかりましたが、ほかの法案とまとめた説明で、この法律の部分を1行にできませんでした。' : '提案理由の説明は見つかりましたが、抜粋からこの法律の中身を1行にできませんでした。'}</span>{quote(overview.what, '見つかった発言')}</> : <span className="laws-ov-none">会議録の提案理由の説明から、この法律の中身を1行にできませんでした。題名と一次資料を見てください。</span>}</dd></div>
      <div><dt>誰が</dt><dd>{overview.passage}{overview.parties && <span className="laws-ov-parties">{overview.parties.no.length ? <>衆院で反対：{overview.parties.no.join('・')}</> : '衆院では反対した会派なし'}</span>}</dd></div>
      {overview.aim?.text && <div><dt>狙い</dt><dd>{overview.aim.text}<span className="laws-ov-tag">AI要約・提出側の説明</span></dd></div>}
      <div><dt>反対側の心配</dt><dd>{overview.concern?.text ? <>{overview.concern.text}<span className="laws-ov-tag">AI要約</span>{quote(overview.concern, '反対討論')}</> : overview.concern?.withheld === 'unchecked' ? <span className="laws-ov-none">見つかった討論がこの法律への反対討論か、まだ確かめていないため示していません。</span> : overview.concern?.withheld === 'other' ? <span className="laws-ov-none">見つかった討論は、この法律への反対討論だと確かめられなかったため（予算や動議、別の法案への討論、賛成の討論など）、1行にしていません。</span> : overview.concern ? <><span className="laws-ov-none">{overview.concern.withheld === 'shared' ? 'この法律の名前が出る反対討論は見つかりましたが、どの法案についての討論か決められず、1行にしていません。' : '反対討論は見つかりましたが、抜粋から反対の理由を1行にできませんでした。'}</span>{quote(overview.concern, '見つかった発言')}</> : <span className="laws-ov-none">会議録に反対討論は見つかりませんでした。</span>}</dd></div>
      <div><dt>結果</dt><dd><strong>{overview.result}</strong><span className="laws-ov-tag is-calc">このサイトの計算</span></dd></div>
    </dl>
  </section>;
}

function CatalogDetailPanel({ item }: { item: CatalogItem }) {
  const [detail, setDetail] = useState<CatalogDetail | null>(null);
  const [error, setError] = useState(false);
  const [prices, setPrices] = useState<PriceIndex | null>(null);
  useEffect(() => {
    let alive = true;
    if (item.amount) loadPriceIndex().then(index => { if (alive) setPrices(index); }).catch(() => { /* 換算表が無ければ換算の行を出さない */ });
    loadDetails(item.id).then(items => { if (alive) setDetail(items[item.id] ?? { chain: [], sources: [] }); }).catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [item.id]);
  if (error) return <div className="laws-detail"><p role="alert">詳細を読み込めませんでした。時間をおいて開き直してください。</p></div>;
  if (!detail) return <div className="laws-detail" aria-busy="true"><p className="fine-note">読み込み中…</p></div>;
  const members = detail.members ?? [];
  const target = { title: item.kind === '政策' ? item.title : `${lawNameText(item.title, item.what)}（${item.id}）`, page: `/ranking#${encodeURIComponent(item.id)}`, sources: detail.sources };
  return <div className="laws-detail">
    {detail.overview && <OverviewBox overview={detail.overview} />}
    <dl className="laws-facts">
      {detail.proposer && <div><dt>提出者</dt><dd>{detail.proposer}</dd></div>}
      {detail.promulgatedOn && <div><dt>公布日</dt><dd>{detail.promulgatedOn}</dd></div>}
      {detail.enforcedOn && <div><dt>施行日</dt><dd>{detail.enforcedOn}</dd></div>}
      {detail.indicator && <div><dt>測る指標</dt><dd>{detail.indicator}</dd></div>}
      {detail.window && <div><dt>額の窓</dt><dd>{detail.window}</dd></div>}
      {detail.comparison && detail.comparison.length > 0 && <div><dt>比べた国</dt><dd>{detail.comparison.join('・')}</dd></div>}
    </dl>
    <h5>計算の流れ（どこまで進み、どこで止まったか）</h5>
    <ol className="laws-chain">{detail.chain.map((step, index) => <li key={index}>
      <span className="laws-chain-step">{step.step}</span><strong>{step.result}</strong>
      {step.note && <details><summary>根拠を読む</summary><p>{step.note}</p></details>}
    </li>)}</ol>
    {item.amount && (isCovidBenefitGroup(detail.group)
      ? <p className="laws-formula">額 ＝ 支出の規模（官公庁の一次資料）× 帰属 × 乗数（{detail.window ?? '窓'}）。中央値 {formatYen(item.amount.median)}、幅 {formatYen(item.amount.low)}〜{formatYen(item.amount.high)}（帰属と乗数の仮定の下・中・上。観測した値の四分位ではない）。財源調達の超過負担は引いていません。</p>
      : <p className="laws-formula">額 ＝ 施行後の日本の伸びと、比べた国の伸びの差 × 開始前の規模（{detail.window ?? '窓'}の累積）。中央値 {formatYen(item.amount.median)}、幅 {formatYen(item.amount.low)}〜{formatYen(item.amount.high)}（比べた国の伸びの四分位）。</p>)}
    {item.amount && prices && (() => {
      const base = windowBaseYear(detail.window);
      const latest = toLatestYen(item.amount.median, base, prices);
      return latest === null ? null : <p className="fine-note">額は{base}年の円です。物価をそろえると {prices.latestYear}年の円で {formatYen(latest)}（GDP デフレーター {base}年→{prices.latestYear}年。<a href="/methodology#spec-price">換算のしかた</a>）。順位と議員の額は、まだ各法律の開始前の年の円で並べています。</p>;
    })()}
    {(members.length > 0 || detail.people) && <>
      <h5>関わった議員（{item.membersTotal ?? members.length}人）</h5>
      {members.length > 0 && <>
        {detail.attributed && <p className="fine-note">法律の額のうち、議員に配った額は {formatYen(detail.attributed.median)}（成立への寄与、Shapley 値）。名前を押すと議員ランキングのその人が開きます。</p>}
        <ul className="laws-members">{members.map(member => <li key={member.id}><a href={`/members?name=${encodeURIComponent(member.id)}#member-${encodeURIComponent(member.id)}`}>{member.name}</a><span>{member.roles.map(role => ROLE_LABEL[role] ?? role).join('・')}</span><strong>{formatYen(Math.abs(member.median))}</strong></li>)}</ul>
        {(item.membersTotal ?? 0) > members.length && <p className="fine-note">ほか{(item.membersTotal ?? 0) - members.length}人は<a href={`/members`}>議員ランキング</a>で見られます。</p>}
      </>}
      {detail.people && <ul className="laws-people">{detail.people.map(person => <li key={person.name}><strong>{person.name}</strong>：{person.note}</li>)}</ul>}
    </>}
    {!members.length && !detail.people && item.kind !== '政策' && <p className="fine-note">{item.amount && item.certainty === '参考'
      ? <>この法律の参考の額は、提出者と参議院の賛成者に配り、<a href="/members#all-members">議員ページの「全議員」の表</a>に「参考」の欄として出しています（確かな額とは足しません）。</>
      : item.amount ? 'この法律の額は、まだ議員に配っていません（配分は議員ランキングに載る法律から順に進めています）。' : '額が出ていないので、議員への配分はありません。'}</p>}
    <h5>一次資料</h5>
    <ul className="laws-sources">{detail.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.label} <ArrowUpRight size={13} /></a></li>)}</ul>
    <p className="laws-deeper">さらに詳しく：<a href="/methodology">計算方法</a>{item.href && <> ・ <a href={item.href}>この政策のページ</a></>} ・ <a href="https://github.com/nexus-ai-2045/public-interest-lens/tree/main/data/derived" target="_blank" rel="noopener noreferrer">計算に使った表 <ArrowUpRight size={13} /></a></p>
    <p className="correction-row"><a className="correction-link" href={correctionIssueUrl(target)} target="_blank" rel="noopener noreferrer">反論・訂正</a><span>この行の額・判定・出典への反論や訂正を GitHub の Issue で送る（対象と出典は入った状態で開きます）</span><a href={correctionListUrl(item.title)} target="_blank" rel="noopener noreferrer">寄せられた反論・訂正を見る</a>{CORRECTION_EMAIL && <a href={correctionMailUrl(target, CORRECTION_EMAIL)}>GitHub を使わずメールで送る</a>}</p>
    <ShareButton title={`${lawNameText(item.title, item.what)}｜法律ランキング`} text={item.amount ? `${lawNameText(item.title, item.what)}：${item.side === 'loss' ? '損失' : '便益'}の推計 ${formatYen(item.amount.median)}（幅 ${formatYen(item.amount.low)}〜${formatYen(item.amount.high)}）` : `${lawNameText(item.title, item.what)}：${item.summary}`} url={`${window.location.origin}/ranking#${encodeURIComponent(item.id)}`} />
  </div>;
}
