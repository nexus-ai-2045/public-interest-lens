import { useEffect, useState } from 'react';
import { ArrowUpRight, Info } from 'lucide-react';
import { ProductHeader } from './ProductHeader';
import { CountUp, FunnelSteps, RankBars, Reveal, ShareButton } from './motion';
import { distributionRankingUrl, parsePublicRanking, type PublicRanking, type PublicRankingHeld } from './public-distribution';

const funnel: { key: keyof PublicRanking['counts']; label: string }[] = [
  { key: 'enacted', label: '成立した法律（1998年以降）' },
  { key: 'evaluated', label: '評価の対象' },
  { key: 'dated', label: '施行日が原文で確定' },
  { key: 'staged', label: '影響の段階が付いた' },
  { key: 'amounted', label: '損失・便益の額が出た' },
  { key: 'publishable', label: '公開できる判定' },
  { key: 'published', label: '公開中' },
];
const reasonTitles: Record<string, string> = {
  APPROVAL: '公開の承認待ち',
  SOURCE: '出典チェックで食い違い（確認中）',
  R1: '参考の行・保留の判定を含む',
  R3: '新型コロナの時期と分けられない',
  R4: '便益を減らしうる項目が未測定',
};

/** 兆円・億円の単位で丸めて読む。幅は必ず一緒に出す。 */
export function formatYen(value: number): string {
  if (value >= 1e12) return `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value / 1e12)}兆円`;
  return `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 0 }).format(value / 1e8)}億円`;
}

