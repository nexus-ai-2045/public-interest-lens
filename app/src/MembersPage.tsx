import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Info } from 'lucide-react';
import { SiteShell } from './SiteHeader';
import { toneTitle, useTone } from './site-tone';
import { formatYen } from './LawRankingPage';
import { Burst, CountUp, RankBars, Reveal, type RankBarItem } from './motion';
import { distributionActivityUrl, readActivity, type MemberActivity, type MemberActivityEntry } from './member-activity';
import { ROLE_LABEL as CAUSAL_ROLE_LABEL, type MemberEvidence, type MemberLaw, type PublicMember, type PublicMemberLaw, type PublicMembers, type PartyRanking, allocatedAmount } from './members-build';
import { DEFAULT_KNOBS, isDefaultKnobs, readKnobs, writeKnobs, type CausalRole, type Knobs } from './causal-allocation';
import { adjustMembers } from './members-knobs';
import { AllMembers } from './AllMembers';
import { distributionReferenceUrl } from './all-members-view';
import type { PublicMembersReference } from './members-reference';
import { partyById, partyComparison, sortPartyRows, type PartySortKey } from './party-compare';
import { LawName, lawNameText, namingOf, useLawNames } from './law-name';
import { CORRECTION_EMAIL, correctionIssueUrl, correctionListUrl, correctionMailUrl, type CorrectionTarget } from './correction-link';
const MethodFormulas = lazy(() => import('./MethodFormulas'));

export const distributionMembersUrl = '/distribution/members.json';
export const correctionUrl = 'https://github.com/nexus-ai-2045/public-interest-lens/issues/new?template=correction.yml';

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
function CausalChain({ entry, law, adjusted }: { entry: MemberLaw; law: PublicMemberLaw; adjusted: boolean }) {
  const g = law.game;
  const verb = entry.effect === 'bad' ? '失わせた' : '生んだ';
  const amountLabel = law.observationLaws > 1 ? `法律の分（観測の額の${law.observationLaws}分の1）` : '法律の額';
  if (entry.direction === 'against') return <>
    <ol className="member-chain">
      <li><strong>行動</strong>参議院本会議で反対（{g.voteDate}）
        <ul className="member-evidence">{entry.evidence.map(ev => <EvidenceLink key={ev.url + ev.action} ev={ev} />)}</ul></li>
      <li><strong>向き</strong>{law.side === 'loss' ? '損失を生んだ法律を止めようとしたので、国士側に数えます。' : '便益を生んだ法律を止めようとしたので、国賊側に数えます。'}賛成1票と同じ割合（{pct(entry.fraction)}）を、向きを逆にして配ります。反対票の分は、法律の額の配分（提出者・賛成会派・賛成票で合計1）とは別に数えます。</li>
      <li><strong>{law.side === 'loss' ? '損失' : '便益'}</strong>施行の前後で「{law.group}」を比較国と比べた差が {formatYen(law.amount.median)}。確かさの印：{law.confidence}</li>
    </ol>
    <p className="member-formula">この人が{verb}額 ＝ {amountLabel} {formatYen(allocatedAmount(law).median)} × 賛成1票の割合 {pct(entry.fraction)} ＝ {formatYen(entry.share.median)}</p>
  </>;
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
      <li><strong>{law.side === 'loss' ? '損失' : '便益'}</strong>施行の前後で「{law.group}」を比較国と比べた差が {formatYen(law.amount.median)}（幅 {formatYen(law.amount.low)}〜{formatYen(law.amount.high)}）。確かさの印：{law.confidence}
        {law.observationLaws > 1 && `。同じ額の系列・同じ期間の観測を${law.observationLaws}本の法律が共有しているので、この法律の分は${law.observationLaws}分の1の ${formatYen(allocatedAmount(law).median)} です（同じ差を何度も数えないため）。`}</li>
    </ol>
    {roles.length > 0 && (adjusted
      ? <p className="member-formula">つまみで調整した値：この人が{verb}額 ＝ {amountLabel} {formatYen(allocatedAmount(law).median)} × {pct(entry.fraction)} ＝ {formatYen(entry.share.median)}（上の割合は初期値の計算）</p>
      : entry.office.median !== 0
        ? <p className="member-formula">この人が{verb}額 ＝ {amountLabel} {formatYen(allocatedAmount(law).median)} × {formula} − 役職の帳簿（閣法の提出者の分）{formatYen(entry.office.median)} ＝ {formatYen(entry.share.median)}</p>
        : <p className="member-formula">この人が{verb}額 ＝ {amountLabel} {formatYen(allocatedAmount(law).median)} × {formula} ＝ {formatYen(entry.share.median)}</p>)}
    {entry.office.median !== 0 && <p className="fine-note">このうち {formatYen(entry.office.median)} は、閣法を閣議決定した担当の大臣としての分です。担当として出しただけで、本人が推したかどうかは分からないため、点数には入れていません（役職の帳簿。つまみ「担当の大臣の分も点数に入れる」で入れられます）。</p>}
    {entry.context.length > 0 && <details className="member-context"><summary>額に入れていない行動（{entry.context.length}件）</summary>
      <ul className="member-evidence">{entry.context.map(ev => <EvidenceLink key={ev.url + ev.action} ev={ev} />)}</ul></details>}
  </>;
}

/** 反論・訂正の Issue に入れる対象と出典。この人の欄に出している一次資料（額に入れていない行動を含む）の順に並べる。 */
export function memberCorrectionTarget(member: PublicMember, laws: Map<string, PublicMemberLaw>): CorrectionTarget {
  const sources = member.laws.flatMap(entry => {
    const law = laws.get(entry.lawId);
    return [
      ...[...entry.evidence, ...entry.context].map(ev => ({ label: `${law?.title ?? entry.lawId}・${ev.actionLabel}（${ev.date}）`, url: ev.url })),
      ...(law?.game.voteUrl ? [{ label: `${law.title}・参議院の投票結果`, url: law.game.voteUrl }] : []),
      ...(law ? [{ label: `${law.title}・衆議院の議案情報`, url: law.source }] : []),
    ];
  });
  return { title: member.id, page: `/members?name=${encodeURIComponent(member.id)}`, sources };
}

