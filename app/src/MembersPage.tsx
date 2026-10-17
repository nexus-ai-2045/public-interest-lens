import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Info } from 'lucide-react';
import { ProductHeader } from './ProductHeader';
import { formatYen } from './LawRankingPage';
import { RankBars, type RankBarItem } from './motion';
import { ACTION_LABEL, POSITION_LABEL, type PublicMember, type PublicMemberLaw, type PublicMembers } from './members-build';

export const distributionMembersUrl = '/distribution/members.json';
export const correctionUrl = 'https://github.com/nexus-ai-2045/public-interest-lens/issues/new?template=correction.yml';

export function SiteNav({ active }: { active: string }) {
  const links: [string, string][] = [['/history', '長期推移'], ['/policies', '政策と結果'], ['/actors', '人物・団体'], ['/ranking', '法律ランキング'], ['/members', '議員ランキング'], ['/methodology', '計算方法'], ['/demo', '架空デモ']];
  return <nav aria-label="主なページ">{links.map(([href, label]) => <a key={href} href={href} className={href === active ? 'nav-active' : undefined}>{label}</a>)}</nav>;
}

/** 符号つきの額。負は国賊側、正は国士側。 */
export function signedYen(value: number): string {
  if (value === 0) return '0円';
  return `${value < 0 ? '−' : '+'}${formatYen(Math.abs(value))}`;
}

function hostLabel(url: string): string {
  const host = new URL(url).hostname;
  if (host === 'kokkai.ndl.go.jp') return '国会会議録';
  if (host === 'www.sangiin.go.jp') return '参議院の投票結果';
  if (host === 'www.shugiin.go.jp') return '衆議院の議案情報';
  return host;
}

export function readMembers(text: string): PublicMembers {
  const data = JSON.parse(text) as PublicMembers;
  if (data.schema !== 'public-members/v1' || !Array.isArray(data.members) || !Array.isArray(data.laws)) throw new Error('議員データの形式が違います');
  return data;
}

function MemberDetail({ member, laws, rate, weights }: { member: PublicMember; laws: Map<string, PublicMemberLaw>; rate: number; weights: PublicMembers['weights'] }) {
  return <div className="member-detail">
    {member.laws.map(entry => {
      const law = laws.get(entry.lawId)!;
      return <section key={entry.lawId} className={`member-law ${entry.side}`} aria-label={law.title}>
        <p className="law-card-side">{entry.side === 'loss' ? '国賊側（損失）' : '国士側（便益）'}・{law.id}</p>
        <h5>{law.title}</h5>
        <p className="member-law-share"><strong>{formatYen(entry.share.median)}</strong><span>幅 {formatYen(entry.share.low)}〜{formatYen(entry.share.high)}</span></p>
        <p className="member-formula">法律の額 {formatYen(law.amount.median)} × 帰属率 {rate} × 重み {entry.weight}（{ACTION_LABEL[entry.action]} {weights.action[entry.action]} × 立場「{POSITION_LABEL[entry.position]}」 {weights.position[entry.position]}） ÷ 関与者{law.persons}人の重みの合計 {law.totalWeight} ＝ {formatYen(entry.share.median)}</p>
        <p className="confidence-label">確かさの印：{law.confidence}</p>
        <ul className="member-evidence">{entry.evidence.map(ev => <li key={ev.url + ev.action}>
          <span>{ev.date}・{ev.house}・{ev.actionLabel}{ev.title && ev.action !== 'vote' ? `（${ev.title}）` : ''}</span>
          <a href={ev.url} target="_blank" rel="noopener noreferrer">{hostLabel(ev.url)} <ArrowUpRight size={13} /></a>
        </li>)}
          <li><span>法律の審議経過</span><a href={law.source} target="_blank" rel="noopener noreferrer">衆議院の議案情報 <ArrowUpRight size={13} /></a></li>
        </ul>
      </section>;
    })}
    <dl className="policy-metrics member-sensitivity">
      <div><dt>帰属率 0.3 なら</dt><dd>{signedYen(member.sensitivity.rate03Net)}</dd></div>
      <div><dt>帰属率 0.7 なら</dt><dd>{signedYen(member.sensitivity.rate07Net)}</dd></div>
      <div><dt>行動重視の順位</dt><dd>{member.sensitivity.actionOnlyRank}位</dd></div>
      <div><dt>立場重視の順位</dt><dd>{member.sensitivity.positionOnlyRank}位</dd></div>
    </dl>
    {member.sensitivity.flagged && <p className="fine-note">重みの付け方を変えると順位が{member.sensitivity.maxMove}位動きます。順位は重みの決め方に左右されます。</p>}
    {member.overlappingGroups.length > 0 && <p className="fine-note">同じ観測グループ（{member.overlappingGroups.join('・')}）の法律を複数足しています。同じ統計の動きを別々の法律で数えているため、合計は重なりを含み、大きめに出ます。</p>}
    <p className="fine-note"><a href={`${correctionUrl}&title=${encodeURIComponent(`[訂正] ${member.name}`)}`} target="_blank" rel="noopener noreferrer">この人の記録の訂正・反論を送る（GitHub）</a></p>
  </div>;
}

