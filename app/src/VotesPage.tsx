import { useEffect, useMemo, useState } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { SiteShell } from './SiteHeader';
import {
  BLOCS, START_YEARS, blocStance, blocSummary, distributionVotesUrl, fromYear, lawYear, noLawsByMember, parseVotes, startLabel,
  type Bloc, type PublicVotes, type StartYear, type VoteLaw,
} from './votes';
import './votes.css';

const STANCE_LABEL = { yes: '賛成', no: '反対', split: '会派で割れ', none: '記載なし' } as const;
const dateOf = (law: VoteLaw) => law.promulgated ?? law.shu?.date ?? law.san?.date ?? '';

function lawLinks(law: VoteLaw) {
  return <span className="votes-links"><a href={law.url} target="_blank" rel="noopener noreferrer">議案の経過</a>{law.san && <a href={law.san.url} target="_blank" rel="noopener noreferrer">参院の採決</a>}</span>;
}

/** 最近の法律：衆議院の賛成・反対の会派と、参議院の賛成・反対の人数。 */
export function RecentLaws({ laws, limit = 12 }: { laws: VoteLaw[]; limit?: number }) {
  return <ol className="votes-recent">{laws.slice(0, limit).map(law => {
    const g = law.san?.groups;
    const yes = g ? Object.values(g).reduce((s, v) => s + v[0], 0) : null, no = g ? Object.values(g).reduce((s, v) => s + v[1], 0) : null;
    const noGroups = g ? Object.entries(g).filter(([, v]) => v[1] > 0).map(([name, v]) => `${name} ${v[1]}`) : [];
    return <li key={law.id}>
      <p className="votes-date">{dateOf(law)}　{law.kind}</p>
      <h4>{law.title}</h4>
      {law.shu && <p><strong>衆院</strong>　賛成：{law.shu.yes.join('、') || 'なし'}　<span className="votes-no">反対：{law.shu.no.join('、') || 'なし（全会派が賛成）'}</span></p>}
      {law.san?.method === 'ballot' && <p><strong>参院</strong>　賛成 {yes}・反対 {no}{noGroups.length > 0 && <span className="votes-no">（反対の内訳：{noGroups.join('、')}）</span>}</p>}
      {law.san?.method === 'standing' && <p><strong>参院</strong>　起立採決（個人・会派別の記録なし）</p>}
      {lawLinks(law)}
    </li>;
  })}</ol>;
}

export function BlocPanel({ laws, bloc }: { laws: VoteLaw[]; bloc: Bloc }) {
  const [filter, setFilter] = useState<'all' | 'no' | 'yes'>('no');
  const [limit, setLimit] = useState(30);
  const summary = useMemo(() => blocSummary(laws, bloc), [laws, bloc]);
  const rows = useMemo(() => laws.map(law => ({ law, s: blocStance(law, bloc) })).filter(({ s }) => {
    if (s.shu === 'none' && !s.san) return false;
    if (filter === 'no') return s.shu === 'no' || s.shu === 'split' || (s.san?.no ?? 0) > 0;
    if (filter === 'yes') return s.shu === 'yes' || s.shu === 'split' || (s.san?.yes ?? 0) > 0;
    return true;
  }), [laws, bloc, filter]);
  return <div className="votes-bloc">
    <p className="votes-summary">
      衆議院：記載のある{summary.shuLaws}本のうち、賛成側 {summary.shuYes}本・反対側 {summary.shuNo}本。
      参議院：{summary.sanLaws}本の押しボタン採決で、賛成 {summary.sanYes.toLocaleString()}票・反対 {summary.sanNo.toLocaleString()}票。
    </p>
    <div className="votes-seg" role="group" aria-label="絞り込み">{([['no', '反対した（反対票が出た）'], ['yes', '賛成した'], ['all', 'すべて']] as const).map(([k, label]) => <button key={k} type="button" aria-pressed={filter === k} onClick={() => { setFilter(k); setLimit(30); }}>{label}</button>)}</div>
    <p className="fine-note">{rows.length.toLocaleString()}本（新しい順）。この系統の会派が衆議院で賛成側にいたか、参議院で何票入れたかです。</p>
    <ul className="votes-rows">{rows.slice(0, limit).map(({ law, s }) => <li key={law.id}>
      <span className="votes-date">{dateOf(law)}</span>
      <span className="votes-title">{law.title}</span>
      <span className={`votes-pill is-${s.shu}`}>衆 {STANCE_LABEL[s.shu]}</span>
      <span className={`votes-pill ${s.san ? (s.san.no > 0 ? 'is-san-no' : 'is-yes') : 'is-none'}`}>{s.san ? `参 賛成${s.san.yes}・反対${s.san.no}` : law.san?.method === 'standing' ? '参 起立採決' : '参 記載なし'}</span>
      {lawLinks(law)}
    </li>)}</ul>
    {rows.length > limit && <button type="button" className="votes-more" onClick={() => setLimit(limit + 50)}>さらに50本見る（残り {(rows.length - limit).toLocaleString()}本）</button>}
  </div>;
}

