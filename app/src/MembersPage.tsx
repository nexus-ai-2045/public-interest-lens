import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Info } from 'lucide-react';
import { ProductHeader } from './ProductHeader';
import { formatYen } from './LawRankingPage';
import { RankBars, type RankBarItem } from './motion';
import { distributionActivityUrl, readActivity, type MemberActivity, type MemberActivityEntry } from './member-activity';
import { ROLE_LABEL as CAUSAL_ROLE_LABEL, type MemberEvidence, type MemberLaw, type PublicMember, type PublicMemberLaw, type PublicMembers } from './members-build';
import type { CausalRole } from './causal-allocation';

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
  if (data.schema !== 'public-members/v2' || !Array.isArray(data.members) || !Array.isArray(data.laws)) throw new Error('議員データの形式が違います');
  return data;
}

const ROLE_LABEL: Record<string, string> = { 役職_内閣: '内閣', 役職_国会: '国会', 役職_党: '党', 選挙: '選挙', 提出法案: '提出法案', 政治資金: '政治資金', 公式発言: '公式発言', 資産公開: '資産公開', その他公的記録: 'その他' };

export function ActivityPanel({ entry, fetchedAt }: { entry: MemberActivityEntry | undefined; fetchedAt: string }) {
  if (!entry?.diet && !entry?.roles?.length) return <p className="fine-note">国会での活動の記録はまだ集めていません。</p>;
  const d = entry.diet;
  return <section className="member-activity" aria-label="国会での活動">
    <h5>国会での活動（参考・点数には入れない）</h5>
    {d && (d.speeches > 0 ? <>
      <dl className="policy-metrics">
        <div><dt>会議録の発言</dt><dd>{d.speeches.toLocaleString('ja-JP')}回</dd></div>
        <div><dt>衆議院／参議院</dt><dd>{d.shugiin.toLocaleString('ja-JP')}／{d.sangiin.toLocaleString('ja-JP')}回</dd></div>
        <div><dt>発言した会議</dt><dd>{d.meetings.toLocaleString('ja-JP')}回</dd></div>
        <div><dt>大臣・副大臣として</dt><dd>{d.asMinister.toLocaleString('ja-JP')}回</dd></div>
        <div><dt>委員長として</dt><dd>{d.asChair.toLocaleString('ja-JP')}回</dd></div>
        {d.first && <div><dt>最初の発言</dt><dd>{d.first}</dd></div>}
      </dl>
      <ul className="member-evidence">{d.recent.slice(0, 5).map(s => <li key={s.url}>
        <span>{s.date}・{s.house}{s.meeting}{s.position ? `（${s.position}）` : ''}</span>
        <a href={s.url} target="_blank" rel="noopener noreferrer">国会会議録 <ArrowUpRight size={13} /></a>
      </li>)}</ul>
    </> : <p className="fine-note">この表記の名前では会議録に発言が見つかりませんでした（ひらがな表記などの違いの可能性があります）。</p>)}
    {!!entry.roles?.length && <ul className="member-evidence">{entry.roles.map(r => <li key={r.url + r.title}>
      <span>{ROLE_LABEL[r.category] ?? r.category}：{r.title}{r.period ? `（${r.period}）` : ''}</span>
      <a href={r.url} target="_blank" rel="noopener noreferrer">{r.source} <ArrowUpRight size={13} /></a>
    </li>)}</ul>}
    <p className="fine-note">{fetchedAt} 時点で機械的に集めた数です。同姓同名の別人の発言が混ざる場合があります。役職は公的機関・政党の公式ページで確かめられたものだけを載せ、内容はリンク先で確認してください。</p>
  </section>;
}

const pct = (x: number) => `${(x * 100).toFixed(x < 0.01 ? 3 : 1)}%`;

function EvidenceLink({ ev }: { ev: MemberEvidence }) {
  return <li>
    <span>{ev.date}・{ev.house}・{ev.actionLabel}{ev.title && ev.action !== 'vote' ? `（${ev.title}）` : ''}</span>
    <a href={ev.url} target="_blank" rel="noopener noreferrer">{hostLabel(ev.url)} <ArrowUpRight size={13} /></a>
  </li>;
}