function MemberDetail({ member, laws, activity, adjusted }: { member: PublicMember; laws: Map<string, PublicMemberLaw>; activity: MemberActivity | null; adjusted: boolean }) {
  const names = useLawNames();
  return <div className="member-detail">
    {member.laws.map(entry => {
      const law = laws.get(entry.lawId)!;
      const naming = namingOf(names, law.id);
      return <section key={entry.lawId + entry.direction} className={`member-law ${entry.effect === 'bad' ? 'loss' : 'benefit'}`} aria-label={lawNameText(law.title, naming.what)}>
        <p className="law-card-side">{entry.effect === 'bad' ? '国賊側' : '国士側'}（{entry.side === 'loss' ? '損失の法律' : '便益の法律'}に{entry.direction === 'against' ? '反対' : '関わった'}）・{law.id}</p>
        <h5><LawName title={law.title} {...naming} /></h5>
        <p className="member-law-link"><a href={`/ranking#${encodeURIComponent(law.id)}`}>この法律の行を法律ランキングで開く（額の計算・一次資料・ほかの議員）</a></p>
        <p className="member-law-share"><span>{entry.effect === 'bad' ? 'この法律で失わせた額' : 'この法律で生んだ額'}{entry.direction === 'against' ? '（反対票）' : ''}</span><strong>{formatYen(entry.share.median)}</strong><span>幅 {formatYen(entry.share.low)}〜{formatYen(entry.share.high)}・{law.observationLaws > 1 ? `この法律の分（観測の額の${law.observationLaws}分の1）の` : '法律の額の'}{pct(entry.fraction)}</span></p>
        <CausalChain entry={entry} law={law} adjusted={adjusted} />
      </section>;
    })}
    <dl className="policy-metrics member-sensitivity">
      <div><dt>委員長も拒否権者とした場合</dt><dd>{signedYen(member.sensitivity.chairVetoNet)}（{member.sensitivity.chairVetoRank}位）</dd></div>
    </dl>
    {member.sensitivity.flagged && <p className="fine-note">委員長を拒否権者に数えるかどうかで、順位が{member.sensitivity.maxMove}位動きます。</p>}
    {member.overlappingGroups.length > 0 && <p className="fine-note">同じ観測グループ（{member.overlappingGroups.join('・')}）の法律を複数足しています。期間と額の幅まで同じ観測を共有する法律は、観測の額を本数で割ってから配っています。期間が重なる別の観測（窓の長さが違うものなど）は全額ずつ足しているため、その分の合計は重なりを含み、大きめに出ます。</p>}
    {activity && <ActivityPanel entry={activity.members[member.id]} fetchedAt={activity.fetchedAt} />}
    <p className="correction-row"><a className="correction-link" href={correctionIssueUrl(memberCorrectionTarget(member, laws))} target="_blank" rel="noopener noreferrer">反論・訂正</a><span>この人の記録への反論・訂正を GitHub の Issue で送る（対象と出典は入った状態で開きます）</span><a href={correctionListUrl(member.id)} target="_blank" rel="noopener noreferrer">寄せられた反論・訂正を見る</a>{CORRECTION_EMAIL && <a href={correctionMailUrl(memberCorrectionTarget(member, laws), CORRECTION_EMAIL)}>GitHub を使わずメールで送る</a>}</p>
  </div>;
}

/** 見え方のつまみ。動かすとその場で並べ替え、値は URL に入る。 */
export function KnobsPanel({ knobs, onChange }: { knobs: Knobs; onChange: (k: Knobs) => void }) {
  const slider = (key: 'proposer' | 'rate', label: string, min: number, note: string) => <label className="knob">
    <span>{label}<strong>{Math.round(knobs[key] * 100)}%</strong></span>
    <input type="range" min={min} max={100} step={5} value={Math.round(knobs[key] * 100)} onChange={e => onChange({ ...knobs, [key]: Number(e.target.value) / 100 })} />
    <small>{note}</small>
  </label>;
  return <section className="members-knobs" aria-label="見え方のつまみ">
    <h3>つまみ（見え方の調整）</h3>
    {slider('proposer', '提出者（大臣・発議者）の重み', 0, '下げた分は、衆議院の賛成会派と参議院の賛成票に、いまの割合どおりに回します。')}
    <label className="knob"><span>衆議院の分</span>
      <select value={knobs.party} onChange={e => onChange({ ...knobs, party: e.target.value as Knobs['party'] })}>
        <option value="party">党（賛成会派）に置く</option>
        <option value="voters">参議院の賛成議員で分ける</option>
      </select>
      <small>衆議院は起立採決で個人の賛否が残らないため、初期値は党に置きます。</small></label>
    <label className="knob knob-check"><input type="checkbox" checked={knobs.chairVeto} onChange={e => onChange({ ...knobs, chairVeto: e.target.checked })} /><span>委員長も拒否権者にする</span></label>
    <label className="knob knob-check"><input type="checkbox" checked={knobs.office} onChange={e => onChange({ ...knobs, office: e.target.checked })} /><span>担当の大臣の分も点数に入れる</span></label>
    {slider('rate', '帰属率（人と党に配る割合）', 10, '残りは誰にも配りません（組織や外部の要因）。')}
    <p className="fine-note">どの設定でも、配る額の合計は法律の額を超えません。{!isDefaultKnobs(knobs) && <> <button type="button" onClick={() => onChange(DEFAULT_KNOBS)}>初期値に戻す</button></>}</p>
  </section>;
}

/** 上位の横棒。値は純額の大きさ、幅は小さい方から並べ直す。 */
export function topBars(members: PublicMember[], side: 'loss' | 'benefit', count = 10): RankBarItem[] {
  const picked = side === 'loss' ? members.filter(m => m.net.median < 0).slice(0, count) : members.filter(m => m.net.median > 0).reverse().slice(0, count);
  return picked.map(m => {
    const ends = [Math.abs(m.net.low), Math.abs(m.net.high)].sort((a, b) => a - b);
    const crosses = m.net.low < 0 && m.net.high > 0;
    return { id: m.id, label: m.name, value: Math.abs(m.net.median), low: crosses ? 0 : ends[0], high: ends[1], side, note: `${m.rank}位・${m.laws.length}本の法律から`, href: `/members?name=${encodeURIComponent(m.id)}` };
  });
}

