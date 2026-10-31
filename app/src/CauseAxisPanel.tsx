import { useState } from 'react';
import { LineReveal, type LineSeries } from './motion';
import causeAxisData from './cause-axis.json';

export type CauseAxisData = typeof causeAxisData;
type Industry = CauseAxisData['industries'][number];

const COUNTRY_NAMES: Record<string, string> = {
  JPN: '日本', AUS: 'オーストラリア', AUT: 'オーストリア', BEL: 'ベルギー', CAN: 'カナダ', CHE: 'スイス', CZE: 'チェコ', DEU: 'ドイツ', DNK: 'デンマーク',
  ESP: 'スペイン', FIN: 'フィンランド', FRA: 'フランス', GBR: '英国', HUN: 'ハンガリー', ITA: 'イタリア', KOR: '韓国', NLD: 'オランダ', NOR: 'ノルウェー',
  POL: 'ポーランド', PRT: 'ポルトガル', SWE: 'スウェーデン', USA: '米国',
};
const countryName = (code: string) => COUNTRY_NAMES[code] ?? code;
const percent = (x: number) => `${Math.round(x * 100)}%`;
const trillion = (x: number) => `${x > 0 ? '+' : ''}${x.toLocaleString('ja-JP', { maximumFractionDigits: 1 })}兆円`;

/** 日本と比べる国の中央値の線（2000年＝100）。 */
export function industrySeries(industry: Industry): LineSeries[] {
  return [
    { id: 'JPN', label: '日本', points: industry.series.map(p => ({ year: p.year, value: p.japan * 100 })) },
    { id: 'MEDIAN', label: '比べる国の中央値', points: industry.series.map(p => ({ year: p.year, value: p.peerMedian * 100 })) },
  ];
}

/** 一言の読み方。損失の向きは「日本が比べる国より伸びなかった」、便益は「日本の方が伸びた」。 */
export function industryLead(industry: Industry): string {
  const dir = industry.direction === '損失' ? '日本の方が伸びなかった' : '日本の方が伸びた';
  const base = `${industry.name}は、比べる${industry.peerCount}か国の中央値より${dir}。2001〜2023年の差の累計は約${trillion(industry.trillionYen)}、置換検定は${industry.of}か国中${industry.rank}位`;
  return industry.certainty === '参考'
    ? `${base}で、参考として載せます（偶然とは言い切れませんが、原因の特定ではありません）。`
    : `${base}で、誤差の範囲です。額は記録だけにして、軸には配りません。`;
}

export function PeerBars({ industry }: { industry: Industry }) {
  const rows = [...industry.peers].sort((a, b) => b.ratio2023 - a.ratio2023);
  const top = Math.max(...rows.map(r => r.ratio2023), 1);
  return <ol className="world-bars cause-peers" aria-label="2023年の比（2000年＝1）">
    {rows.map((row, i) => <li key={row.country} className={row.country === 'JPN' ? 'is-japan' : undefined}>
      <span className="world-bar-name">{i + 1}. {countryName(row.country)}</span>
      <span className="world-bar-track" aria-hidden="true"><span className="world-bar" style={{ left: 0, width: `${row.ratio2023 / top * 100}%` }} /></span>
      <span className="world-bar-value">{row.ratio2023.toFixed(2)}</span>
    </li>)}
  </ol>;
}

