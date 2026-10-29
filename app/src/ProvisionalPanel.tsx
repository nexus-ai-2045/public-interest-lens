import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { formatYen } from './laws-catalog';
import { plainLawName } from './law-name';
import { directionLabel, formatGapRange, parseProvisional, provisionalUrl, type Provisional, type ProvisionalCard, type ProvisionalItem } from './provisional';

/** 0を中央にした横軸に、幅（最小〜最大）だけを描く。点（中央値）は描かない。 */
function RangeBar({ low, high, max }: { low: number; high: number; max: number }) {
  const left = 50 + (Math.min(low, high) / max) * 50;
  const width = (Math.abs(high - low) / max) * 50;
  return <span className="prov-range" role="img" aria-label={`${formatYen(low)}から${formatYen(high)}`}>
    <span className="prov-zero" />
    <span className="prov-span" style={{ left: `${left}%`, width: `${Math.max(width, 0.8)}%` }} />
  </span>;
}

function CardView({ card }: { card: ProvisionalCard }) {
  return <li className="prov-card" id={card.id}>
    <h4>{card.countryName}：{card.title}</h4>
    <p className="fine-note">{card.purpose}／手段：{card.instrument}／対象：{card.targetIndustry}</p>
    {card.status === 'measured' && card.effect
      ? <p><strong>比較国との差の差：{formatGapRange(card.effect)}</strong>（開始後{card.window.post[1] - card.window.post[0] + 1}年の終わりの水準の差。比較国{card.comparatorsUsed?.length}か国ごとの最小〜最大。点の値は出しません）{card.spansZero && <span className="prov-flag">幅が0をまたぐ</span>}</p>
      : <p>測れていません：{card.reason}</p>}
    <p className="fine-note">測った量：{card.measure}。窓：開始前{card.window.pre[0]}〜{card.window.pre[1]}年／開始後{card.window.post[0]}〜{card.window.post[1]}年。{card.crisisYears.length > 0 && <>窓に危機の年（{card.crisisYears.join('・')}）が入っています。</>}確かさの元：{card.sourceCertainty}。</p>
    <p className={`fine-note prov-apply ${card.applicableToJapan ? 'yes' : 'no'}`}>{card.applicableToJapan ? '日本の法律に当てる対象' : '日本の法律には当てない'}：{card.applicabilityNote}</p>
  </li>;
}

function ItemRow({ item, max }: { item: ProvisionalItem; max: number }) {
  return <li className="prov-row">
    <div><strong>{item.what ? plainLawName(item.what) : item.title}</strong><small>{item.id}・{item.field}・{directionLabel(item.direction)}</small></div>
    <RangeBar low={item.amount.low} high={item.amount.high} max={max} />
    <div className="fine-note">{formatYen(item.amount.low)}〜{formatYen(item.amount.high)}（{item.size.label}の{item.size.year}年の規模×他国の幅）</div>
  </li>;
}

export function ProvisionalPanel() {
  const [data, setData] = useState<Provisional | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(provisionalUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        setData(parseProvisional(await response.text()));
      } catch { if (!controller.signal.aborted) setError('暫定評価のデータを読み込めませんでした。'); }
    })();
    return () => controller.abort();
  }, []);
  if (error) return <p className="state-banner" role="alert">{error}</p>;
  if (!data) return <p className="fine-note">読み込み中…</p>;
  const max = Math.max(1, ...data.items.flatMap(item => [Math.abs(item.amount.low), Math.abs(item.amount.high)]));
  return <section aria-label="暫定国賊ランキング" id="provisional">
    <h3>暫定国賊ランキング（他国の実績を当てた幅）</h3>
    <p className="laws-lead">直近{data.recentFromYear}年以降に成立した法律は、結果が出るまでの観測が足りません。そこで、同じ種類の政策を先に実施した他国の産業の伸びの差の差を、幅のまま日本のその産業の規模に当てます。確かさは「低」固定で、確定の順位には入れません。点の値は出さず、成功した国だけでなく失敗した国も同じ表に入れています。</p>
    <section className="laws-stats" aria-label="暫定のひと目">
      <div className="laws-stat"><span>直近の法律</span><strong>{data.counts.recent.toLocaleString('ja-JP')}本</strong><small>{data.recentFromYear}年以降に成立</small></div>
      <div className="laws-stat hit"><span>暫定の幅を付けた</span><strong>{data.counts.provisional}本</strong><small>他国の同種の政策がある法律だけ</small></div>
      <div className="laws-stat"><span>未測定</span><strong>{data.counts.unmeasured.toLocaleString('ja-JP')}本</strong><small>同種の他国の実績がまだ無い。「影響なし」ではない</small></div>
    </section>
    {data.items.length > 0
      ? <ol className="prov-list">{data.items.map(item => <ItemRow key={item.id} item={item} max={max} />)}</ol>
      : <p className="state-banner">いまの政策カードに、目的・対象産業・手段・開始時期の水準の4つが合う直近の法律はありません。無理に当てていません。カードを増やすと増えます。</p>}
    {data.nearMisses.length > 0 && <details className="prov-near"><summary>近かったが当てなかった法律（{data.nearMisses.length}本）</summary>
      <ul>{data.nearMisses.map(miss => <li key={miss.id + miss.cardId}><strong>{miss.title}</strong>：{miss.reason}</li>)}</ul></details>}
    <h3>政策カード（他国の政策1件ずつの点検）</h3>
    <p className="fine-note"><Info size={14} /> 国や人物ではなく、政策に付けます。追い上げ成長・同時期の別政策・制度の違い・統計の質の限界があります。窓と産業は結果を見る前に固定しました。</p>
    <ul className="prov-cards">{data.cards.map(card => <CardView key={card.id} card={card} />)}</ul>
  </section>;
}
