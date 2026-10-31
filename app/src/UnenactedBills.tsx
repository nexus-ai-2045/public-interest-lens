import { useEffect, useMemo, useState } from 'react';
import { characterOf, type Character } from './law-character';
import { filterUnenacted, parseUnenacted, unenactedUrl, type UnenactedData } from './unenacted';

const KIND_LABEL: Record<string, string> = { 閣法: '内閣が出した（閣法）', 衆法: '衆議院議員が出した（衆法）', 参法: '参議院議員が出した（参法）' };

/** 成立しなかった提出法案の暫定の規模点。成立した法律の額とは別の表で、向き（良い悪い）は付けない。 */
export function UnenactedBills({ natures }: { natures: readonly Character[] }) {
  const [data, setData] = useState<UnenactedData | null>(null);
  const [kind, setKind] = useState('');
  const [field, setField] = useState('');
  const [limit, setLimit] = useState(30);
  useEffect(() => {
    const controller = new AbortController();
    void fetch(unenactedUrl, { signal: controller.signal, cache: 'no-store' }).then(r => r.ok ? r.text() : Promise.reject(new Error('missing')))
      .then(text => setData(parseUnenacted(text))).catch(() => undefined);
    return () => controller.abort();
  }, []);
  const fields = useMemo(() => [...new Set((data?.bills ?? []).map(b => b.field))].sort((a, b) => a.localeCompare(b, 'ja')), [data]);
  const rows = useMemo(() => filterUnenacted(data?.bills ?? [], { kind, field }, b => !natures.length || natures.includes(characterOf(b.title))), [data, kind, field, natures]);
  if (!data) return null;
  const max = Math.max(1, ...rows.map(b => b.scale));
  return <section className="unenacted" aria-label="成立しなかった提出法案">
    <h3>成立しなかった提出法案の暫定の規模点</h3>
    <p className="fine-note">{data.notes.join('')}（点が付いたのは{data.counts.scored.toLocaleString('ja-JP')}本。残り{(data.counts.total - data.counts.scored).toLocaleString('ja-JP')}本は、実質改正でない・産業を特定できないなどで点を付けていません。）</p>
    <div className="unenacted-controls">
      <label>誰が出したか<select value={kind} onChange={e => { setKind(e.target.value); setLimit(30); }}><option value="">すべて</option>{Object.entries(KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select></label>
      <label>分野<select value={field} onChange={e => { setField(e.target.value); setLimit(30); }}><option value="">すべて</option>{fields.map(f => <option key={f} value={f}>{f}</option>)}</select></label>
    </div>
    <p className="fine-note" role="status">{rows.length.toLocaleString('ja-JP')}本（規模点の大きい順）。規模点は「触れる産業が日本の付加価値の何%か」で、法案の良し悪しではありません。</p>
    <ul className="unenacted-list">{rows.slice(0, limit).map(b => <li key={b.id}>
      <p className="unenacted-title">{b.title}</p>
      <p className="unenacted-meta">{b.kind}・第{b.session}回国会・{b.status}・{b.field}</p>
      <p className="unenacted-score"><span className="stance-bar" aria-hidden="true"><i className="y" style={{ width: `${b.scale / max * 100}%` }} /></span><strong>{b.scale.toFixed(1)}点</strong><small>確かさ：{b.certainty}（向きなし・円の額なし）</small>{b.url && <a href={b.url} target="_blank" rel="noopener noreferrer">議案の経過</a>}</p>
    </li>)}</ul>
    {rows.length > limit && <button type="button" className="votes-more" onClick={() => setLimit(limit + 50)}>さらに50本見る（残り {(rows.length - limit).toLocaleString('ja-JP')}本）</button>}
  </section>;
}
