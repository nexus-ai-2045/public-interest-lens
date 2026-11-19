import { lazy, Suspense, useEffect, useState } from 'react';
import { SiteShell } from './SiteHeader';
import { toneTitle, useTone } from './site-tone';
import { ExposureRankingPanel } from './ExposureRankingPanel';
import type { PanelExposureRanking } from './exposure-ranking';
import { parsePublicExposureRanking, panelExposureRanking } from './public-distribution';
import { SCORING_CONSTANTS } from './scoring-constants';
const MethodFormulas = lazy(() => import('./MethodFormulas'));
const BacktestPanel = lazy(() => import('./BacktestPanel'));
const LedgerPanel = lazy(() => import('./LedgerPanel'));

export const correctionUrl = 'https://github.com/nexus-ai-2045/public-interest-lens/issues/new?template=correction.yml';
/** 曝露ランキングの公開用データ。表示を解くまでは公開ディレクトリに置かない（scripts/generate_artifacts.py）。 */
export const distributionExposureUrl = '/distribution/exposure-ranking.json';

/** 議員・党の順位と点を本番で出さない（ねく 11-01）。曝露ランキングの表示を解くのは、設計決定0008（実名公開の線引き）のねくの確認の後。 */
export const MEMBER_RANKING_HIDDEN = true;

export function MembersPage() {
  const [tone] = useTone();
  // トップ（/）から来たら、URL を議員ページのものに揃える。
  if (window.location.pathname === '/') window.history.replaceState(window.history.state, '', `/members${window.location.search}${window.location.hash}`);
  useEffect(() => { document.title = `議員・実名｜${toneTitle(tone)}`; }, [tone]);
  const [ranking, setRanking] = useState<PanelExposureRanking | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (MEMBER_RANKING_HIDDEN) return;
    const controller = new AbortController();
    void fetch(distributionExposureUrl, { signal: controller.signal, cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.text(); })
      .then(text => setRanking(panelExposureRanking(parsePublicExposureRanking(text))))
      .catch(e => { if (!controller.signal.aborted) setError(`議員のデータを読み込めませんでした（${e instanceof Error ? e.message : e}）`); });
    return () => controller.abort();
  }, []);
  return <SiteShell active="/members" label="議員・実名・実データ" className="law-ranking members-page">
    <main id="main">
      <h1>議員が関わった法律と、その産業の伸び損ね（記述）</h1>
      {MEMBER_RANKING_HIDDEN && <p className="empty-state" role="note">議員・政党の順位と点は、計算方法の見直し中のため、いったん非表示にしています。法律ごとの損失と便益は<a href="/ranking">法律ランキング</a>で見られます。</p>}
      <p className="fine-note">記録や判定に誤りがあれば、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">訂正・反論の窓口（GitHub の Issue）</a>から公開資料を添えて知らせてください。</p>
      {!MEMBER_RANKING_HIDDEN && error && <p className="state-banner" role="alert">{error}</p>}
      {!MEMBER_RANKING_HIDDEN && ranking && <ExposureRankingPanel ranking={ranking} />}
    </main>
  </SiteShell>;
}

