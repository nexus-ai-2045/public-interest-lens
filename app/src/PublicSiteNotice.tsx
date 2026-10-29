import { useEffect } from 'react';
import { SiteShell } from './SiteHeader';

export function PublicSiteNotice() {
  return <footer className="public-site-notice" aria-label="この試作版と訂正窓口">
    <h2>このサイトは試作版です</h2>
    <p>法律ランキングは実データの推計額です。議員ランキングは、その法律の額を、提出・賛成・反対の記録（一次資料つき）から人に配った値です。政策事例（金融再生プログラム1件）に限り、判定ルールで算出した人物ごとの点数と保留を載せています。どれも資料に記された行動と観測された指標の変化の関係であり、人格評価や意図・予見の評価、責任割合の認定ではありません。</p>
    <h3>訂正・お問い合わせ</h3>
    <p>開発・資料の訂正窓口：nexus-ai-2045 / public-interest-lens</p>
    <p><a href="https://github.com/nexus-ai-2045/public-interest-lens/issues/new?template=correction.yml" target="_blank" rel="noopener noreferrer">GitHubで訂正・問い合わせを送る</a>（GitHubアカウントが必要です）</p>
    <p>該当ページのURL、該当箇所、訂正内容と出典をお知らせください。投稿は公開されるため、個人情報や非公開資料は記載しないでください。</p>
  </footer>;
}

/**
 * 存在しないパス。静的ホスティングなので HTTP は 200 のまま返るため、画面で「見つかりません」を示し、
 * 検索に載らないよう noindex を足す。閉じた画面（/demo など）へはリンクせず、公開している主要ページへ案内する。
 */
export function PublicNotFoundPage() {
  useEffect(() => {
    const previous = document.title;
    document.title = 'ページが見つかりません｜国賊ランキング';
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex';
    document.head.appendChild(meta);
    return () => { document.title = previous; meta.remove(); };
  }, []);
  return <SiteShell active="" label="ページが見つかりません">
    <main id="main"><h1>ページが見つかりません</h1>
      <p>指定されたアドレスのページはありません。アドレスの打ち間違いか、移動・終了したページの可能性があります。</p>
      <p><a href="/members">議員ランキングを見る</a> · <a href="/ranking">法律ランキングを見る</a> · <a href="/votes">政党・議員の賛否を見る</a> · <a href="/numbers">数字で見る</a> · <a href="/world">世界のGDPと比べる</a> · <a href="/methodology">計算方法を読む</a></p>
    </main>
  </SiteShell>;
}

export function PublicUnavailablePage() {
  useEffect(() => { document.title = '公開版に含まれない機能｜試作版'; }, []);
  return <SiteShell active="" label="公開版の案内">
    <main id="main"><h1>この機能は公開版に含まれていません</h1>
      <p>端末内の非公開評価版や収集記録を読む機能です。このサイトからは利用できません。</p>
      <p><a href="/members">議員ランキングを見る</a> · <a href="/ranking">法律ランキングを見る</a> · <a href="/world">世界のGDPと比べる</a> · <a href="/history">長期推移を読む</a> · <a href="/policies">政策事例と判定結果を読む</a></p>
    </main>
  </SiteShell>;
}