/** 1本の法律について、行動 → 成立 → 損失（便益）の鎖と、この人の分の式。 */
function CausalChain({ entry, law }: { entry: MemberLaw; law: PublicMemberLaw }) {
  const g = law.game;
  const verb = law.side === 'loss' ? '失わせた' : '生んだ';
  const roles = Object.entries(entry.roles) as [CausalRole, number][];
  const formula = roles.map(([role, x]) => role === 'proposer'
    ? `提出者の組の割合 ${pct(g.vetoShare)} ÷ 提出者${g.proposers}人 ＝ ${pct(x)}`
    : `賛成1票の割合 ${pct(x)}`).join(' ＋ ');
  return <>
    <ol className="member-chain">
      <li><strong>行動</strong>{roles.length ? roles.map(([role]) => CAUSAL_ROLE_LABEL[role]).join('・') : '成立を左右しない行動だけ（0円）'}
        <ul className="member-evidence">{entry.evidence.map(ev => <EvidenceLink key={ev.url + ev.action} ev={ev} />)}</ul></li>
      <li><strong>この行動が無かったら</strong>{roles.some(([r]) => r === 'proposer')
        ? `提出が無ければ法律は成立しません。成立に欠かせない「拒否権者」は、提出者の組（${g.proposerKind}）と衆議院の賛成会派の2つです。参議院は可決に${g.quota}票が要る中で${g.yes}票の賛成でした。投票の順番をすべて等しく考えたとき、提出者の組が成立を決める場面の割合は${pct(g.vetoShare)}です（Shapley 値）。`
        : roles.length ? `参議院本会議は可決に${g.quota}票が要る中で、賛成${g.yes}・反対${g.no}でした。賛成票の1票が成立を決める場面の割合は${pct(g.voteShare)}です（Shapley 値）。`
        : '質疑や修正案は、それが無くても成立したかどうかを変えないため、額は配りません。'}
        {g.voteUrl && <a href={g.voteUrl} target="_blank" rel="noopener noreferrer">参議院の投票結果（{g.voteDate}） <ArrowUpRight size={13} /></a>}</li>
      <li><strong>成立</strong>{law.enactedOn ? `${law.enactedOn} 公布` : '成立'}
        <a href={law.source} target="_blank" rel="noopener noreferrer">衆議院の議案情報（審議経過） <ArrowUpRight size={13} /></a></li>
      <li><strong>{law.side === 'loss' ? '損失' : '便益'}</strong>施行の前後で「{law.group}」を比較国と比べた差が {formatYen(law.amount.median)}（幅 {formatYen(law.amount.low)}〜{formatYen(law.amount.high)}）。確かさの印：{law.confidence}</li>
    </ol>
    {roles.length > 0 && <p className="member-formula">この人が{verb}額 ＝ 法律の額 {formatYen(law.amount.median)} × {formula} ＝ {formatYen(entry.share.median)}</p>}
    {entry.context.length > 0 && <details className="member-context"><summary>額に入れていない行動（{entry.context.length}件）</summary>
      <ul className="member-evidence">{entry.context.map(ev => <EvidenceLink key={ev.url + ev.action} ev={ev} />)}</ul></details>}
  </>;
}

