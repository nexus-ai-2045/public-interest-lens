import { useEffect, useMemo, useState } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { SiteShell } from './SiteHeader';
import { distributionPledgesUrl, parsePledges, pledgeRates, stanceTally, type PledgeItem, type PledgeStatus, type PublicPledges } from './pledges';
import './votes.css';

const STATUS_LABEL: Record<PledgeStatus, string> = { enacted: '対応する法律が成立', review: '要確認（判定が割れた）', none: '対応する成立法なし', no_law: '法律を要さない' };
const STANCE_LABEL = { yes: '賛成', no: '反対', split: '会派で割れ', none: '記載なし' } as const;
const STATUS_ORDER: PledgeStatus[] = ['enacted', 'review', 'none', 'no_law'];

export function PledgeItems({ items, filter }: { items: PledgeItem[]; filter: PledgeStatus | 'all' }) {
  const [limit, setLimit] = useState(30);
  const rows = items.filter(i => filter === 'all' || i.status === filter);
  return <>
    <ul className="votes-rows">{rows.slice(0, limit).map(i => <li key={i.id}>
      <span className="votes-date">{i.id}</span>
      <span className="votes-title">{i.text}</span>
      <span className={`votes-pill ${i.status === 'enacted' ? 'is-yes' : i.status === 'review' ? 'is-split' : 'is-none'}`}>{STATUS_LABEL[i.status]}</span>
      {i.laws.length > 0 && <span className="votes-links">{i.laws.map(l => <a key={l.id} href={l.url} target="_blank" rel="noopener noreferrer">{l.title}（この党：{STANCE_LABEL[l.stance]}）</a>)}</span>}
    </li>)}</ul>
    {rows.length > limit && <button type="button" className="votes-more" onClick={() => setLimit(limit + 50)}>さらに50項目見る（残り {(rows.length - limit).toLocaleString()}項目）</button>}
  </>;
}

export function PledgeParty({ data, name }: { data: PublicPledges; name: string }) {
  const [filter, setFilter] = useState<PledgeStatus | 'all'>('enacted');
  const p = data.parties.find(x => x.name === name)!;
  const r = pledgeRates(p), t = stanceTally(p);
  return <div className="votes-bloc">
    <p className="votes-summary">
      公約{p.total}項目のうち、{STATUS_ORDER.map(s => `${STATUS_LABEL[s]} ${p.counts[s]}`).join('・')}。
      成立の割合は<strong>{r.confirmed ?? '—'}%（確定分）〜{r.upper ?? '—'}%（要確認が全部成立だった場合）</strong>。
      法律を要さない項目を分母から外すと {r.measurable ?? '—'}%（{r.measurableDenominator}項目中）。
      {!p.governing && t.laws > 0 && <>対応する成立法{t.laws}本のうち、この党が衆議院で賛成側にいたのは{t.yes}本・反対側{t.no}本・会派で割れ{t.split}本・記載なし{t.none}本。</>}
      {p.governing && <>政権党（与党）の党です。野党と成立の割合を直接比べないでください。</>}
    </p>
    <p className="fine-note">出典：<a href={p.source.url} target="_blank" rel="noopener noreferrer">{p.name}の公式公約</a>{p.source.note && `（${p.source.note}）`}</p>
    <div className="votes-seg" role="group" aria-label="絞り込み">{(['all', ...STATUS_ORDER] as const).map(k => <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>{k === 'all' ? `すべて ${p.total}` : `${STATUS_LABEL[k]} ${p.counts[k]}`}</button>)}</div>
    <PledgeItems key={name + filter} items={p.items} filter={filter} />
  </div>;
}

export function PledgesPage() {
  useEffect(() => { document.title = PUBLIC_SITE ? '公約と成立した法律｜試作版' : '公約と成立した法律｜国賊／国士ランキング'; }, []);
  const [data, setData] = useState<PublicPledges | null>(null);
  const [error, setError] = useState('');
  const [name, setName] = useState(() => new URLSearchParams(window.location.search).get('party') ?? '');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionPledgesUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        const value = parsePledges(await response.text());
        if (!controller.signal.aborted) { setData(value); setError(''); }
      } catch { if (!controller.signal.aborted) { setData(null); setError('公約のデータを読み込めませんでした。'); } }
    })();
    return () => controller.abort();
  }, []);
  const current = useMemo(() => data?.parties.find(p => p.name === name)?.name ?? data?.parties[0]?.name ?? '', [data, name]);
  function pick(next: string) { setName(next); window.history.replaceState(null, '', `/pledges?party=${encodeURIComponent(next)}`); }
  return <SiteShell active="/pledges" label="公約と成立した法律" className="votes-page"><main>
    <h2>党の公約に、対応する法律は成立したか</h2>
    <p>{data?.election.name ?? '第50回衆議院議員総選挙'}（{data?.election.date ?? '2024-10-27'}）の各党の公約を項目に分け、選挙後に成立した法律と突き合わせます。国賊・国士の点数や順位には入れない、別の表示です。</p>
    {error && <p className="state-banner" role="alert">{error}</p>}
    {data && <>
      <section aria-labelledby="pledge-sum-h"><h3 id="pledge-sum-h">党ごとの一覧（{data.lawsAsOf}公布までの成立法）</h3>
        <div className="votes-seg" role="group" aria-label="党">{data.parties.map(p => <button key={p.name} type="button" aria-pressed={current === p.name} onClick={() => pick(p.name)}>{p.name}{p.governing ? '（与党）' : ''}</button>)}</div>
        {current && <PledgeParty data={data} name={current} />}
      </section>
      <section aria-labelledby="pledge-cmp-h"><h3 id="pledge-cmp-h">党の比較（与党同士・野党同士で見る）</h3>
        <ul className="votes-rows">{data.parties.map(p => { const r = pledgeRates(p); return <li key={p.name}>
          <span className="votes-title">{p.name}{p.governing ? '（与党）' : '（野党）'}</span>
          <span className="votes-summary">{p.total}項目　成立 {r.confirmed ?? '—'}〜{r.upper ?? '—'}%　法律不要を除くと {r.measurable ?? '—'}%</span>
        </li>; })}</ul>
      </section>
      <section aria-labelledby="pledge-notes-h"><h3 id="pledge-notes-h">この表の読み方と限界</h3><ul className="world-notes">{data.notes.map(n => <li key={n}>{n}</li>)}</ul></section>
    </>}
  </main></SiteShell>;
}