export function MethodologyPage() {
  useEffect(() => { document.title = '計算方法｜国賊／国士ランキング'; }, []);
  return <SiteShell active="/methodology" label="計算方法" className="law-ranking">
    <main id="main" className="methodology">
      <h1>どう計算しているか</h1>
      <p>判断に使うのは一次資料（国会会議録、衆議院・参議院の議案情報と投票結果、e-Gov 法令）と公的統計（OECD 国民経済計算など）だけです。人の印象や報道の評価は点数に入れません。手順はすべてこのリポジトリのコードとして公開しています。</p>
      <h3>1. 法律ごとの額</h3>
      <ol>
        <li>1998年以降に成立した法律から、経済の指標で影響を追える法律を選ぶ（評価の対象）。</li>
        <li>施行日を法令の原文で確かめ、施行の前後で日本の指標（宿泊者数、通信業の付加価値など）を比較国と比べる。</li>
        <li>比較国の伸びの中央値と、施行前の日本の伸びとの差を織り込んだ「施行しなかった場合」との差を、損失（国賊側）または便益（国士側）の額とする。幅は比較国の伸びの第1・第3四分位。全体指標（産業や経済全体の差）だけで測った参考の額は、損失か便益かが差の符号でしか決まらず、法律の効果の向きの証拠が無いので「向き未確定」とし、国賊側・国士側に分けない。</li>
        <li>確かさの印を付ける。新型コロナの時期と窓が重なるもの、便益を減らしうる項目が未測定のもの、未測定の便益を0とした下限など。</li>
      </ol>
      <h3>2. 議員の見せ方（点数設計 v2.1、設計決定0027・0028）</h3>
      <p>識別できる単位は「産業×期間の群」までです（単独で識別できる法律は 1,982 本中 2 本）。そこで議員には、次の2つを分けて出します。足し合わせません。</p>
      <ol>
        <li><strong>因果の点</strong>：外部の証拠（他国の実測・官庁の見込みなど）で法律単位の額が取れ、確かさが「中」以上の法律だけを、役割ごとの固定比率（発議 0.4・賛成 0.2・反対 −0.2・閣議決定 0.2。取り決め）で人に配ります。関与した法律が5本以上で、上位3本の占有率が50%以下の人だけに点を出します。いまは該当する法律が0本なので、点のある議員は0人です。</li>
        <li><strong>曝露ランキング（記述）</strong>：関与した法律が属する産業×年の群が、OECD の同じ産業・同じ年の中央値よりどれだけ伸び損ねたかを、同じ固定比率で配った額です。その人や法律が原因だという意味ではありません。順位は1位・2位ではなく、幅が重なる人を同じ階層にまとめ、階層の中は名前（人物ID）の文字の順に出します（いまは全員の幅が重なり階層は1つです）。「国賊」「国士」の札は付けません。関与した法律が{SCORING_CONSTANTS.minContributingLaws}本未満の人、上位3本の法律で額の{SCORING_CONSTANTS.topThreeShareCap * 100}%を超える人、関与の記録が無い人は、額を出さず理由を出します。</li>
      </ol>
      <p>閣法は首相1人に付けず、提出した回次の会期を通して在任した閣僚の全員に付けます（総理大臣が会期中に替わる回次は、交代より前に付託された閣法だけ）。賛成・反対の枠は院で半分ずつに分け、衆議院は会派単位の賛否、参議院は押しボタン投票の個人票に配ります。記録の無い分は未配分として残し、別の人へ寄せません。このため個人の欄は参議院議員と閣僚が中心になり、衆議院議員の賛否は会派の欄に入ります（階層に入る 796 人のうち参議院 592・衆議院 71・院の欄が空の閣僚経験者など 133）。</p>
      <p>以前の「成立への寄与」（投票のゲームで1票の効き方を測る）による配分と、全議員へ参考の額を配る欄は、v2.1 でやめました（計算方法の版 method-spec-v3.0）。</p>
      <h3>3. 訂正と反論</h3>
      <p>法律の一覧（法律ランキング）では、同じ観測（同じ額の系列・同じ期間）を共有する法律は、確かさの高い順（同じなら id の昇順）で先頭の1本を代表の行にして並べ、残りは「ほか N 本が同じ観測」から題名で見られます。額は観測ごとに1つなので、足し合わせません。また、額が窓の開始前最後の年の日本の全産業の名目付加価値（OECD 国民経済計算 表6）1年分を超える法律には「桁外れ」の印と倍率を付けます。額は変えず、順位からも外さず、参考にとどめる印です。</p>
      <p>誤り・反証・本人や関係者からの反論は、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">GitHub の Issue（訂正・異議の申し立て）</a>で受け付けます。公開資料の出典を添えてください。確認できたものは記録を直し、同じ計算で額と順位を出し直します。受付後の流れは<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/corrections.md" target="_blank" rel="noopener noreferrer">訂正の手順</a>にあります。</p>
      <h3>4. 元のデータとコード</h3>
      <ul>
        <li><a href="/distribution/ranking.json">法律ランキングの配布データ（ranking.json）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/involvements.csv" target="_blank" rel="noopener noreferrer">関与の一覧（行動・日付・一次資料の URL、外した行動と理由を含む）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/loss-rule.ts" target="_blank" rel="noopener noreferrer">損失の計算（loss-rule.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/exposure-ranking.ts" target="_blank" rel="noopener noreferrer">曝露ランキングの集計（exposure-ranking.ts）</a>・<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/scoring-constants.ts" target="_blank" rel="noopener noreferrer">固定の定数（scoring-constants.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/votes.csv" target="_blank" rel="noopener noreferrer">参議院本会議の票数（votes.csv）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/計算式.md" target="_blank" rel="noopener noreferrer">計算式（docs/計算式.md）</a>・<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/データベース.md" target="_blank" rel="noopener noreferrer">データベース（docs/データベース.md）</a>・<a href="/numbers">数字で見る</a></li>
      </ul>
      <Suspense fallback={<p className="empty-state">式を読み込み中…</p>}><MethodFormulas /></Suspense>
      <Suspense fallback={<p className="empty-state">精度の表を読み込み中…</p>}><BacktestPanel /></Suspense>
      <Suspense fallback={<p className="empty-state">評価台帳を読み込み中…</p>}><LedgerPanel /></Suspense>
    </main>
  </SiteShell>;
}