export function MemberSearch({ data, laws }: { data: PublicVotes; laws: VoteLaw[] }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState('');
  const noByMember = useMemo(() => noLawsByMember(data.laws, data.members.length), [data]);
  const shown = useMemo(() => {
    const q = query.replace(/[\s　]/g, '');
    const list = data.members.map((m, index) => ({ m, index })).filter(({ m }) => !q || m.name.includes(q));
    return list.slice(0, q ? 20 : 10);
  }, [data, query]);
  const visible = new Set(laws.map(l => l.id));
  return <div className="votes-members">
    <label className="votes-search">議員の名前（姓か名の一部）<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="例：山本" /></label>
    {!query && <p className="fine-note">名前を入れていません。反対票が多い順に10人を出しています。</p>}
    <ul className="votes-rows">{shown.map(({ m, index }) => {
      const nos = noByMember[index].filter(i => visible.has(data.laws[i].id));
      return <li key={m.name} className="votes-member">
        <button type="button" aria-expanded={open === m.name} onClick={() => setOpen(open === m.name ? '' : m.name)}>
          <strong>{m.name}</strong><span>{m.group}（最後の採決時）</span><span>賛成 {m.yes}・反対 {m.no}・欠席 {m.absent}</span>
        </button>
        {open === m.name && <div className="votes-member-detail">
          <p className="fine-note">反対した法律：選んだ期間で{nos.length}本（新しい順に最大40本まで）。</p>
          <ul>{nos.slice(0, 40).map(i => <li key={data.laws[i].id}><span className="votes-date">{dateOf(data.laws[i])}</span> {data.laws[i].title} <a href={data.laws[i].san!.url} target="_blank" rel="noopener noreferrer">採決</a></li>)}</ul>
        </div>}
      </li>;
    })}</ul>
  </div>;
}

export function VotesPage() {
  useEffect(() => { document.title = PUBLIC_SITE ? '政党・議員の賛否｜試作版' : '政党・議員の賛否｜国賊／国士ランキング'; }, []);
  const [data, setData] = useState<PublicVotes | null>(null);
  const [error, setError] = useState('');
  const [start, setStart] = useState<StartYear>(() => { const v = new URLSearchParams(window.location.search).get('from'); return (START_YEARS as readonly string[]).includes(v ?? '') ? v as StartYear : '2020'; });
  const [bloc, setBloc] = useState<Bloc>(() => { const v = new URLSearchParams(window.location.search).get('party'); return (BLOCS as readonly string[]).includes(v ?? '') ? v as Bloc : '自民'; });
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionVotesUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        const value = parseVotes(await response.text());
        if (!controller.signal.aborted) { setData(value); setError(''); }
      } catch { if (!controller.signal.aborted) { setData(null); setError('賛否データを読み込めませんでした。'); } }
    })();
    return () => controller.abort();
  }, []);
  function pick(next: { start?: StartYear; bloc?: Bloc }) {
    const s = next.start ?? start, b = next.bloc ?? bloc;
    setStart(s); setBloc(b);
    window.history.replaceState(null, '', `/votes?from=${s}&party=${encodeURIComponent(b)}`);
  }
  const laws = useMemo(() => data ? fromYear(data.laws, start) : [], [data, start]);
  const latest = data?.laws[0] ? dateOf(data.laws[0]) : '';
  return <SiteShell active="/votes" label="政党・議員の賛否" className="votes-page"><main>
    <h2>どの政党・議員が、どの法律に賛成・反対したか</h2>
    <p>成立した法律について、衆議院は会派ごと、参議院は押しボタン式の採決で議員ごとの賛否を並べます。点数や責任の判定ではなく、記録そのものです。</p>
    {error && <p className="state-banner" role="alert">{error}</p>}
    {data && <>
      <section className="real-intake votes-controls" aria-label="表示の切り替え">
        <label>見る期間<select value={start} onChange={e => pick({ start: e.target.value as StartYear })}>{START_YEARS.map(y => <option key={y} value={y}>{startLabel(y)}</option>)}</select></label>
        <p className="fine-note">最新の法律：{latest}公布。{laws.length.toLocaleString()}本が対象です。</p>
      </section>
      <section aria-labelledby="votes-recent-h"><h3 id="votes-recent-h">最近成立した法律の賛否</h3><RecentLaws laws={laws} /></section>
      <section aria-labelledby="votes-bloc-h"><h3 id="votes-bloc-h">政党（系統）ごとの賛否</h3>
        <div className="votes-seg" role="group" aria-label="政党の系統">{BLOCS.map(b => <button key={b} type="button" aria-pressed={bloc === b} onClick={() => pick({ bloc: b })}>{b}</button>)}</div>
        <BlocPanel laws={laws} bloc={bloc} />
      </section>
      <section aria-labelledby="votes-member-h"><h3 id="votes-member-h">議員ごとの賛否（参議院）</h3><MemberSearch data={data} laws={laws} /></section>
      <section aria-labelledby="votes-notes-h"><h3 id="votes-notes-h">この表の読み方と限界</h3><ul className="world-notes">{data.notes.map(n => <li key={n}>{n}</li>)}
        <li>系統の分け方は、会派名の一部で寄せています（自民・公明・立憲・共産・国民民主・維新・れいわ・社民・参政・民主系。それ以外は「その他」）。</li>
        <li>対象：衆議院の会派別 {data.counts.shugiin.toLocaleString()}本（2014年以降）、参議院の押しボタン採決 {data.counts.sangiinBallot.toLocaleString()}本（1998年以降）、起立採決 {data.counts.sangiinStanding.toLocaleString()}本。</li></ul></section>
    </>}
  </main></SiteShell>;
}