/** 上位の横棒。値は純額の大きさ、幅は小さい方から並べ直す。 */
export function topBars(members: PublicMember[], side: 'loss' | 'benefit', count = 10): RankBarItem[] {
  const picked = side === 'loss' ? members.filter(m => m.net.median < 0).slice(0, count) : members.filter(m => m.net.median > 0).reverse().slice(0, count);
  return picked.map(m => {
    const ends = [Math.abs(m.net.low), Math.abs(m.net.high)].sort((a, b) => a - b);
    const crosses = m.net.low < 0 && m.net.high > 0;
    return { id: m.name, label: m.name, value: Math.abs(m.net.median), low: crosses ? 0 : ends[0], high: ends[1], side, note: `${m.rank}位・${m.laws.length}本の法律から`, href: `/members?name=${encodeURIComponent(m.name)}` };
  });
}

export function MembersPage() {
  const [data, setData] = useState<PublicMembers | null>(null);
  const [error, setError] = useState('');
  const [side, setSide] = useState<'all' | 'loss' | 'benefit'>('all');
  const [query, setQuery] = useState(() => new URLSearchParams(window.location.search).get('name') ?? '');
  useEffect(() => { document.title = '議員ランキング｜国賊／国士ランキング'; }, []);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionMembersUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        setData(readMembers(await response.text()));
      } catch { if (!controller.signal.aborted) setError('議員のデータを読み込めませんでした。'); }
    })();
    return () => controller.abort();
  }, []);
  const laws = useMemo(() => new Map((data?.laws ?? []).map(l => [l.id, l])), [data]);
  const shown = useMemo(() => {
    const all = data?.members ?? [];
    const bySide = side === 'loss' ? all.filter(m => m.net.median < 0) : side === 'benefit' ? [...all].filter(m => m.net.median > 0).reverse() : all;
    const q = query.trim();
    return q ? bySide.filter(m => m.name.includes(q)) : bySide;
  }, [data, side, query]);
  return <div className="app-shell research-page law-ranking members-page" data-theme="light">
    <ProductHeader title="議員ランキング" label="実データ・実名" brandHref="/members"><SiteNav active="/members" /></ProductHeader>
    <main>
      <h2>法律の損失と便益を、関わった議員に配る</h2>
      <p>額が出た法律の損失（国賊側）と便益（国士側）を、国会の記録で確認できた行動（提出、修正、委員長、法案を支持する質疑、参議院本会議の賛成）に、決めた重みで機械的に配った<strong>推計上の配分額</strong>です。「この人が失わせた額」ではなく、結果への関与を測る指標です。すべての行動に一次資料（国会会議録・参議院の投票結果）のリンクを付けています。計算のしかたは<a href="/methodology">計算方法</a>にあります。</p>
      <p className="fine-note">記録や判定に誤りがあれば、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">訂正・反論の窓口（GitHub の Issue）</a>から公開資料を添えて知らせてください。本人・関係者からの反論も同じ窓口で受け付け、確認できたものは記録と額に反映します。</p>
      {error && <p className="state-banner" role="alert">{error}</p>}
      {data && <>
        <section aria-label="元になった法律" className="law-funnel">
          <p className="law-funnel-lead">{data.laws.length}本の法律、{data.counts.members}人（国賊側{data.counts.loss}人・国士側{data.counts.benefit}人）。数えた行動{data.counts.involvements.toLocaleString('ja-JP')}件、外した行動{data.counts.excluded}件。</p>
          <ul className="members-laws">{data.laws.map(law => <li key={law.id} className={law.side}>
            <span>{law.side === 'loss' ? '国賊側' : '国士側'}・{law.id}</span>
            <strong>{law.title}</strong>
            <small>額 {formatYen(law.amount.median)}（幅 {formatYen(law.amount.low)}〜{formatYen(law.amount.high)}）・{law.persons}人に配分・確かさの印：{law.confidence}</small>
          </li>)}</ul>
          <p className="fine-note">確かさの印が「コロナ期と重なる」「未測定」の法律は、法律ランキングでは額を公開判定にしていないものです。ここでは印を付けたまま配分に含めています。参考扱いの額（段階1・貸出残高）は配分していません。額が出た法律が増えると、このページも同じ計算で更新されます。</p>
        </section>
        <section aria-label="上位の議員" className="members-top">
          <h3>国賊側の上位10人</h3>
          <RankBars caption="国賊側の純額の大きい順" format={formatYen} items={topBars(data.members, 'loss')} />
          <h3>国士側の上位10人</h3>
          <RankBars caption="国士側の純額の大きい順" format={formatYen} items={topBars(data.members, 'benefit')} />
        </section>
        <section aria-label="議員の一覧">
          <h3>全員の一覧</h3>
          <div className="members-controls">
            <div role="group" aria-label="側で絞る">
              {([['all', '全員（国賊側が上）'], ['loss', '国賊側'], ['benefit', '国士側']] as const).map(([key, label]) => <button key={key} type="button" aria-pressed={side === key} onClick={() => setSide(key)}>{label}</button>)}
            </div>
            <label>名前で探す <input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
          </div>
          <p className="fine-note" role="status">{shown.length}人を表示</p>
          <ol className="members-list">{shown.map(member => <li key={member.name} className={`member-card ${member.net.median < 0 ? 'loss' : 'benefit'}`}>
            <details open={shown.length === 1}>
              <summary>
                <span className="member-rank">{member.rank}位</span>
                <span className="member-name">{member.name}</span>
                <span className="member-net"><strong>{signedYen(member.net.median)}</strong><small>幅 {signedYen(member.net.low)}〜{signedYen(member.net.high)}</small></span>
                <span className="member-from">{member.laws.map(l => laws.get(l.lawId)!.id).join('・')}</span>
              </summary>
              <MemberDetail member={member} laws={laws} rate={data.rate} weights={data.weights} />
            </details>
          </li>)}</ol>
        </section>
        <section className="lower-panel" aria-label="この画面の読み方">
          <p><Info size={16} /> 点数は 純額 ＝ 国士側の配分（貢献）− 国賊側の配分（損失）です。マイナスが国賊側、プラスが国士側。順位は純額の小さい順（国賊側が上）です。幅は比較国の伸びの四分位から来ています。</p>
          <p className="fine-note">結果への責任を測るもので、提出者や賛成者の意図や予見を評価するものではありません。行動のない人（反対した人、記録が無い人）は配分の対象外で、0点とは別です。ルール：{data.rules.join('・')}。</p>
        </section>
      </>}
    </main>
  </div>;
}

