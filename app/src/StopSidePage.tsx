import { useEffect, useMemo, useState } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { SiteShell } from './SiteHeader';
import {
  CHECK_LABEL, CHECK_NOTE, countByState, distributionStopSideUrl, filterActors, filterRulings, parseStopSide, rulingKind,
  type ActorFilter, type CheckState, type StopActor, type StopRuling, type StopSide,
} from './stop-side';
import './stop-side.css';

const STATES: (CheckState | 'all')[] = ['all', 'c', 'h', 'u'];
const STATE_BUTTON = { all: 'すべて', ...CHECK_LABEL } as const;
const PAGE = 40;

function StateMark({ v, reason }: { v: CheckState; reason?: string }) {
  return <span className={`stop-state is-${v}`} title={CHECK_NOTE[v]}>{CHECK_LABEL[v]}{v === 'h' && reason ? `：${reason}` : ''}</span>;
}

/** 一次資料のリンクは、URL がある行だけ。無い行は「一次資料のリンクなし」と書く。 */
function SourceLink({ url, page }: { url?: string; page?: string }) {
  return url
    ? <a href={url} target="_blank" rel="noopener noreferrer">一次資料（官公庁の資料）を開く{page ? `　${page}` : ''}</a>
    : <span className="stop-nolink">一次資料のリンクなし</span>;
}

export function ActorRow({ a }: { a: StopActor }) {
  const meta = [a.k && `技術：${a.k}`, a.l && `法令：${a.l}`, a.a && `相手・会議：${a.a}`].filter(Boolean).join('　');
  return <li className="stop-item">
    <div className="stop-head"><h4>{a.o}</h4>{a.s && <span className="stop-pill">{a.s}</span>}<StateMark v={a.v} reason={a.r} />{a.d && <span className="stop-date">{a.d}</span>}</div>
    {a.t && <p><strong>{a.t}</strong></p>}
    {a.x && <p>{a.x}</p>}
    {meta && <p className="stop-meta">{meta}</p>}
    <p className="stop-meta"><SourceLink url={a.u} page={a.p} /></p>
  </li>;
}

export function RulingRow({ r }: { r: StopRuling }) {
  return <li className="stop-item stop-ruling">
    <div className="stop-head"><h4>{r.name}</h4><span className="stop-pill">{rulingKind(r)}</span><span className="stop-state is-r" title="判決日・事件番号・規制への判断が、独立した2系統で一致">2系統一致</span>{r.fulltext === 'no' && <span className="stop-state is-u" title="全文PDFを取得していない">全文は未取得</span>}</div>
    <dl>
      <dt>裁判所・判決日</dt><dd>{r.court}　{r.date}　{r.no}</dd>
      <dt>止められた規制</dt><dd>{r.rule}{r.agency ? `（所管：${r.agency}）` : ''}</dd>
      <dt>規制への判断</dt><dd>{r.judge}{r.result ? `（結果：${r.result}）` : ''}</dd>
      <dt>判断の要旨</dt><dd>{r.summary}</dd>
      {r.after && <dt>その後の変化</dt>}{r.after && <dd>{r.after}</dd>}
    </dl>
    <p className="stop-meta">{r.u ? <a href={r.u} target="_blank" rel="noopener noreferrer">裁判所の判例ページを開く</a> : <span className="stop-nolink">判例ページのリンクなし</span>}</p>
  </li>;
}

function param(name: string, allowed: readonly string[], fallback: string): string {
  const v = new URLSearchParams(window.location.search).get(name) ?? '';
  return allowed.includes(v) ? v : fallback;
}

export function ActorSection({ data }: { data: StopSide }) {
  const groupKeys = ['all', ...data.groups.map(g => g.key)];
  const [filter, setFilter] = useState<ActorFilter>(() => ({ group: param('g', groupKeys, 'all'), state: param('v', STATES, 'all') as ActorFilter['state'], query: new URLSearchParams(window.location.search).get('q') ?? '' }));
  const [limit, setLimit] = useState(PAGE);
  const rows = useMemo(() => filterActors(data.actors, filter), [data, filter]);
  const counts = useMemo(() => countByState(rows), [rows]);
  const group = data.groups.find(g => g.key === filter.group);
  function pick(next: Partial<ActorFilter>) {
    const f = { ...filter, ...next };
    setFilter(f); setLimit(PAGE);
    const q = new URLSearchParams();
    if (f.group !== 'all') q.set('g', f.group);
    if (f.state !== 'all') q.set('v', f.state);
    if (f.query) q.set('q', f.query);
    window.history.replaceState(null, '', `/stop-side${q.size ? `?${q}` : ''}`);
  }
  return <section aria-labelledby="stop-actors-h"><h3 id="stop-actors-h">止めた側の記録（{data.counts.actors.toLocaleString()}件）</h3>
    <div className="stop-controls">
      <label>系統<select value={filter.group} onChange={e => pick({ group: e.target.value })}><option value="all">すべての系統</option>{data.groups.map(g => <option key={g.key} value={g.key}>{g.label}</option>)}</select></label>
      <div className="stop-seg" role="group" aria-label="確認の状態">{STATES.map(s => <button key={s} type="button" aria-pressed={filter.state === s} onClick={() => pick({ state: s })}>{STATE_BUTTON[s]}</button>)}</div>
      <label>ことばで絞る（空白で複数）<input type="search" value={filter.query} onChange={e => pick({ query: e.target.value })} placeholder="例：ライドシェア 道路運送法" /></label>
    </div>
    {group && <p className="stop-about">{group.about}</p>}
    <ul className="stop-counts" aria-label="いまの条件の件数"><li><strong>{rows.length.toLocaleString()}</strong>件</li>{(['c', 'h', 'u'] as const).map(s => <li key={s}><strong>{counts[s].toLocaleString()}</strong>{CHECK_LABEL[s]}</li>)}</ul>
    <ul className="stop-list">{rows.slice(0, limit).map((a, i) => <ActorRow key={`${a.h}-${i}`} a={a} />)}</ul>
    {rows.length === 0 && <p className="empty-state">条件に合う記録がありません。</p>}
    {rows.length > limit && <button type="button" className="stop-more" onClick={() => setLimit(limit + 100)}>さらに100件見る（残り {(rows.length - limit).toLocaleString()}件）</button>}
  </section>;
}

