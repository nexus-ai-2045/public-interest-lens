import { useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { SiteShell } from './SiteHeader';
import { toneTitle, useTone } from './site-tone';
import { FunnelSteps, RankBars } from './motion';
import { LawCatalog } from './LawCatalog';
import { ProvisionalPanel } from './ProvisionalPanel';
import { collapseObservations, formatYen, lawsCatalogUrl, parseLawsCatalog, type CatalogStep, type LawsCatalog } from './laws-catalog';
import { plainLawName } from './law-name';
import './laws.css';

const TOP = 15;
const funnel: { key: CatalogStep; label: string }[] = [
  { key: 'enacted', label: '成立した法律（1998年以降）' },
  { key: 'evaluated', label: '測る指標が決まった（全体指標を含む）' },
  { key: 'dated', label: '施行日が決まった（公布日での推定を含む）' },
  { key: 'staged', label: '影響の段階が付いた、または全体指標で測った' },
  { key: 'amounted', label: '損失・便益の額が出た（参考を含む）' },
  { key: 'published', label: 'うち確かな額（参考を除く）' },
];

export { formatYen } from './laws-catalog';

export function LawRankingPage() {
  const [data, setData] = useState<LawsCatalog | null>(null);
  const [error, setError] = useState('');
  const [tone] = useTone();
  useEffect(() => { document.title = `法律・政策ランキング｜${toneTitle(tone)}`; }, [tone]);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(lawsCatalogUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        setData(parseLawsCatalog(await response.text()));
      } catch { if (!controller.signal.aborted) setError('一覧のデータを読み込めませんでした。'); }
    })();
    return () => controller.abort();
  }, []);
  const provisional = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mode') === 'provisional';
  const amounted = (data?.laws ?? []).filter(law => law.amount);
  const confirmed = amounted.filter(law => law.step === 'published');
  const loss = confirmed.filter(law => law.side === 'loss').length;
  // 国賊を選んでいれば損失の大きい順、国士なら便益の大きい順。その側が0本なら両方を並べる。
  const toneSide = tone === 'harm' ? 'loss' : 'benefit';
  const sideTop = confirmed.filter(law => law.side === toneSide);
  // 同じ観測（同じ額）は代表の1本だけを棒にする。
  const topList = collapseObservations((sideTop.length ? sideTop : confirmed).slice().sort((a, b) => b.amount!.median - a.amount!.median)).slice(0, TOP);
  return <SiteShell active="/ranking" label="法律・政策ランキング（実データ）" className="law-ranking">
    
    <main id="main">
      <h1>法律と政策ごとの損失と便益</h1>
      <p className="laws-lead">成立した全部の法律を、一次資料（国会の議案情報・e-Gov 法令）と公的統計（OECD 国民経済計算など）で同じルールに通しました。額は比べた国との差から出した推計で、必ず幅と確かさの印を付けています。額が出ない法律も、止まった理由を付けて全部載せています。結果への責任を測るもので、提出者や賛成者の意図や予見を評価するものではありません。</p>
      <nav className="prov-mode" aria-label="ランキングの種類">
        <a href="/ranking" aria-current={!provisional}>国賊ランキング（確定）</a>
        <a href="/ranking?mode=provisional#provisional" aria-current={provisional}>暫定国賊ランキング（他国の実績）</a>
      </nav>
      {provisional && <ProvisionalPanel />}
      {error && <p className="state-banner" role="alert">{error}</p>}
      {!provisional && data && <>
        <section className="laws-stats" aria-label="ひと目で">
          <a href="#list" className="laws-stat"><span>載せている件数</span><strong>{(data.laws.length + data.policies.length).toLocaleString('ja-JP')}件</strong><small>法律{data.laws.length.toLocaleString('ja-JP')}本＋政策{data.policies.length}件</small></a>
          <a href="?side=confirmed#list" className="laws-stat hit"><span>確かな額</span><strong>{confirmed.length}本</strong><small>国賊側{loss}本・国士側{confirmed.length - loss}本（影響の段階まで確認）</small></a>
          <a href="?side=amount#list" className="laws-stat"><span>参考の額</span><strong>{(amounted.length - confirmed.length).toLocaleString('ja-JP')}本</strong><small>産業・経済全体の差など。確かな額と足さない</small></a>
          <a href="?side=none#list" className="laws-stat"><span>額なし（理由つき）</span><strong>{(data.laws.length - amounted.length).toLocaleString('ja-JP')}本</strong><small>測れていないだけで「影響なし」ではない</small></a>
        </section>
        {confirmed.length > 0 && <section aria-label="額の大きい順" id="top-amounts">
          <h3>{sideTop.length ? (toneSide === 'loss' ? '国賊側：損失の大きい順' : '国士側：便益の大きい順') : '額の大きい順'}（確かな額の上位{topList.length}本）</h3>
          <p className="fine-note">赤は国賊側（損失）、緑は国士側（便益）。太い棒が中央値、細い線が幅です。棒を押すと、下の一覧でその法律の詳しい中身が開きます。</p>
          <RankBars caption="額が出た法律の額の大きい順" format={formatYen} items={topList.map(law => ({ id: law.id, label: law.what ? plainLawName(law.what) : law.title, value: law.amount!.median, low: law.amount!.low, high: law.amount!.high, side: law.side ?? 'loss', note: `${law.what ? `名前はAI要約・正式名：${law.title}・` : ''}${law.side === 'loss' ? '国賊側（損失）' : '国士側（便益）'}・${law.field}${law.marks.length ? `・${law.marks.filter(mark => !mark.startsWith('同じ')).join('・') || '印なし'}` : ''}`, href: `#${encodeURIComponent(law.id)}` }))} />
          <p className="fine-note">同じ観測（同じ額の系列・同じ期間）の法律は同じ額を共有するので、棒には代表の1本だけを並べています。足し合わせないでください。ほかの法律と参考の額は下の一覧にあります。上の「国賊／国士」を切り替えると、反対側の上位に変わります。</p>
        </section>}
        <LawCatalog data={data} />
        <details className="law-funnel-box">
          <summary>どこで止まったか（件数の絞り込み）</summary>
          <section aria-label="件数の絞り込み" className="law-funnel">
            <FunnelSteps caption="件数の絞り込み" steps={funnel.map(step => ({ key: step.key, label: step.label, count: data.counts[step.key] }))} />
            {data.strict && <p className="fine-note">参考の額を除くと、測る指標が決まった{data.strict.evaluated.toLocaleString('ja-JP')}本・施行日が原文で確定{data.strict.dated.toLocaleString('ja-JP')}本・影響の段階が付いた{data.strict.staged.toLocaleString('ja-JP')}本です。ほかに、産業や経済全体の差で参考の額を付けた法律が{(data.counts.amounted - data.counts.published).toLocaleString('ja-JP')}本、額が出ていない法律（理由つき）が{(data.counts.enacted - data.counts.amounted).toLocaleString('ja-JP')}本あります。</p>}
            <p className="fine-note">途中で外れた法律は「影響なし」ではありません。資料や統計が足りず、まだ測れていないだけです。棒の長さは桁の違いが見えるよう対数でそろえています。</p>
          </section>
        </details>
        <section className="lower-panel" aria-label="この画面の読み方">
          <p><Info size={16} /> 議員ごとの「この人が失わせた額・生んだ額」は<a href="/members">議員ランキング</a>にあります。計算のしかたは<a href="/methodology">計算方法</a>にあります。</p>
          <p className="fine-note">一覧の元データ：<a href="/distribution/laws.json">laws.json</a>・laws-detail/（開いた時に読む詳細）（入力データの照合値 SHA-256 つき）。</p>
        </section>
      </>}
    </main>
  </SiteShell>;
}
