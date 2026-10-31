import { useMemo, useState } from 'react';
import { blocStance, type Bloc, type VoteLaw } from './votes';
import { CHARACTER_LABEL, CHARACTER_SHORT, characterOf } from './law-character';
import { plainLawName } from './law-name';
import type { CatalogItem } from './laws-catalog';
import { formatYen } from './laws-catalog';

const STANCE = { yes: '賛成', no: '反対', split: '割れ', none: '—' } as const;
const dateOf = (law: VoteLaw) => law.promulgated ?? law.shu?.date ?? law.san?.date ?? '';

export type StanceRow = { law: VoteLaw; info?: CatalogItem; character: ReturnType<typeof characterOf>; title: string };

/** 明らかな悪法：確かな額で損失側と出たものだけ（参考の額は目立たせない）。 */
export const isClearlyBad = (info?: CatalogItem) => !!info && info.side === 'loss' && info.step === 'published' && !!info.amount;

export function StanceList({ rows, blocs, limit: initial = 30 }: { rows: StanceRow[]; blocs: readonly Bloc[]; limit?: number }) {
  const [limit, setLimit] = useState(initial);
  const shown = useMemo(() => rows.slice(0, limit), [rows, limit]);
  return <>
    <ul className="stance-list">{shown.map(({ law, info, character, title }) => {
      const bad = isClearlyBad(info);
      return <li key={law.id} className={`stance-law${bad ? ' is-bad' : ''}`}>
        <div className="stance-head">
          <span className="votes-date">{dateOf(law)}</span>
          <span className="votes-title">{title}</span>
        </div>
        {info?.what && <p className="stance-sub">正式名：{law.title}（上の名前は国会会議録の AI 要約）</p>}
        <div className="stance-tags">
          <span className={`stance-tag char-${character}`} title={`${CHARACTER_LABEL[character]}（題名・要約のことばからの暫定分類）`}>{CHARACTER_SHORT[character]}</span>
          {info?.field && <span className="stance-tag">{info.field}</span>}
          {bad && info?.amount && <span className="stance-tag loss">損失 {formatYen(info.amount.median)}</span>}
          {info?.side === 'benefit' && info.step === 'published' && info.amount && <span className="stance-tag">便益 {formatYen(info.amount.median)}</span>}
        </div>
        <div className="stance-chips">{blocs.map(bloc => {
          const s = blocStance(law, bloc);
          const san = s.san ? `参 ${s.san.yes}/${s.san.no}` : law.san?.method === 'standing' ? '参 起立' : '';
          const cls = s.shu !== 'none' ? s.shu : s.san ? (s.san.no > 0 ? 'no' : 'yes') : 'none';
          return <span key={bloc} className={`stance-chip is-${cls}`}><b>{bloc}</b>衆 {STANCE[s.shu]}{san && `・${san}`}</span>;
        })}</div>
        <p className="stance-sub"><a href={law.url} target="_blank" rel="noopener noreferrer">議案の経過</a>{law.san && <>　<a href={law.san.url} target="_blank" rel="noopener noreferrer">参院の採決</a></>}</p>
      </li>;
    })}</ul>
    {rows.length > limit && <button type="button" className="votes-more" onClick={() => setLimit(limit + 50)}>さらに50本見る（残り {(rows.length - limit).toLocaleString()}本）</button>}
  </>;
}

export function buildRows(laws: VoteLaw[], catalog: ReadonlyMap<string, CatalogItem>): StanceRow[] {
  return laws.map(law => {
    const info = catalog.get(law.id);
    const title = info?.what ? plainLawName(info.what) : law.title;
    return { law, info, character: characterOf(`${law.title}${info?.what ?? ''}`), title };
  });
}

/** 性格ごとに、選んだ政党がどちら側に立ったか（衆院の会派の賛否。割れは両方に数える）。 */
export function characterStances(rows: StanceRow[], bloc: Bloc): { character: StanceRow['character']; yes: number; no: number }[] {
  const out = (['regulate', 'protect', 'improve', 'other'] as const).map(character => ({ character, yes: 0, no: 0 }));
  for (const { law, character } of rows) {
    const s = blocStance(law, bloc);
    const row = out.find(o => o.character === character)!;
    if (s.shu === 'yes' || s.shu === 'split') row.yes += 1;
    if (s.shu === 'no' || s.shu === 'split') row.no += 1;
  }
  return out;
}

export function CharacterStanceChart({ rows, blocs }: { rows: StanceRow[]; blocs: readonly Bloc[] }) {
  return <div className="stance-chart" role="table" aria-label="法律の性格ごとの賛否の本数">
    {blocs.map(bloc => <div key={bloc} className="stance-chart-bloc" role="rowgroup">
      <p className="stance-chart-name"><strong>{bloc}</strong></p>
      {characterStances(rows, bloc).map(({ character, yes, no }) => {
        const total = yes + no;
        return <div key={character} className="stance-chart-row" role="row">
          <span className="stance-chart-label">{CHARACTER_SHORT[character]}</span>
          <span className="stance-bar" aria-hidden="true"><i className="y" style={{ width: total ? `${yes / total * 100}%` : 0 }} /><i className="n" style={{ width: total ? `${no / total * 100}%` : 0 }} /></span>
          <span className="stance-chart-num">賛成 {yes}・反対 {no}</span>
        </div>;
      })}
    </div>)}
    <p className="fine-note">衆議院で会派の賛否が記録された法律の本数です（割れた法律は両方に数えます）。緑が賛成、赤が反対。</p>
  </div>;
}