export function AxisTable({ data }: { data: CauseAxisData }) {
  return <div className="world-table-wrap"><table className="world-table cause-axes">
    <caption>軸ごとの額と扱い（2001〜2023年の累計、実質で比べた差）</caption>
    <thead><tr><th>軸</th><th>結ぶ観測</th><th>額</th><th>扱い</th></tr></thead>
    <tbody>{data.axes.map(a => <tr key={a.code}>
      <td>{a.code} {a.name}</td>
      <td>{a.observation}{a.sharedBy > 1 && <small>（{a.sharedBy}軸で共有）</small>}{a.recordedOnly && <small>（記録だけ：{a.recordedOnly}）</small>}</td>
      <td>{a.trillionYen === null ? '—' : trillion(a.trillionYen)}</td>
      <td>{a.treatment}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function AccountingTable({ data }: { data: CauseAxisData }) {
  return <div className="world-table-wrap"><table className="world-table cause-accounting">
    <caption>失敗した側の差の要因分解（成長会計、2000→2019年。差に占める割合）</caption>
    <thead><tr><th>観測</th><th>働く人の数</th><th>資本</th><th>全要素生産性</th><th>印</th></tr></thead>
    <tbody>{data.accounting.map(a => a.labor === undefined || a.labor === null
      ? <tr key={a.code}><td>{a.name}</td><td colSpan={3}>—</td><td>{a.mark}</td></tr>
      : <tr key={a.code}><td>{a.name}<small>（比べる国 {a.peers?.length ?? 0}か国）</small></td><td>{percent(a.labor)}</td><td>{percent(a.capital ?? 0)}</td><td>{percent(a.tfp ?? 0)}</td><td>{a.mark}</td></tr>)}</tbody>
  </table></div>;
}

/** 産業別の付加価値の比較と、原因の軸の額、差の要因分解。原因の断定も、人や組織への配分もしません。 */
export function CauseAxisPanel({ data = causeAxisData, initial = 'J62_63' }: { data?: CauseAxisData; initial?: string }) {
  const [code, setCode] = useState(data.industries.some(i => i.code === initial) ? initial : data.industries[0].code);
  const industry = data.industries.find(i => i.code === code) ?? data.industries[0];
  return <section id="cause-axis" className="lower-panel cause-axis" aria-labelledby="cause-axis-heading">
    <h3 id="cause-axis-heading">産業ごとに、日本は同じ産業の他国より伸びたか</h3>
    <p className="fine-note">各産業の実質の付加価値の伸びを、その国全体の実質の伸びで割った比を、2000年＝100にして並べます（名目では比べません。差の大半は物価だからです）。比べる国は、2000年の就業者1人当たりGDPが日本の8割以上の国で、アイルランドは除きます。式と決まりは<a href="/methodology#spec-cause-axis">原因の軸の式と決まり</a>（{data.version}）。</p>
    <div className="world-segment" role="group" aria-label="産業">
      {data.industries.map(i => <button key={i.code} type="button" aria-pressed={i.code === code} onClick={() => setCode(i.code)}>{i.name}</button>)}
    </div>
    <p className="world-lead" role="status">{industryLead(industry)}</p>
    {industry.realNote !== 'OECD の実質' && <p className="fine-note">日本のこの産業は OECD に実質の系列が無く、親の産業の物価で割った仮定の値です。</p>}
    {industry.withoutKorea && <p className="fine-note">支援の強い韓国を除くと {trillion(industry.withoutKorea.trillionYen)}（{industry.withoutKorea.of}か国中{industry.withoutKorea.rank}位）。</p>}
    <div className="world-chart-wrap"><LineReveal key={industry.code} series={industrySeries(industry)} highlightId="JPN" log format={v => v.toFixed(0)} unit="指数（2000年＝100、全体の伸びで割った値）" caption={`${industry.name}の実質付加価値の伸び（全体の伸びで割った値）。日本を赤で強調`} /></div>
    <h4>2023年の比（2000年＝1）</h4>
    <PeerBars industry={industry} />
    <AxisTable data={data} />
    <AccountingTable data={data} />
    <p className="fine-note">額は「その軸に結ぶ観測の差」の上限で、人や組織にはまだ配っていません。置換検定で3位以内なら「参考」、4位以下は「誤差の範囲」です。成長会計の「全要素生産性」は説明できなかった残りで、物価の作り方や資本の測り方の違いも入ります。比べる国が5〜6か国と少なく、期間も2019年までなので、割合は目安です。</p>
  </section>;
}
