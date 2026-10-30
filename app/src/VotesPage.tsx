import { useEffect, useMemo, useState } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { SiteShell } from './SiteHeader';
import {
  BLOCS, START_YEARS, blocStance, blocSummary, distributionMembersIdsUrl, distributionVotesUrl, fromYear, lawYear, memberIdsOf, memberPageHref, noLawsByMember, parseVotes, recentCutoff, shuSpan, startLabel,
  type Bloc, type PublicVotes, type StartYear, type VoteLaw,
} from './votes';
import { LensFilterBar, MultiSelect } from './LensFilterBar';
import { CharacterStanceChart, StanceList, buildRows } from './StanceList';
import { CHARACTERS, CHARACTER_LABEL, type Character } from './law-character';
import { lawsCatalogUrl, parseLawsCatalog, type CatalogItem } from './laws-catalog';
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
      {bloc !== '自民' && <>
        {summary.withLdpLaws > 0
          ? <>衆議院で双方の賛否が一意な{summary.withLdpLaws}本のうち、自民と同じ側（賛成か反対）は {summary.withLdpSame}/{summary.withLdpLaws}本（{Math.round(summary.withLdpSame / summary.withLdpLaws * 100)}%）。</>
          : <>衆議院で自民と比較できる法律はありません。</>}
        記載なし・会派で割れのため除外 {summary.withLdpExcluded}本。
      </>}
      会派で割れた法律は賛成側・反対側の両方に数えます。
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

/** 立憲・公明の衆院会派は合流前で記録が切れ、以後は中道改革連合として載る。切れ目を採決日で示す（この系統が載った期間は全期間で見る）。 */
export function MergerNote({ laws, bloc }: { laws: VoteLaw[]; bloc: Bloc }) {
  if (bloc !== '立憲' && bloc !== '公明') return null;
  const own = shuSpan(laws, bloc), next = shuSpan(laws, '中道改革連合');
  if (!own.last || !next.first || own.last >= next.first) return null;
  return <p className="fine-note votes-merger">衆議院の{bloc}の会派は{own.last}の採決が最後で、{next.first}以降は「中道改革連合・無所属」の会派で記録されます（「中道改革連合」の系統で見られます）。選んだ期間がそれより後だけだと、衆議院は「記載なし」になります。参議院は{bloc}のまま続きます。</p>;
}