export function RulingSection({ data }: { data: StopSide }) {
  const kinds = useMemo(() => [...new Set(data.rulings.map(rulingKind))], [data]);
  const [kind, setKind] = useState('all');
  const [query, setQuery] = useState('');
  const rows = useMemo(() => filterRulings(data.rulings, kind, query), [data, kind, query]);
  return <section aria-labelledby="stop-rulings-h"><h3 id="stop-rulings-h">規制をめぐる判決（{data.counts.rulings}件）</h3>
    <p className="stop-about">規制が裁判で退けられた例と、争われて維持された例です。判決日・事件番号・規制への判断が独立した2系統で一致したものだけを載せ、全文は裁判所の判例ページで読めます。</p>
    <div className="stop-controls">
      <div className="stop-seg" role="group" aria-label="規制への判断">{['all', ...kinds].map(k => <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>{k === 'all' ? 'すべて' : k}</button>)}</div>
      <label>ことばで絞る<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="例：タクシー" /></label>
    </div>
    <p className="fine-note">{rows.length}件（古い順）。</p>
    <ul className="stop-list">{rows.map(r => <RulingRow key={r.id} r={r} />)}</ul>
    <h4>保留の判決（{data.rulingsHeld.length}件）</h4>
    <p className="stop-about">判決日・事件番号・規制への判断のどれかが、2系統でそろわなかったものです。中身は載せず、理由だけ示します。</p>
    <ul className="stop-held">{data.rulingsHeld.map(h => <li key={h.id}><strong>{h.name}</strong>　{h.reason}</li>)}</ul>
  </section>;
}

export function StopSidePage() {
  useEffect(() => { document.title = PUBLIC_SITE ? '技術を止めた側と判決｜試作版' : '技術を止めた側と判決｜国賊／国士ランキング'; }, []);
  const [data, setData] = useState<StopSide | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionStopSideUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        const value = parseStopSide(await response.text());
        if (!controller.signal.aborted) { setData(value); setError(''); }
      } catch { if (!controller.signal.aborted) { setData(null); setError('止めた側のデータを読み込めませんでした。'); } }
    })();
    return () => controller.abort();
  }, []);
  return <SiteShell active="/stop-side" label="技術を止めた側と判決" className="stop-page"><main>
    <h2>新しい技術を、誰が止めたのか</h2>
    <p>所管省庁の回答、審議会で慎重を述べた団体、再就職、効果の出ない事業、上乗せ条例、そして規制をめぐる判決を、確認の状態の印つきで全件並べます。責任の判定や点数ではなく、記録そのものです。</p>
    {error && <p className="state-banner" role="alert">{error}</p>}
    {data && <>
      <ul className="stop-counts" aria-label="全体の件数">
        <li><strong>{data.counts.actors.toLocaleString()}</strong>件の記録</li>
        {(['c', 'h', 'u'] as const).map(s => <li key={s}><strong>{data.counts[{ c: 'confirmed', h: 'held', u: 'unchecked' }[s]].toLocaleString()}</strong>{CHECK_LABEL[s]}</li>)}
        <li><strong>{data.counts.rulings}</strong>件の判決</li>
      </ul>
      <p className="fine-note">印の見方：確認済み＝{CHECK_NOTE.c}。保留＝{CHECK_NOTE.h}。未照合＝{CHECK_NOTE.u}。保留と未照合は、そのまま正しいとは言えません。</p>
      <ActorSection data={data} />
      <RulingSection data={data} />
      <section aria-labelledby="stop-notes-h"><h3 id="stop-notes-h">この表の読み方と限界</h3><ul className="world-notes">{data.notes.map(n => <li key={n}>{n}</li>)}</ul></section>
    </>}
  </main></SiteShell>;
}