/** いま選んでいる側の1位を大きく出す。国賊は暗い枠に黒い破片、国士は明るい枠に金の光の粒。額と幅は常に文字で出す。 */
function ToneHero({ members }: { members: PublicMember[] }) {
  const [tone] = useTone();
  const side = tone === 'harm' ? 'loss' : 'benefit';
  const top = side === 'loss' ? members.find(m => m.net.median < 0) : [...members].reverse().find(m => m.net.median > 0);
  if (!top) return null;
  return <Reveal tone={side} className={`tone-hero ${side}`} key={`${side}-${top.id}`}>
    <a href={`/members?name=${encodeURIComponent(top.id)}`}>
      <span className="tone-hero-badge">{side === 'loss' ? '国賊 1位' : '国士 1位'}<Burst tone={side} count={22} /></span>
      <strong className="tone-hero-name">{top.name}</strong>
      <span className="tone-hero-amount"><span>{side === 'loss' ? 'この人が失わせた額（純額）' : 'この人が生んだ額（純額）'}</span><b><CountUp value={Math.abs(top.net.median)} format={formatYen} /></b><small>幅 {signedYen(top.net.low)}〜{signedYen(top.net.high)}・{top.laws.length}本の法律から</small></span>
    </a>
  </Reveal>;
}

/** 一覧に最初に並べる人数と、「さらに表示」で足す人数。 */
export const MEMBERS_PAGE_SIZE = 30;

/** 上から limit 人まで。それより下でも、URL や検索で指された人（focus）は並べる。 */
export function visibleMembers(shown: PublicMember[], limit: number, focus: string): PublicMember[] {
  return shown.length <= limit ? shown : shown.filter((m, i) => i < limit || m.id === focus);
}

export type PartySort = 'perPerson' | 'perLaw' | 'perVote' | 'total';
const PARTY_SORTS: { key: PartySort; label: string }[] = [{ key: 'perPerson', label: '1人あたり' }, { key: 'perLaw', label: '1本あたり' }, { key: 'perVote', label: '1票あたり' }, { key: 'total', label: '総額（参考）' }];
/** 政党ランキングの並べ替え。純額の小さい順（国賊側が上）。 */
export function sortBlocs(ranking: PartyRanking, by: PartySort) {
  const value = (b: PartyRanking['blocs'][number]) => by === 'total' ? b.net.median : b[by];
  return [...ranking.blocs].sort((a, b) => value(a) - value(b) || a.bloc.localeCompare(b.bloc));
}

export function PartyRankingPanel({ ranking }: { ranking: PartyRanking }) {
  const [by, setBy] = useState<PartySort>('perPerson');
  const rows = sortBlocs(ranking, by);
  const cert = (c: Record<string, number>) => ['高', '中', '低'].filter(k => c[k]).map(k => `${k}${c[k]}`).join('・');
  return <section aria-label="政党ランキング" className="members-party-ranking">
    <h3>政党ランキング（参議院本会議の賛否を、採決した時の会派で集計）</h3>
    <p className="fine-note">上の議員の額を、その法律を参議院で採決した時の会派の系統ごとに足したものです（新しい額ではありません）。与党は人数も賛成する本数も多く、総額は会派の大きさで大きくなるため、1人あたり・1本あたりで並べます。1票あたりは、1人が1本に示した賛否1つあたりの額です。総額は参考です。</p>
    <p className="fine-note">期間：参議院の採決 {ranking.from}〜{ranking.to}（議員に配っている法律だけ）。確かさの印は、各会派が賛否を示した法律の本数で、ほとんどが「低」です。会派の系統は会派名の一部で寄せています（合流・改称が多いため。中身は各行の会派名で確かめられます）。会派が分からなかった{ranking.unmatched.people}人（衆議院だけの行動など、純額 {signedYen(ranking.unmatched.net.median)}）は入れていません。衆議院の会派別の賛否は下の会派の帳簿にあります（第186回以降だけ）。</p>
    <div className="party-sort" role="group" aria-label="並べ方">{PARTY_SORTS.map(o => <button key={o.key} type="button" aria-pressed={by === o.key} onClick={() => setBy(o.key)}>{o.label}</button>)}</div>
    <div className="ranking-scroll"><table className="party-table">
      <caption className="sr-only">政党ランキング（{PARTY_SORTS.find(o => o.key === by)!.label}の小さい順。マイナスが国賊側）</caption>
      <thead><tr><th scope="col">順位</th><th scope="col">会派の系統</th><th scope="col">1人あたり</th><th scope="col">1本あたり</th><th scope="col">1票あたり</th><th scope="col">純額（参考）</th><th scope="col">人数</th><th scope="col">本数（賛成／反対）</th><th scope="col">賛成した法律のうち損失</th><th scope="col">確かさ</th></tr></thead>
      <tbody>{rows.map((b, i) => <tr key={b.bloc} className={b.net.median < 0 ? 'loss' : 'benefit'}>
        <td>{i + 1}</td>
        <th scope="row"><span className="party-side">{b.net.median < 0 ? '国賊側' : '国士側'}</span> {b.bloc}<details><summary>会派名</summary><small>{b.parties.join('、')}</small></details></th>
        <td>{signedYen(b.perPerson)}</td><td>{signedYen(b.perLaw)}</td><td>{signedYen(b.perVote)}</td><td>{signedYen(b.net.median)}</td>
        <td>{b.people}人</td><td>{b.laws}本（{b.yesLaws}／{b.noLaws}）</td><td>{Math.round(b.lossShareOfYes * 100)}%</td><td>{cert(b.certainty)}</td>
      </tr>)}</tbody>
    </table></div>
  </section>;
}

/** 一覧の所属政党の表示。現職は政党名、表がまだ読めていないときは空、それ以外（元職・当時）は「元職」。 */
export function partyLabel(id: string, parties: ReadonlyMap<string, string>, loaded: boolean, former: ReadonlyMap<string, string> = new Map()): string {
  const last = former.get(id);
  return parties.get(id) ?? (loaded ? (last ? `元職・${last}` : '元職') : '');
}

const AFFILIATION_SORTS: { key: PartySortKey; label: string }[] = [{ key: 'perPerson', label: '1人あたり' }, { key: 'total', label: '合計' }, { key: 'people', label: '人数' }];