export function LawRankingPage() {
  const [data, setData] = useState<PublicRanking | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { document.title = '法律ランキング｜国賊／国士ランキング'; }, []);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionRankingUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        setData(parsePublicRanking(await response.text()));
      } catch { if (!controller.signal.aborted) setError('ランキングのデータを読み込めませんでした。'); }
    })();
    return () => controller.abort();
  }, []);
  const groups = new Map<string, PublicRankingHeld[]>();
  for (const item of data?.held ?? []) groups.set(item.reasonCode, [...(groups.get(item.reasonCode) ?? []), item]);
  return <div className="app-shell research-page law-ranking" data-theme="light">
    <ProductHeader title="法律ランキング" label="実データ" brandHref="/ranking"><nav aria-label="主なページ"><a href="/history">長期推移</a><a href="/world">世界のGDP</a><a href="/policies">政策と結果</a><a href="/actors">人物・団体</a><a href="/ranking" className="nav-active">法律ランキング</a><a href="/members">議員ランキング</a><a href="/methodology">計算方法</a><a href="/demo">架空デモ</a></nav></ProductHeader>
    <main>
      <h2>法律ごとの損失と便益</h2>
      <p>一次資料（国会の議案情報、e-Gov 法令）と公的統計（OECD 国民経済計算など）だけを使い、決めたルールで機械的に出した額です。結果への責任を測るもので、提出者や賛成者の意図や予見を評価するものではありません。額は比較国と比べた推計上の値で、必ず幅を付けて読みます。</p>
      {error && <p className="state-banner" role="alert">{error}</p>}
      {data && <>
        <section aria-label="件数の絞り込み" className="law-funnel">
          <p className="law-funnel-lead"><CountUp value={data.counts.enacted} format={value => `${Math.round(value).toLocaleString('ja-JP')}本`} />のうち、額を公開できたのは<CountUp className="law-funnel-hit" value={data.counts.published} format={value => `${Math.round(value)}本`} />です。</p>
          <FunnelSteps caption="件数の絞り込み" steps={funnel.map(step => ({ key: step.key, label: step.label, count: data.counts[step.key] }))} />
          <p className="fine-note">途中で外れた法律は「影響なし」ではありません。資料や統計が足りず、まだ測れていないだけです。棒の長さは桁の違いが見えるよう対数でそろえています。</p>
        </section>
        {data.laws.length > 0 && <section aria-label="額の大きい順">
          <h3>額の大きい順</h3>
          <RankBars caption="公開している法律の額の大きい順" format={formatYen} items={[...data.laws].sort((a, b) => b.amountMedianYen - a.amountMedianYen).map(law => ({ id: law.id, label: law.title, value: law.amountMedianYen, low: law.amountLowYen, high: law.amountHighYen, side: law.side, note: `${law.side === 'loss' ? '国賊側（損失）' : '国士側（便益）'}・${law.field}${law.lowerBound ? '・下限' : ''}`, href: `#${encodeURIComponent(law.id)}` }))} />
          <p className="fine-note">太い棒は中央値、細い線は幅（比較国の伸びの四分位）です。</p>
        </section>}
        <section aria-label="公開している法律">
          <h3>公開している法律</h3>
          {!data.laws.length && <p className="empty-state" role="status">公開の判定が出た法律は{data.counts.publishable}本ありますが、公開の承認待ちです。承認されるまで額は表示しません。</p>}
          {data.laws.map((law, index) => <Reveal as="article" key={law.id} tone={law.side} delay={index * 60} className={`law-card ${law.side}`}><span id={law.id} className="law-anchor" />
            <p className="law-card-side">{index + 1}. {law.side === 'loss' ? '国賊側（損失）' : '国士側（便益）'}・{law.id}</p>
            <h4>{law.title}</h4>
            <p className="law-amount"><strong>{law.lowerBound ? '少なくとも ' : ''}<CountUp value={law.amountMedianYen} format={formatYen} /></strong><span>幅 {formatYen(law.amountLowYen)}〜{formatYen(law.amountHighYen)}（比較国の伸びの四分位）</span></p>
            <dl className="policy-metrics">
              <div><dt>指標</dt><dd>{law.field}・{law.indicator}</dd></div>
              <div><dt>影響の段階</dt><dd>{law.stage}</dd></div>
              <div><dt>施行日</dt><dd>{law.enforcedOn}</dd></div>
              <div><dt>額の窓</dt><dd>{law.window}</dd></div>
              <div><dt>比較国</dt><dd>{law.comparisonCountries.join('・')}</dd></div>
            </dl>
            {law.lowerBound && <p className="fine-note">未測定の便益を0として数えた下限です。未測定の項目：{law.benefitStatus}</p>}
            <p className="fine-note">同じ観測グループ（{law.group}）の額は足しません。推計上の額で、確定した損害額や効果額ではありません。</p>
            <ul className="law-sources">{law.sources.map(url => <li key={url}><a href={url} target="_blank" rel="noopener noreferrer">{new URL(url).hostname === 'laws.e-gov.go.jp' ? 'e-Gov 法令' : '国会の議案情報'} <ArrowUpRight size={13} /></a></li>)}</ul>
            <ShareButton title={`${law.title}｜法律ランキング`} text={`${law.title}：${law.side === 'loss' ? '損失' : '便益'}の推計 ${formatYen(law.amountMedianYen)}（幅 ${formatYen(law.amountLowYen)}〜${formatYen(law.amountHighYen)}）`} url={`${window.location.origin}/ranking#${encodeURIComponent(law.id)}`} />
          </Reveal>)}
        </section>
        <section aria-label="保留の法律">
          <h3>額を出していない法律（{data.held.length}本）</h3>
          <p>額の計算まで進んだものの、ルールで公開を止めた法律です。理由ごとにまとめています。額は載せません。</p>
          {[...groups].map(([code, items]) => <details key={code} className="law-held">
            <summary>{reasonTitles[code] ?? code}（{items.length}本）</summary>
            <p className="fine-note">{items[0].reason}</p>
            <ul>{items.map(item => <li key={item.id}><span>{item.title}</span><small>{item.id}・{item.side === 'loss' ? '国賊側' : '国士側'}</small></li>)}</ul>
          </details>)}
        </section>
        <section className="lower-panel" aria-label="この画面の読み方">
          <p><Info size={16} /> 議員ごとの「この人が失わせた額・生んだ額」は<a href="/members">議員ランキング</a>にあります。幅つきの推計で、計算のしかたは<a href="/methodology">計算方法</a>にあります。</p>
          <p className="fine-note">ルール：{data.generatedFrom.rules.join('・')}。入力データの照合値（SHA-256）は配布データ ranking.json に記録しています。</p>
        </section>
      </>}
    </main>
  </div>;
}
