import { useEffect, useMemo, useState } from 'react';
import { ProductHeader } from './ProductHeader';
import { FunnelSteps, LineReveal, RankBars, ShareButton, type LineSeries, type RankBarItem } from './motion';

/** 見せ方の試作。数字も名前もすべて架空。実データの画面は同じ部品で作る。 */
const people: (RankBarItem & { benefitValue: number })[] = [
  { id: 'a', label: '架空議員 A', value: 8.2e12, low: 5.1e12, high: 9.9e12, benefitValue: 0.4e12, side: 'loss', note: '架空・衆議院' },
  { id: 'b', label: '架空議員 B', value: 5.4e12, low: 3.0e12, high: 7.7e12, benefitValue: 2.1e12, side: 'loss', note: '架空・参議院' },
  { id: 'c', label: '架空議員 C', value: 3.1e12, low: 1.2e12, high: 4.0e12, benefitValue: 6.8e12, side: 'loss', note: '架空・衆議院' },
  { id: 'd', label: '架空議員 D', value: 1.9e12, low: 0.8e12, high: 2.6e12, benefitValue: 9.4e12, side: 'loss', note: '架空・衆議院' },
  { id: 'e', label: '架空議員 E', value: 0.7e12, low: 0.2e12, high: 1.1e12, benefitValue: 4.3e12, side: 'loss', note: '架空・参議院' },
];
const fakeSeries = (id: string, label: string, growth: number, wobble: number): LineSeries => ({ id, label, points: Array.from({ length: 36 }, (_, i) => ({ year: 1990 + i, value: 100 * Math.pow(1 + growth, i) * (1 + Math.sin(i / 3 + wobble) * 0.02) })) });
const series = [fakeSeries('jp', '日本（架空）', 0.006, 0), fakeSeries('us', 'A国（架空）', 0.022, 1), fakeSeries('kr', 'B国（架空）', 0.041, 2), fakeSeries('de', 'C国（架空）', 0.013, 3), fakeSeries('gb', 'D国（架空）', 0.016, 4)];
const yen = (value: number) => `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 1 }).format(value / 1e12)}兆円`;

export function MotionGalleryPage() {
  useEffect(() => { document.title = '見せ方の試作｜架空データ'; }, []);
  const [side, setSide] = useState<'loss' | 'benefit'>('loss');
  const [indexed, setIndexed] = useState(true);
  const items = useMemo(() => people.map(item => side === 'loss' ? item : { ...item, value: item.benefitValue, low: item.benefitValue * 0.6, high: item.benefitValue * 1.25, side: 'benefit' as const }).sort((a, b) => b.value - a.value), [side]);
  return <div className="app-shell research-page motion-gallery" data-theme={side === 'loss' ? 'dark' : 'light'}>
    <ProductHeader title="見せ方の試作" label="架空データ" brandHref="/demo/motion"><nav aria-label="主なページ"><a href="/ranking">法律ランキング</a><a href="/history">長期推移</a><a href="/demo">架空デモ</a></nav></ProductHeader>
    <main>
      <h2>同じ部品で、法律・議員・各国比較を見せる</h2>
      <p>ここの名前と数字はすべて架空です。国賊（損失）は暗く沈み、国士（便益）は明るく浮きます。動きは一度だけで、端末の「視差効果を減らす」設定では止まります。</p>
      <section aria-label="議員ランキングの試作">
        <h3>議員ランキング（並べ替えると行が滑って入れ替わる）</h3>
        <div className="gallery-controls"><button aria-pressed={side === 'loss'} onClick={() => setSide('loss')}>国賊（損失）</button><button aria-pressed={side === 'benefit'} onClick={() => setSide('benefit')}>国士（便益）</button></div>
        <RankBars caption="架空の議員ランキング" items={items} format={yen} />
        <p className="fine-note">太い棒は中央値、細い線は幅です。順位の差が幅の中なら、差は確かではありません。</p>
        <ShareButton title="見せ方の試作" text="架空データの議員ランキング" url={`${window.location.origin}/demo/motion`} />
      </section>
      <section aria-label="各国比較の試作">
        <h3>各国の伸び（日本だけ色、名前は線の終わり）</h3>
        <div className="gallery-controls"><button aria-pressed={indexed} onClick={() => setIndexed(true)}>1990年＝100</button><button aria-pressed={!indexed} onClick={() => setIndexed(false)}>実額</button></div>
        <LineReveal key={String(indexed)} caption="架空の各国の伸び" series={series} highlightId="jp" indexed={indexed} baseYear={1990} format={value => value.toFixed(0)} />
      </section>
      <section aria-label="件数の絞り込みの試作">
        <h3>件数の絞り込み（最後の1本が光る）</h3>
        <FunnelSteps caption="架空の件数の絞り込み" steps={[{ key: 'a', label: '調べた法律', count: 3415 }, { key: 'b', label: '評価の対象', count: 349 }, { key: 'c', label: '段階が付いた', count: 63 }, { key: 'd', label: '額が出た', count: 6 }, { key: 'e', label: '公開中', count: 1 }]} />
      </section>
    </main>
  </div>;
}