/** linkable：議員ページ（/members）に載っている人物ID。名前がこれと一致するときだけ議員ページへのリンクを出す。 */
export function MemberSearch({ data, laws, linkable }: { data: PublicVotes; laws: VoteLaw[]; linkable?: ReadonlySet<string> }) {
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
    {!query && <p className="fine-note">名前を入れていません。全期間の反対票が多い順に10人を出しています。</p>}
    <ul className="votes-rows">{shown.map(({ m, index }) => {
      const nos = noByMember[index].filter(i => visible.has(data.laws[i].id));
      return <li key={m.name} className="votes-member">
        <button type="button" aria-expanded={open === m.name} onClick={() => setOpen(open === m.name ? '' : m.name)}>
          <strong>{m.name}</strong><span>{m.group}（最後の採決時）</span><span>全期間：賛成 {m.yes}・反対 {m.no}・欠席 {m.absent}</span><span>選択期間の反対法数 {nos.length}本</span>
        </button>
        {open === m.name && <div className="votes-member-detail">
          {memberPageHref(m.name, linkable) && <p><a href={memberPageHref(m.name, linkable)!}>この議員の額と一次資料のつながり（議員ページ）</a></p>}
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
  const [start, setStart] = useState<StartYear>(() => { const v = new URLSearchParams(window.location.search).get('from'); return (START_YEARS as readonly string[]).includes(v ?? '') ? v as StartYear : 'recent4'; });
  const [blocs, setBlocs] = useState<Bloc[]>(() => { const v = new URLSearchParams(window.location.search).get('party'); const list = (v ?? '').split(',').filter((b): b is Bloc => (BLOCS as readonly string[]).includes(b)); return list.length ? list : ['自民']; });
  const bloc = blocs[0] ?? '自民';
  const [chars, setChars] = useState<Character[]>(() => (new URLSearchParams(window.location.search).get('nature') ?? '').split(',').filter((c): c is Character => (CHARACTERS as readonly string[]).includes(c)));
  const [fields, setFields] = useState<string[]>(() => (new URLSearchParams(window.location.search).get('field') ?? '').split(',').filter(Boolean));
  const [catalog, setCatalog] = useState<ReadonlyMap<string, CatalogItem>>(new Map());
  useEffect(() => {
    const controller = new AbortController();
    void fetch(lawsCatalogUrl, { signal: controller.signal, cache: 'no-store' })
      .then(r => r.ok ? r.text() : Promise.reject(new Error('missing')))
      .then(text => { const c = parseLawsCatalog(text); setCatalog(new Map([...c.laws, ...c.policies].map(item => [item.id, item]))); }).catch(() => undefined);
    return () => controller.abort();
  }, []);
  // 議員ページの人物ID（読めなければリンクを出さないだけ）。
  const [memberIds, setMemberIds] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const controller = new AbortController();
    void fetch(distributionMembersIdsUrl, { signal: controller.signal, cache: 'no-store' })
      .then(r => r.ok ? r.text() : Promise.reject(new Error('missing'))).then(text => setMemberIds(memberIdsOf(text))).catch(() => undefined);
    return () => controller.abort();
  }, []);
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
  function pick(next: { start?: StartYear; blocs?: Bloc[]; chars?: Character[]; fields?: string[] }) {
    const s = next.start ?? start, b = next.blocs ?? blocs, c = next.chars ?? chars, f = next.fields ?? fields;
    setStart(s); setBlocs(b); setChars(c); setFields(f);
    const params = new URLSearchParams({ from: s });
    if (b.length) params.set('party', b.join(','));
    if (c.length) params.set('nature', c.join(','));
    if (f.length) params.set('field', f.join(','));
    window.history.replaceState(null, '', `/votes?${params}`);
  }
  const fieldOptions = useMemo(() => [...new Set([...catalog.values()].map(i => i.field).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ja')).map(f => ({ value: f, label: f })), [catalog]);
  const rows = useMemo(() => {
    const all = buildRows(data ? fromYear(data.laws, start) : [], catalog);
    return all.filter(r => (!chars.length || chars.includes(r.character)) && (!fields.length || (r.info && fields.includes(r.info.field)))).sort((a, b) => (dateOf(b.law) > dateOf(a.law) ? 1 : -1));
  }, [data, start, catalog, chars, fields]);
  const laws = useMemo(() => data ? fromYear(data.laws, start) : [], [data, start]);
  const latest = data?.laws.map(dateOf).reduce((a, b) => b > a ? b : a, '') ?? '';
  return <SiteShell active="/votes" label="政党・議員の賛否" className="votes-page"><main id="main">
    <LensFilterBar note={<>法律の性格は題名と要約のことばからの暫定の機械分類です（人や AI の確認前）。分野は法律ランキングと同じ分け方です。{!data ? '' : `${rows.length.toLocaleString()}本が条件に合います。`}</>}>
      <MultiSelect label="政党（複数可）" allLabel="自民" options={BLOCS.map(b => ({ value: b, label: b }))} selected={blocs} onChange={next => pick({ blocs: next })} />
      <MultiSelect label="どんな法律か" allLabel="すべて" options={CHARACTERS.map(c => ({ value: c, label: CHARACTER_LABEL[c] }))} selected={chars} onChange={next => pick({ chars: next })} />
      <MultiSelect label="何の分野か" allLabel="すべて" options={fieldOptions} selected={fields} onChange={next => pick({ fields: next })} />
    </LensFilterBar>
    <h1>どの政党・議員が、どの法律に賛成・反対したか</h1>
    <p>成立した法律について、衆議院は会派ごと、参議院は押しボタン式の採決で議員ごとの賛否を並べます。点数や責任の判定ではなく、記録そのものです。</p>
    {error && <p className="state-banner" role="alert">{error}</p>}
    {data && <>
      <section className="real-intake votes-controls" aria-label="表示の切り替え">
        <label>見る期間<select value={start} onChange={e => pick({ start: e.target.value as StartYear })}>{START_YEARS.map(y => <option key={y} value={y}>{startLabel(y)}</option>)}</select></label>
        <p className="fine-note">データ最新日：{latest || '日付なし'}。公布日を使い、なければ衆院、次に参院の採決日を使います。{laws.length.toLocaleString()}本が対象です。{start === 'recent4' && latest && <>期間は{recentCutoff(data.laws)}より後から{latest}まで（開始日を除き、終了日を含む）です。</>}</p>
      </section>
      <section aria-labelledby="votes-recent-h"><h3 id="votes-recent-h">法律ごとの性格と、{blocs.join('・')}の態度</h3>
        <p className="fine-note">赤い枠は、確かな額で損失側と出た法律だけです（ほかは目立たせていません）。「衆」は衆議院の会派の賛否、「参 賛成/反対」は参議院の票数です。</p>
        <CharacterStanceChart rows={rows} blocs={blocs} />
        <StanceList rows={rows} blocs={blocs} />
      </section>
      {blocs.length === 1 && <section aria-labelledby="votes-bloc-h"><h3 id="votes-bloc-h">{bloc}の賛否のまとめ</h3>
        <MergerNote laws={data.laws} bloc={bloc} />
        <BlocPanel laws={laws} bloc={bloc} />
      </section>}
      <section aria-labelledby="votes-member-h"><h3 id="votes-member-h">議員ごとの賛否（参議院）</h3><MemberSearch data={data} laws={laws} linkable={memberIds} /></section>
      <section aria-labelledby="votes-notes-h"><h3 id="votes-notes-h">この表の読み方と限界</h3><ul className="world-notes">{data.notes.map(n => <li key={n}>{n}</li>)}
        <li>系統の分け方は、会派名の一部で寄せています（自民・公明・立憲・共産・国民民主・維新・れいわ・社民・参政・中道改革連合・チームみらい・日本保守党・民主系。それ以外は「その他」）。中道改革連合は立憲・公明とは別の会派として数え、合算しません。</li>
        <li>対象：衆議院の会派別 {data.counts.shugiin.toLocaleString()}本（2014年以降）、参議院の押しボタン採決 {data.counts.sangiinBallot.toLocaleString()}本（1998年以降）、起立採決 {data.counts.sangiinStanding.toLocaleString()}本。</li></ul></section>
    </>}
  </main></SiteShell>;
}