/** 現職の所属政党ごとの比較。議員の確かな額を今の所属政党で足しただけで、新しい額ではない。 */
export function PartyAffiliationPanel({ members, parties, loaded, error, adjusted }: { members: PublicMember[]; parties: ReadonlyMap<string, string>; loaded: boolean; error: string; adjusted: boolean }) {
  const [by, setBy] = useState<PartySortKey>('perPerson');
  const { rows, excluded } = useMemo(() => partyComparison(members, parties), [members, parties]);
  const sorted = useMemo(() => sortPartyRows(rows, by), [rows, by]);
  if (error) return <p className="state-banner" role="alert">{error}</p>;
  if (!loaded) return <p className="fine-note" role="status">所属政党の表を読み込み中…</p>;
  return <section aria-label="所属政党ごとの比較" className="members-party-ranking">
    <h3>所属政党ごとの比較（現職の議員の、今の所属政党で集計）</h3>
    <p className="fine-note">議員の額（上の「議員ランキング」と同じ純額）を、いまの所属政党ごとに足したものです。新しい額ではありません。過去に別の党にいたときの行動も、いまの党に入ります。元職・当時だけの{excluded}人（全{members.length}人のうち）は政党が決められないため入れていません。国賊側の上位は元職が多く、その分は下の「採決した時の会派」で見られます。政党名は名簿の表記（略称）のままです。党は大きいほど合計が大きくなるので、まず1人あたりで並べます。{adjusted && '見え方のつまみを変えた値で集計しています。'}</p>
    <div className="party-sort" role="group" aria-label="並べ方">{AFFILIATION_SORTS.map(o => <button key={o.key} type="button" aria-pressed={by === o.key} onClick={() => setBy(o.key)}>{o.label}</button>)}</div>
    <div className="ranking-scroll"><table className="party-table">
      <caption className="sr-only">所属政党ごとの比較（{AFFILIATION_SORTS.find(o => o.key === by)!.label}。マイナスが国賊側）</caption>
      <thead><tr><th scope="col">順位</th><th scope="col">政党</th><th scope="col">1人あたり</th><th scope="col">合計</th><th scope="col">人数</th><th scope="col">国賊側／国士側／0円</th></tr></thead>
      <tbody>{sorted.map((r, i) => <tr key={r.party} className={r.total < 0 ? 'loss' : 'benefit'}>
        <td>{i + 1}</td>
        <th scope="row"><span className="party-side">{r.total < 0 ? '国賊側' : '国士側'}</span> {r.party}</th>
        <td>{signedYen(r.perPerson)}</td><td>{signedYen(r.total)}</td><td>{r.people}人</td><td>{r.loss}人／{r.benefit}人／{r.zero}人</td>
      </tr>)}</tbody>
    </table></div>
  </section>;
}