export function MethodologyPage() {
  useEffect(() => { document.title = '計算方法｜国賊／国士ランキング'; }, []);
  return <div className="app-shell research-page law-ranking" data-theme="light">
    <ProductHeader title="計算方法" label="公開している手順" brandHref="/methodology"><SiteNav active="/methodology" /></ProductHeader>
    <main className="methodology">
      <h2>どう計算しているか</h2>
      <p>判断に使うのは一次資料（国会会議録、衆議院・参議院の議案情報と投票結果、e-Gov 法令）と公的統計（OECD 国民経済計算など）だけです。人の印象や報道の評価は点数に入れません。手順はすべてこのリポジトリのコードとして公開しています。</p>
      <h3>1. 法律ごとの額</h3>
      <ol>
        <li>1998年以降に成立した法律から、経済の指標で影響を追える法律を選ぶ（評価の対象）。</li>
        <li>施行日を法令の原文で確かめ、施行の前後で日本の指標（宿泊者数、通信業の付加価値など）を比較国と比べる。</li>
        <li>比較国の伸びの中央値と、施行前の日本の伸びとの差を織り込んだ「施行しなかった場合」との差を、損失（国賊側）または便益（国士側）の額とする。幅は比較国の伸びの第1・第3四分位。</li>
        <li>確かさの印を付ける。新型コロナの時期と窓が重なるもの、便益を減らしうる項目が未測定のもの、未測定の便益を0とした下限など。</li>
      </ol>
      <h3>2. 議員への配分</h3>
      <p className="member-formula">個人の配分 ＝ 法律の額 × 帰属率 × (行動の重み × 立場の重み) ÷ 関与者全員の重みの合計</p>
      <table>
        <thead><tr><th>行動</th><th>重み</th></tr></thead>
        <tbody>
          <tr><td>提出・決定（大臣として閣議決定に関わった、提出者・発議者）</td><td>5</td></tr>
          <tr><td>修正案の提出</td><td>4</td></tr>
          <tr><td>委員長として採決を主宰</td><td>3</td></tr>
          <tr><td>法案を支持する質疑（2系統の機械判定がともに「支持」のものだけ）</td><td>2</td></tr>
          <tr><td>参議院本会議で賛成</td><td>1</td></tr>
        </tbody>
      </table>
      <table>
        <thead><tr><th>当時の立場</th><th>重み</th></tr></thead>
        <tbody>
          <tr><td>内閣総理大臣</td><td>3</td></tr>
          <tr><td>大臣</td><td>2</td></tr>
          <tr><td>副大臣・大臣政務官・内閣官房副長官・本件の委員会の委員長</td><td>1.5</td></tr>
          <tr><td>その他</td><td>1</td></tr>
        </tbody>
      </table>
      <ul>
        <li>帰属率の基準は 0.5。残りの半分は組織や外部要因として、誰にも配らない。0.3 と 0.7 の結果も各議員の欄に出す。</li>
        <li>1人が同じ法律で複数の行動をしたときは、重みが最大の組を1回だけ数える。</li>
        <li>証拠の URL が無い行動は数えない。反対票、中立・反対の質疑、2系統の判定が食い違った質疑は数えない。</li>
        <li>立場は行動の重みを補正するだけで、立場だけでは配分しない。党の役職は資料が揃っていないため、全員「その他」。</li>
        <li>円の端数は最大剰余法で配り、法律ごとの配分の合計が帰属額にぴったり一致するようにしている。</li>
        <li>感度：行動重視（立場の重みをすべて1）と立場重視（行動の重みをすべて1）でも順位を出し、5位以上動く人には注意を付ける。</li>
      </ul>
      <h3>3. 点数</h3>
      <p>点数（純額）＝ 国士側の法律からの配分の合計 − 国賊側の法律からの配分の合計。マイナスが国賊側、プラスが国士側。同じ統計（観測グループ）の動きを複数の法律で数えている人は、合計が重なりを含むため、その旨を表示する。</p>
      <h3>4. 訂正と反論</h3>
      <p>誤り・反証・本人や関係者からの反論は、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">GitHub の Issue（訂正・異議の申し立て）</a>で受け付けます。公開資料の出典を添えてください。確認できたものは記録を直し、同じ計算で額と順位を出し直します。受付後の流れは<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/corrections.md" target="_blank" rel="noopener noreferrer">訂正の手順</a>にあります。</p>
      <h3>5. 元のデータとコード</h3>
      <ul>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/involvements.csv" target="_blank" rel="noopener noreferrer">関与の一覧（行動・日付・一次資料の URL、外した行動と理由を含む）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/loss-rule.ts" target="_blank" rel="noopener noreferrer">損失の計算と配分の重み（loss-rule.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/allocation-batch.ts" target="_blank" rel="noopener noreferrer">配分の集計（allocation-batch.ts）</a></li>
        <li><a href="/distribution/members.json">議員ページの配布データ（members.json）</a></li>
      </ul>
    </main>
  </div>;
}