function MemberDetail({ member, laws, activity }: { member: PublicMember; laws: Map<string, PublicMemberLaw>; activity: MemberActivity | null }) {
  return <div className="member-detail">
    {member.laws.map(entry => {
      const law = laws.get(entry.lawId)!;
      return <section key={entry.lawId} className={`member-law ${entry.side}`} aria-label={law.title}>
        <p className="law-card-side">{entry.side === 'loss' ? '国賊側（損失）' : '国士側（便益）'}・{law.id}</p>
        <h5>{law.title}</h5>
        <p className="member-law-share"><span>{entry.side === 'loss' ? 'この法律で失わせた額' : 'この法律で生んだ額'}</span><strong>{formatYen(entry.share.median)}</strong><span>幅 {formatYen(entry.share.low)}〜{formatYen(entry.share.high)}・法律の額の{pct(entry.fraction)}</span></p>
        <CausalChain entry={entry} law={law} />
      </section>;
    })}
    <dl className="policy-metrics member-sensitivity">
      <div><dt>委員長も拒否権者とした場合</dt><dd>{signedYen(member.sensitivity.chairVetoNet)}（{member.sensitivity.chairVetoRank}位）</dd></div>
    </dl>
    {member.sensitivity.flagged && <p className="fine-note">委員長を拒否権者に数えるかどうかで、順位が{member.sensitivity.maxMove}位動きます。</p>}
    {member.overlappingGroups.length > 0 && <p className="fine-note">同じ観測グループ（{member.overlappingGroups.join('・')}）の法律を複数足しています。同じ統計の動きを別々の法律で数えているため、合計は重なりを含み、大きめに出ます。</p>}
    {activity && <ActivityPanel entry={activity.members[member.name]} fetchedAt={activity.fetchedAt} />}
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
  const [activity, setActivity] = useState<MemberActivity | null>(null);
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
  useEffect(() => {
    const controller = new AbortController();
    void fetch(distributionActivityUrl, { signal: controller.signal, cache: 'no-store' })
      .then(r => r.ok ? r.text() : Promise.reject(new Error('missing'))).then(text => setActivity(readActivity(text))).catch(() => undefined);
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
      <h2>この人が失わせた額・生んだ額</h2>
      <p>法律が日本に与えた損失（国賊側）と便益（国士側）を、<strong>「この人の行動が無かったら、その法律は成立したか」</strong>で人に配りました。提出者が出さなければ、また参議院で賛成票が足りなければ、法律は成立せず、損失も便益も生まれません。成立のしくみ（拒否権者と過半数の投票）の中で、その人の行動が成立を決める場面の割合（Shapley 値）を出し、法律の額に掛けたものが<strong>この人が失わせた額</strong>・<strong>生んだ額</strong>です。各人の欄に、行動 → 成立 → 損失のつながりを一次資料（国会会議録・参議院の投票結果・衆議院の議案情報）のリンクつきで示し、式も載せています。計算のしかたは<a href="/methodology">計算方法</a>にあります。</p>
      <p className="fine-note">記録や判定に誤りがあれば、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">訂正・反論の窓口（GitHub の Issue）</a>から公開資料を添えて知らせてください。本人・関係者からの反論も同じ窓口で受け付け、確認できたものは記録と額に反映します。</p>
      {error && <p className="state-banner" role="alert">{error}</p>}
      {data && <>
        <section aria-label="元になった法律" className="law-funnel">
          <p className="law-funnel-lead">{data.laws.length}本の法律、{data.counts.members}人（国賊側{data.counts.loss}人・国士側{data.counts.benefit}人・0円{data.counts.zero}人）。額を配った行動（提出・参議院の賛成）{data.counts.involvements.toLocaleString('ja-JP')}件、額に入れない行動（質疑・修正案・委員長）{data.counts.context}件、外した行動{data.counts.excluded}件。</p>
          <ul className="members-laws">{data.laws.map(law => <li key={law.id} className={law.side}>
            <span>{law.side === 'loss' ? '国賊側' : '国士側'}・{law.id}</span>
            <strong>{law.title}</strong>
            <small>額 {formatYen(law.amount.median)}（幅 {formatYen(law.amount.low)}〜{formatYen(law.amount.high)}）・{law.persons}人に{formatYen(law.attributed.median)}・衆議院の賛成会派（{law.game.parties.join('、')}）に{formatYen(law.game.party.median)}・確かさの印：{law.confidence}</small>
          </li>)}</ul>
          <p className="fine-note">確かさの印が「コロナ期と重なる」「未測定」の法律は、法律ランキングでは額を公開判定にしていないものです。ここでは印を付けたまま配分に含めています。参考扱いの額（段階1・貸出残高）は配分していません。衆議院は起立採決で個人の賛否が記録に残らないため、衆議院の分は個人ではなく賛成した会派に置いています。額が出た法律が増えると、このページも同じ計算で更新されます。</p>
        </section>
        <section aria-label="上位の議員" className="members-top">
          <h3>失わせた額の上位10人（国賊側）</h3>
          <RankBars caption="国賊側の純額の大きい順" format={formatYen} items={topBars(data.members, 'loss')} />
          <h3>生んだ額の上位10人（国士側）</h3>
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
              <MemberDetail member={member} laws={laws} activity={activity} />
            </details>
          </li>)}</ol>
        </section>
        <section className="lower-panel" aria-label="この画面の読み方">
          <p><Info size={16} /> 点数は 純額 ＝ 生んだ額（国士側の法律から）− 失わせた額（国賊側の法律から）です。マイナスが国賊側、プラスが国士側。順位は純額の小さい順（国賊側が上）です。幅は比較国の伸びの四分位から来ています。</p>
          <p className="fine-note">結果で評価しており、提出者や賛成者の意図や予見は問いません。額は推計で、幅と確かさの印の範囲で読むものです。成立に欠かせない提出者には大きな割合が、多数の中の1票には小さな割合が付きます。反対した人は、成立した法律では成立を決めていないため0円です（反対で成立を止めた・遅らせた法案は、額が出たら同じ式で数えます）。記録の無い人は対象外で、0円とは別です。ルール：{data.rules.join('・')}。</p>
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
      <h3>2. この人が失わせた額・生んだ額</h3>
      <p>問いは「この人の行動が無かったら、その法律は成立したか」です。法律が成立しなければ、その損失（便益）は生まれません。そこで成立のしくみを投票のゲームとして書き、各人の行動が成立を決める割合を Shapley 値で出します。全員の割合の合計は1なので、配った額の合計は法律の額を超えません。</p>
      <p className="member-formula">この人が失わせた額（または生んだ額） ＝ 法律の額 × この人の Shapley 値</p>
      <ol>
        <li>拒否権者（欠けたら成立しない）：提出者の組（閣法は閣議決定に関わった大臣、衆法は発議者）と、衆議院の賛成会派。</li>
        <li>参議院本会議：賛成した議員は互いに同じ立場で、可決には q ＝ (賛成＋反対)÷2 を切り捨てて＋1 票が要る。</li>
        <li>拒否権者 k 人・賛成 Y 人のとき、拒否権者1人の値 φ ＝ (1/n) Σ<sub>j=q..Y</sub> C(Y, j) ÷ C(n−1, j+k−1)（n ＝ k＋Y）。賛成1票の値 ＝ (1 − kφ) ÷ Y。</li>
        <li>提出者の組の値は、記録のある提出者で等分する。衆議院の賛成会派の値は、起立採決で個人の賛否が残らないため、党（会派）に置き、個人には配らない。</li>
        <li>委員長は、委員会の多数決と中間報告で採決を通せるため、基準では拒否権者にしない。委員長も拒否権者とした場合の額と順位を、各議員の欄に出す（5位以上動く人には注意を付ける）。</li>
        <li>質疑・修正案は成立したかどうかを変えないため配らない。記録として各議員の欄に出す。反対票は成立を決めていないため0円。</li>
        <li>数えるのは、行動（会議録・投票結果）→ 成立（議案の審議経過）→ 額（公的統計）がすべて一次資料でつながるものだけ。円の端数は最大剰余法で配り、人・会派・名前不明の賛成票の合計が法律の額にぴったり一致する。</li>
      </ol>
      <p className="fine-note">例：参議院で賛成214・反対16（可決に116票）、拒否権者2つのとき、提出者の組は35.4%、賛成1票は0.137%。提出者が3人なら1人11.8%。</p>
      <h3>3. 点数</h3>
      <p>点数（純額）＝ 国士側の法律からの配分の合計 − 国賊側の法律からの配分の合計。マイナスが国賊側、プラスが国士側。同じ統計（観測グループ）の動きを複数の法律で数えている人は、合計が重なりを含むため、その旨を表示する。</p>
      <h3>4. 訂正と反論</h3>
      <p>誤り・反証・本人や関係者からの反論は、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">GitHub の Issue（訂正・異議の申し立て）</a>で受け付けます。公開資料の出典を添えてください。確認できたものは記録を直し、同じ計算で額と順位を出し直します。受付後の流れは<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/corrections.md" target="_blank" rel="noopener noreferrer">訂正の手順</a>にあります。</p>
      <h3>5. 元のデータとコード</h3>
      <ul>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/involvements.csv" target="_blank" rel="noopener noreferrer">関与の一覧（行動・日付・一次資料の URL、外した行動と理由を含む）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/loss-rule.ts" target="_blank" rel="noopener noreferrer">損失の計算（loss-rule.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/causal-allocation.ts" target="_blank" rel="noopener noreferrer">成立への寄与の計算（causal-allocation.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/votes.csv" target="_blank" rel="noopener noreferrer">参議院本会議の票数（votes.csv）</a></li>
        <li><a href="/distribution/members.json">議員ページの配布データ（members.json）</a></li>
      </ul>
    </main>
  </div>;
}