export function MembersPage() {
  const [data, setData] = useState<PublicMembers | null>(null);
  const [error, setError] = useState('');
  const [activity, setActivity] = useState<MemberActivity | null>(null);
  const [tone] = useTone();
  const [side, setSide] = useState<'all' | 'loss' | 'benefit'>(() => tone === 'harm' ? 'all' : 'benefit');
  useEffect(() => { setSide(tone === 'harm' ? 'all' : 'benefit'); }, [tone]);
  // トップ（/）から来たら、以後のつまみや名前の URL が議員ページのものになるよう /members に揃える。
  if (window.location.pathname === '/') window.history.replaceState(window.history.state, '', `/members${window.location.search}${window.location.hash}`);
  const [query, setQuery] = useState(() => new URLSearchParams(window.location.search).get('name') ?? '');
  // 名前を選んだら、その人の欄を開いて画面に出す（ページの下の方に開くだけだと、押しても何も起きないように見える）。
  const [focus, setFocus] = useState(() => new URLSearchParams(window.location.search).get('name') ?? '');
  const openMember = (name: string) => {
    setPartyFilter('');
    setQuery(name);
    setFocus(name);
    const params = new URLSearchParams(window.location.search);
    params.set('name', name);
    window.history.pushState(null, '', `${window.location.pathname}?${params}`);
  };
  useEffect(() => {
    if (!focus || !data) return;
    requestAnimationFrame(() => document.getElementById(`member-${focus}`)?.scrollIntoView({ block: 'start' }));
  }, [focus, data]);
  useEffect(() => {
    const restore = () => { const q = new URLSearchParams(window.location.search); const name = q.get('name') ?? ''; setQuery(name); setFocus(name); setTab(q.get('tab') === 'party' && !name ? 'party' : 'members'); };
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const onTopClick = (event: React.MouseEvent) => {
    const link = (event.target as HTMLElement).closest('a');
    const name = link ? new URL(link.href).searchParams.get('name') : null;
    if (!name || new URL(link!.href).pathname !== '/members') return;
    event.preventDefault();
    openMember(name);
  };
  useEffect(() => { document.title = `議員・実名｜${toneTitle(tone)}`; }, [tone]);
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
  // 現職の所属政党と院は参考の表（members-reference.json）から人物IDで結ぶ。全議員の表も同じものを使う。
  const [reference, setReference] = useState<PublicMembersReference | null>(null);
  const [referenceError, setReferenceError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void fetch(distributionReferenceUrl, { signal: controller.signal, cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json() as Promise<PublicMembersReference>; })
      .then(setReference).catch(e => { if (!controller.signal.aborted) setReferenceError(`所属政党の表を読み込めませんでした（${e instanceof Error ? e.message : e}）`); });
    return () => controller.abort();
  }, []);
  const partyMap = useMemo(() => reference ? partyById(reference.members) : new Map<string, string>(), [reference]);
  // 元職の人は、参議院の投票記録に最後に出てくる会派を添える（あれば）。
  const formerMap = useMemo(() => new Map((reference?.members ?? []).filter(r => !r.current && r.lastSangiinParty).map(r => [r.id, r.lastSangiinParty] as const)), [reference]);
  const [partyFilter, setPartyFilter] = useState('');
  const partyChoices = useMemo(() => { const c = new Map<string, number>(); for (const party of partyMap.values()) c.set(party, (c.get(party) ?? 0) + 1); return [...c].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ja')).map(([party]) => party); }, [partyMap]);
  // 議員ランキング／政党ごとの比較。名前を指した URL は議員ランキングで開く。
  const [tab, setTab] = useState<'members' | 'party'>(() => { const q = new URLSearchParams(window.location.search); return q.get('tab') === 'party' && !q.get('name') ? 'party' : 'members'; });
  const switchTab = (next: 'members' | 'party') => {
    setTab(next);
    const params = new URLSearchParams(window.location.search);
    if (next === 'party') { params.set('tab', 'party'); params.delete('name'); } else params.delete('tab');
    window.history.replaceState(null, '', `${window.location.pathname}${params.toString() ? `?${params}` : ''}`);
  };
  const [knobs, setKnobsState] = useState<Knobs>(() => readKnobs(new URLSearchParams(window.location.search)));
  const setKnobs = (k: Knobs) => {
    setKnobsState(k);
    const params = writeKnobs(new URLSearchParams(window.location.search), k).toString();
    window.history.replaceState(null, '', `${window.location.pathname}${params ? `?${params}` : ''}`);
  };
  const adjusted = !isDefaultKnobs(knobs);
  const members = useMemo(() => data ? adjustMembers(data, knobs) : [], [data, knobs]);
  const laws = useMemo(() => new Map((data?.laws ?? []).map(l => [l.id, l])), [data]);
  const names = useLawNames();
  const shown = useMemo(() => {
    const all = members;
    const bySide = side === 'loss' ? all.filter(m => m.net.median < 0) : side === 'benefit' ? [...all].filter(m => m.net.median > 0).reverse() : all;
    const q = query.trim();
    const byParty = partyFilter ? bySide.filter(m => partyMap.get(m.id) === partyFilter) : bySide;
    return q ? byParty.filter(m => m.name.includes(q) || m.id.includes(q)) : byParty;
  }, [members, side, query, partyFilter, partyMap]);
  // 537人ぶんのカードを一度に描くと重いので、上から一定数だけ並べ、「さらに表示」で足す。名前で探した結果・URL で指した人は必ず並べる。
  const [limit, setLimit] = useState(MEMBERS_PAGE_SIZE);
  const visible = useMemo(() => visibleMembers(shown, limit, focus), [shown, limit, focus]);
  // 開いたカードだけ中身（法律ごとの根拠の一覧など）を描く。
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const toggleOpened = (id: string, open: boolean) => setOpened(prev => prev.has(id) === open ? prev : (() => { const next = new Set(prev); if (open) next.add(id); else next.delete(id); return next; })());
  return <SiteShell active="/members" label="議員・実名・実データ" className="law-ranking members-page">
    <main>
      <h2>この人が失わせた額・生んだ額</h2>
      <p>議員ごとに、その人の行動で日本が<strong>失った額（国賊側）・生んだ額（国士側）</strong>を並べています。理由（行動→成立→損失の鎖）は、行を開くと出ます。</p>
      <details className="members-intro"><summary>この数字の意味と訂正窓口</summary>
      <p>法律が日本に与えた損失（国賊側）と便益（国士側）を、<strong>「この人の行動が無かったら、その法律は成立したか」</strong>で人に配りました。提出者が出さなければ、また参議院で賛成票が足りなければ、法律は成立せず、損失も便益も生まれません。成立のしくみ（拒否権者と過半数の投票）の中で、その人の行動が成立を決める場面の割合（Shapley 値）を出し、法律の分（ふつうは法律の額。同じ観測を共有する法律では観測の額を本数で割った分）に掛けたものが<strong>この人が失わせた額</strong>・<strong>生んだ額</strong>です。各人の欄に、行動 → 成立 → 損失のつながりを一次資料（国会会議録・参議院の投票結果・衆議院の議案情報）のリンクつきで示し、式も載せています。計算のしかたは<a href="/methodology">計算方法</a>にあります。</p>
      <p className="fine-note">記録や判定に誤りがあれば、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">訂正・反論の窓口（GitHub の Issue）</a>から公開資料を添えて知らせてください。本人・関係者からの反論も同じ窓口で受け付け、確認できたものは記録と額に反映します。</p>
      </details>
      {error && <p className="state-banner" role="alert">{error}</p>}
      {data && <>
        <ToneHero members={members} />
        <div className="members-tabs" role="group" aria-label="表示を切り替える">
          <button type="button" aria-pressed={tab === 'members'} onClick={() => switchTab('members')}>議員ランキング</button>
          <button type="button" aria-pressed={tab === 'party'} onClick={() => switchTab('party')}>政党ごとの比較</button>
        </div>
        {tab === 'members' && <>
        <section aria-label="上位の議員" className="members-top" onClick={onTopClick}>
          {(tone === 'harm' ? ['loss', 'benefit'] as const : ['benefit', 'loss'] as const).map(key => <div key={key} className={`members-top-block ${key}`}>
            <h3>{key === 'loss' ? '失わせた額の上位10人（国賊側）' : '生んだ額の上位10人（国士側）'}</h3>
            <RankBars caption={key === 'loss' ? '国賊側の純額の大きい順' : '国士側の純額の大きい順'} format={formatYen} items={topBars(members, key)} />
          </div>)}
        </section>
        <section aria-label="議員の一覧">
          <h3>全員の一覧</h3>
          <div className="members-controls">
            <div role="group" aria-label="側で絞る">
              {([['all', '全員（国賊側が上）'], ['loss', '国賊側'], ['benefit', '国士側']] as const).map(([key, label]) => <button key={key} type="button" aria-pressed={side === key} onClick={() => setSide(key)}>{label}</button>)}
            </div>
            <label>政党で絞る <select value={partyFilter} onChange={event => setPartyFilter(event.target.value)}><option value="">すべて</option>{partyChoices.map(p => <option key={p} value={p}>{p}</option>)}</select></label>
            <label>名前で探す <input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
            {query && <button type="button" onClick={() => { setQuery(''); setFocus(''); const params = new URLSearchParams(window.location.search); params.delete('name'); window.history.replaceState(null, '', `${window.location.pathname}${params.toString() ? `?${params}` : ''}`); }}>全員を表示</button>}
          </div>
          <p className="fine-note" role="status">{shown.length}人を表示{visible.length < shown.length && `（順位の上から${visible.length}人を並べています）`}</p>
          <ol className="members-list">{visible.map(member => <li key={member.id} id={`member-${member.id}`} className={`member-card ${member.net.median < 0 ? 'loss' : 'benefit'}`}>
            {/* 検索・URL で自動で開いたカードは覚えない（覚えると、検索を消しても開いたまま中身が残る）。人が開いたものだけ覚える。 */}
            <details open={shown.length === 1 || member.id === focus || opened.has(member.id)} onToggle={event => { if (shown.length !== 1 && member.id !== focus) toggleOpened(member.id, event.currentTarget.open); }}>
              <summary>
                <span className="member-rank">{member.rank}位</span>
                <span className="member-name">{member.name}</span>
                <span className="member-party">{partyLabel(member.id, partyMap, reference !== null, formerMap)}</span>
                <span className="member-net"><strong>{signedYen(member.net.median)}</strong><small>幅 {signedYen(member.net.low)}〜{signedYen(member.net.high)}</small></span>
              </summary>
              {(shown.length === 1 || member.id === focus || opened.has(member.id)) && <MemberDetail member={member} laws={laws} activity={activity} adjusted={adjusted} />}
            </details>
          </li>)}</ol>
          {visible.length < shown.length && <p className="members-more"><button type="button" onClick={() => setLimit(n => n + MEMBERS_PAGE_SIZE)}>さらに表示（残り{shown.length - visible.length}人）</button> <button type="button" onClick={() => setLimit(shown.length)}>全員を表示</button></p>}
        </section>
        <AllMembers confirmed={data.members} data={reference} error={referenceError} />
        </>}
        {tab === 'party' && <>
          <PartyAffiliationPanel members={members} parties={partyMap} loaded={!!reference} error={referenceError} adjusted={adjusted} />
        {/* 政党ランキングは初期の配分から作る。つまみを変えた後の議員の額とは合わないので、そのときは出さない。 */}
        {data.partyRanking && data.partyRanking.blocs.length > 0 && (adjusted
          ? <p className="fine-note">政党ランキングは初期の設定の配分で集計しています。見え方のつまみを初期値に戻すと表示されます。</p>
          : <PartyRankingPanel ranking={data.partyRanking} />)}
        {data.parties && data.parties.length > 0 && <section aria-label="会派の帳簿" className="members-parties">
          <h3>会派の帳簿（衆議院の会派別の賛否）</h3>
          <p className="fine-note">衆議院は起立採決で個人の賛否が残らないため、議案の経過に載った会派別の賛否で会派に置きます。賛成会派は衆議院の分を会派の数で等分、反対会派には賛成会派1つと同じ額を向きを逆にして置きます。議員の点数には足していません。会派別の賛否が載るのは第186回国会ごろからの法律だけです。与党は法案の大半に賛成するため、総額ではなく賛否を示した法律1本あたりの額の順に並べています。</p>
          {/* 与党は法案の大半に賛成するので、総額で並べると会派の大きさと与党かどうかで偏る。賛否を示した法律1本あたりで並べる。 */}
          <ol className="members-laws">{[...data.parties].sort((a, b) => a.net.median / a.laws.length - b.net.median / b.laws.length).map(p => <li key={p.name} className={p.net.median < 0 ? 'loss' : 'benefit'}>
            <span>{p.net.median < 0 ? '国賊側' : '国士側'}</span>
            <strong>{p.name}</strong>
            <small>賛否を示した法律1本あたり {signedYen(Math.round(p.net.median / p.laws.length))}（{p.laws.length}本、純額 {signedYen(p.net.median)}）・{p.laws.map(l => `${l.lawId}（${l.direction === 'with' ? '賛成' : '反対'}）`).join('、')}</small>
          </li>)}</ol>
        </section>}
        </>}
        <details className="members-basis" open={adjusted || undefined}><summary>根拠と計算の前提（元になった法律・見え方のつまみ・各帳簿）</summary>
        <section aria-label="元になった法律" className="law-funnel">
          <p className="law-funnel-lead">{data.laws.length}本の法律、{data.counts.members}人（国賊側{data.counts.loss}人・国士側{data.counts.benefit}人・0円{data.counts.zero}人）。額を配った行動（提出・参議院の賛成）{data.counts.involvements.toLocaleString('ja-JP')}件、額に入れない行動（質疑・修正案・委員長）{data.counts.context}件、外した行動{data.counts.excluded}件。</p>
          <ul className="members-laws">{data.laws.map(law => <li key={law.id} className={law.side}>
            <span>{law.side === 'loss' ? '国賊側' : '国士側'}・{law.id}</span>
            <strong><LawName title={law.title} {...namingOf(names, law.id)} /></strong>
            <small>額 {formatYen(law.amount.median)}（幅 {formatYen(law.amount.low)}〜{formatYen(law.amount.high)}）{law.observationLaws > 1 && `・同じ観測を${law.observationLaws}本で分けてこの法律の分は${formatYen(allocatedAmount(law).median)}`}・{law.persons}人に{formatYen(law.attributed.median)}・衆議院の賛成会派（{law.game.parties.join('、')}）に{formatYen(law.game.party.median)}・確かさの印：{law.confidence}</small>
          </li>)}</ul>
          {data.pending && data.pending.length > 0 && <details className="members-pending">
            <summary>確かな額が出ていて、関わった議員の記録を集めている途中の法律 {data.pending.length}本（まだ配分に入っていません）</summary>
            <ul className="members-laws">{data.pending.map(law => <li key={law.id} className={law.side}>
              <span>{law.side === 'loss' ? '国賊側' : '国士側'}・{law.id}</span>
              <strong><a href={`/ranking?q=${encodeURIComponent(law.id)}#${encodeURIComponent(law.id)}`}><LawName title={law.title} {...namingOf(names, law.id)} /></a></strong>
              <small>額 {formatYen(law.median)}・確かさ {law.certainty}。提出者・参議院の個人別の賛否・質疑の記録がそろったら、同じ計算でこのページに入ります。</small>
            </li>)}</ul>
          </details>}
          <p className="fine-note">点数は本人の行動（衆議院の発議者・参議院本会議の賛成と反対）だけで決めます。閣法を閣議決定した担当の大臣の分は「役職の帳簿」として別に見せ、点数に入れません。参議院本会議で反対した人には、賛成1票と同じ割合を向きを逆にして配ります（損失の法律に反対＝国士側、便益の法律に反対＝国賊側）。損失の窓がコロナ期と重なり分けて測れない法律（判定表の R3）は、額がコロナ期の落ち込みをそのまま含むので配りません。確かさの印が「未測定」の法律は、法律ランキングでは額を公開判定にしていないものです。ここでは印を付けたまま配分に含めています。参考扱いの額（段階1・貸出残高）は配分していません。衆議院は起立採決で個人の賛否が記録に残らないため、衆議院の分は個人ではなく会派に置いています（下の会派の帳簿）。会議録から関与を集めていない法律は、議案の提出者の欄と参議院の個人別の賛否だけで機械的に配ります（質疑・委員長の分は入りません）。</p>
        </section>
        <KnobsPanel knobs={knobs} onChange={setKnobs} />
        {data.ministries && data.ministries.length > 0 && <section aria-label="省庁の帳簿" className="members-parties">
          <h3>省庁の帳簿（閣法の所管の省庁）</h3>
          <p className="fine-note">閣法の原案は所管の省庁が書き、国会では所管の大臣が提案理由を説明します。閣法の提出者の組の分（議員の点数に入れない役職の帳簿と同じ額）を、説明した大臣の省庁に置きました。内閣と所管の省庁の組の分で、どちらか一方のせいではありません。議員の点数には足していません。所管する法律が多い省庁ほど総額が大きくなるため、法律1本あたりの額の順に並べています。2001年の再編の前の省庁は、今の名前に寄せています（例：通商産業省→経済産業省）。</p>
          <ol className="members-laws">{data.ministries.map(p => <li key={p.name} className={p.net.median < 0 ? 'loss' : 'benefit'}>
            <span>{p.net.median < 0 ? '国賊側' : '国士側'}</span>
            <strong>{p.name}</strong>
            <small>閣法1本あたり {signedYen(Math.round(p.net.median / p.laws.length))}（{p.laws.length}本、純額 {signedYen(p.net.median)}）・{p.laws.map(l => l.lawId).join('、')}</small>
          </li>)}</ol>
        </section>}
        {data.taxLedger && data.taxLedger.length > 0 && <section aria-label="税の帳簿" className="members-parties">
          <h3>税の帳簿（消費税率を変えた法律）</h3>
          <p className="fine-note">消費税率を変えた法律の額を、内閣府の短期マクロモデルの乗数（税率1%ポイントの引上げで実質GDPが1年目0.28%、2年目0.19%、3年目0.20%下がる）で出しました。延期した法律は、延期した期間に避けた減少を便益として数えます。確かさは「低」で、需要が短期に減る分だけです。税収の使い道（社会保障など）の効果は含みません。法律の額とは物差しが違うので、議員の点数には足していません。額は2020年の円です。</p>
          <ol className="members-laws">{data.taxLedger.map(t => <li key={t.lawId} className={t.total < 0 ? 'loss' : 'benefit'}>
            <span>{t.total < 0 ? '国賊側' : '国士側'}</span>
            <strong>{t.lawId}</strong>
            <small>{t.title}・{t.changes.join('、')}・合計 {signedYen(t.total)}（{t.years.map(y => `${y.year}年 ${signedYen(y.amount)}`).join('、')}）・確かさ {t.certainty}・{t.marks.join('・')}{t.notes.length > 0 ? `・${t.notes.join('・')}` : ''}</small>
          </li>)}</ol>
        </section>}
        {data.resistance && data.resistance.length > 0 && <section aria-label="省庁の抵抗の件数" className="members-parties">
          <h3>省庁の抵抗の件数（規制改革の要望への回答など）</h3>
          <p className="fine-note">規制改革ホットラインで「対応不可」とした回答、規制改革会議の WG のヒアリングで反対・慎重とした発言、フォローアップで反対・慎重・未措置とされた事項を、所管の省庁ごとに数えました。原本と照合し、機械の照合と AI 2系統が一致した記録だけです。額は付けていません。集めた記録は止めた側の事例なので、「対応不可の割合」は省庁全体の回答の割合ではありません。省庁の答弁は内閣の方針の説明であることも多く、省庁だけの抵抗とは限りません。</p>
          <ol className="members-laws">{data.resistance.filter(r => r.total > 0).map(r => <li key={r.ministry} className="loss">
            <span>{r.total}件</span>
            <strong>{r.ministry}</strong>
            <small>ホットラインで対応不可 {r.refusals}件（集めた回答 {r.answers}件のうち）・ヒアリングで反対・慎重 {r.hearings}件・フォローアップで反対・慎重・未措置 {r.followups}件</small>
          </li>)}</ol>
        </section>}
        {data.orgStances && data.orgStances.length > 0 && <section aria-label="団体の立場" className="members-parties">
          <h3>団体の帳簿（審議会・検討会で示した立場）</h3>
          <p className="fine-note">審議会・検討会の議事録で、新しい技術や規制緩和について示した立場を、団体ごとに数えました。原本照合済みの記録だけで、額は付けていません。学者・委員・肩書の無い発言者は個人なので名前を出さず、区分ごとにまとめています。慎重な意見には、安全や消費者保護の理由もあります。</p>
          <ol className="members-laws">{data.orgStances.map(o => <li key={`${o.name}|${o.kind}`} className={o.against + o.careful > o.conditional + o.support ? 'loss' : 'benefit'}>
            <span>反対 {o.against}・慎重 {o.careful}</span>
            <strong>{o.name}</strong>
            <small>{o.kind}・条件付き賛成 {o.conditional}・賛成 {o.support}{o.technologies.length > 0 ? `・${o.technologies.join('、')}` : ''}</small>
          </li>)}</ol>
        </section>}
        </details>
        <section className="lower-panel" aria-label="この画面の読み方">
          <p><Info size={16} /> 点数は 純額 ＝ 生んだ額（国士側の法律から）− 失わせた額（国賊側の法律から）です。マイナスが国賊側、プラスが国士側。順位は純額の小さい順（国賊側が上）です。幅は比較国の伸びの四分位から来ています。</p>
          <p className="fine-note">結果で評価しており、提出者や賛成者の意図や予見は問いません。額は推計で、幅と確かさの印の範囲で読むものです。成立に欠かせない提出者には大きな割合が、多数の中の1票には小さな割合が付きます。参議院本会議で反対した人には、賛成1票と同じ割合を向きを逆にして配ります（成立しなかった法案は、額が出たら同じ式で数えます）。記録の無い人は対象外で、0円とは別です。ルール：{data.rules.join('・')}。</p>
        </section>
      </>}
    </main>
  </SiteShell>;
}

export function MethodologyPage() {
  useEffect(() => { document.title = '計算方法｜国賊／国士ランキング'; }, []);
  return <SiteShell active="/methodology" label="計算方法" className="law-ranking">
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
      <p className="member-formula">この人が失わせた額（または生んだ額） ＝ 法律の分 × この人の Shapley 値</p>
      <p>法律の分は、ふつうは法律の額そのものです。同じ観測（同じ額の系列・同じ期間・同じ額の幅）を複数の法律が共有するときは、同じ差を何度も数えないよう、観測の額を共有する本数で割ったものを法律の分とします。</p>
      <ol>
        <li>拒否権者（欠けたら成立しない）：提出者の組（閣法は閣議決定に関わった大臣、衆法は発議者）と、衆議院の賛成会派。</li>
        <li>参議院本会議：賛成した議員は互いに同じ立場で、可決には q ＝ (賛成＋反対)÷2 を切り捨てて＋1 票が要る。</li>
        <li>拒否権者 k 人・賛成 Y 人のとき、拒否権者1人の値 φ ＝ (1/n) Σ<sub>j=q..Y</sub> C(Y, j) ÷ C(n−1, j+k−1)（n ＝ k＋Y）。賛成1票の値 ＝ (1 − kφ) ÷ Y。</li>
        <li>提出者の組の値は、記録のある提出者で等分する。衆議院の賛成会派の値は、起立採決で個人の賛否が残らないため、党（会派）に置き、個人には配らない。</li>
        <li>委員長は、委員会の多数決と中間報告で採決を通せるため、基準では拒否権者にしない。委員長も拒否権者とした場合の額と順位を、各議員の欄に出す（5位以上動く人には注意を付ける）。</li>
        <li>質疑・修正案は成立したかどうかを変えないため配らない。記録として各議員の欄に出す。反対票は成立を決めていないため0円。</li>
        <li>数えるのは、行動（会議録・投票結果）→ 成立（議案の審議経過）→ 額（公的統計）がすべて一次資料でつながるものだけ。円の端数は最大剰余法で配り、人・会派・名前不明の賛成票の合計が法律の分にぴったり一致する。</li>
      </ol>
      <p>議員ランキングのページには見え方のつまみがあります。初期値は上の計算そのものです。提出者の重み（下げた分は衆議院の賛成会派と参議院の賛成票に今の割合で回す）、衆議院の分を党に置くか参議院の賛成議員で分けるか、委員長を拒否権者にするか、帰属率（残りは未帰属）を変えられます。どの設定でも割合の合計は1のままで、円は切り捨てるため、配る額の合計は法律の額を超えません。つまみの値は URL に入るので、その見え方のまま共有できます。</p>
      <p className="fine-note">例：参議院で賛成214・反対16（可決に116票）、拒否権者2つのとき、提出者の組は35.4%、賛成1票は0.137%。提出者が3人なら1人11.8%。</p>
      <h3>3. 点数</h3>
      <p>点数（純額）＝ 国士側の法律からの配分の合計 − 国賊側の法律からの配分の合計。マイナスが国賊側、プラスが国士側。同じ統計（観測グループ）の動きを複数の法律で数えている人は、合計が重なりを含むため、その旨を表示する。</p>
      <h3>3-2. 全議員の参考の額</h3>
      <p>議員ページの下の「全議員」には、現職の衆参全員と、過去に法律に関わった人を載せています。確かな額とは別の欄に、確かさ「参考」の法律の額を「参考」の印つきで配ります。同じ観測（同じ額の系列・同じ期間）を共有する法律は観測の額を本数で割ってから配り、同じ差を何度も数えないようにしています。配り方は上と同じ Shapley 値で、提出者は閣法なら提出時の内閣総理大臣、議員立法なら提出者の欄の人です。参議院の個人別の賛否が見つからない法律は、会派の分を人に配りません。参考の額は確かな額と足さず、順位も別です。</p>
      <h3>4. 訂正と反論</h3>
      <p>法律の一覧（法律ランキング）では、同じ観測（同じ額の系列・同じ期間）を共有する法律は、確かさの高い順（同じなら id の昇順）で先頭の1本を代表の行にして並べ、残りは「ほか N 本が同じ観測」から題名で見られます。額は観測ごとに1つなので、足し合わせません。また、額が窓の開始前最後の年の日本の全産業の名目付加価値（OECD 国民経済計算 表6）1年分を超える法律には「桁外れ」の印と倍率を付けます。額は変えず、順位からも外さず、参考にとどめる印です。</p>
      <p>誤り・反証・本人や関係者からの反論は、<a href={correctionUrl} target="_blank" rel="noopener noreferrer">GitHub の Issue（訂正・異議の申し立て）</a>で受け付けます。公開資料の出典を添えてください。確認できたものは記録を直し、同じ計算で額と順位を出し直します。受付後の流れは<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/corrections.md" target="_blank" rel="noopener noreferrer">訂正の手順</a>にあります。</p>
      <h3>5. 元のデータとコード</h3>
      <ul>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/involvements.csv" target="_blank" rel="noopener noreferrer">関与の一覧（行動・日付・一次資料の URL、外した行動と理由を含む）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/loss-rule.ts" target="_blank" rel="noopener noreferrer">損失の計算（loss-rule.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/app/src/causal-allocation.ts" target="_blank" rel="noopener noreferrer">成立への寄与の計算（causal-allocation.ts）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/allocation-v1/votes.csv" target="_blank" rel="noopener noreferrer">参議院本会議の票数（votes.csv）</a></li>
        <li><a href="/distribution/members.json">議員ページの配布データ（members.json）</a></li>
        <li><a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/計算式.md" target="_blank" rel="noopener noreferrer">計算式（docs/計算式.md）</a>・<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/データベース.md" target="_blank" rel="noopener noreferrer">データベース（docs/データベース.md）</a>・<a href="/numbers">数字で見る</a></li>
      </ul>
      <Suspense fallback={<p className="empty-state">式を読み込み中…</p>}><MethodFormulas /></Suspense>
    </main>
  </SiteShell>;
}
